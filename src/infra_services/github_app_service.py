"""Mint GitHub App installation tokens. Never merges."""

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx
from jose import jwt

from src.configs.orchestrator_settings import OrchestratorSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.orchestrator_models import AppRole

logger = get_logger()


class GitHubAppService(BaseInfraService):
    """JWT + installation token. Cursor CLI does not use LiteLLM."""

    def __init__(self) -> None:
        self._settings = OrchestratorSettings.get_instance()
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._client = httpx.AsyncClient(timeout=30.0)
        self._initialized = True
        logger.info("Initializing GitHub App service")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized and self._client is not None

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """HTTP call with transient retries (connect/timeout/5xx)."""
        from src.configs.hermes_settings import HermesSettings
        from src.utils.transient_retry import retry_transient

        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        settings = HermesSettings.get_instance()
        client = self._client

        async def once() -> httpx.Response:
            response = await client.request(method, url, **kwargs)
            if response.status_code in (408, 425, 429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"transient HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            return response

        short = url
        if "github.com" in url:
            short = url.split("github.com", 1)[-1][:96]
        return await retry_transient(
            once,
            attempts=int(settings.network_retry_attempts),
            backoff_seconds=float(settings.network_retry_backoff_seconds),
            label=f"github {method} {short}",
        )

    async def installation_token(
        self,
        app: AppRole,
        *,
        write: bool,
        repositories: Optional[list[str]] = None,
        permissions: Optional[dict[str, str]] = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return (token, permissions). Scoped to `repositories` when given.

        ``permissions`` overrides the default write/read set when the caller needs
        a narrower or different grant (e.g. ``issues: write`` for board seed).
        """
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        pem = Path(app.pem).expanduser()
        if not pem.is_file():
            raise ValidationError(f"GitHub App PEM not found: {pem}")
        now = datetime.now(UTC)
        encoded = jwt.encode(
            {
                "iat": int(now.timestamp()) - 10,
                "exp": int((now + timedelta(minutes=8)).timestamp()),
                "iss": str(app.app_id),
            },
            pem.read_text(),
            algorithm="RS256",
        )
        installation_id = app.installation_id
        if installation_id is None:
            installation_id = await self._installation_id(encoded, app.app_id)
        if permissions is not None:
            perms = dict(permissions)
        elif write:
            perms = {
                "contents": "write",
                "pull_requests": "write",
                "checks": "write",
                "metadata": "read",
            }
        else:
            perms = {"contents": "read", "metadata": "read"}
        payload: dict[str, Any] = {"permissions": perms}
        repos = repositories if repositories is not None else list(app.repos)
        if repos:
            payload["repositories"] = repos
        url = (
            f"{self._settings.github_api.rstrip('/')}"
            f"/app/installations/{installation_id}/access_tokens"
        )
        response = await self._request(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {encoded}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        token = str(body["token"])
        granted = body.get("permissions") or perms
        logger.info(
            "Minted GitHub App installation token",
            app_id=app.app_id,
            installation_id=installation_id,
            write=write,
            repositories=repos,
            permissions=granted,
        )
        return token, granted

    async def probe_repo(self, token: str, repo: str) -> int:
        """GET a repo as the App. 403/404 means this identity cannot use it."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        response = await self._request(
            "GET",
            f"{self._settings.github_api.rstrip('/')}/repos/{org}/{repo}",
            headers=_token_headers(token),
        )
        logger.info("GitHub repo probe", repo=repo, status=response.status_code)
        return int(response.status_code)

    async def probe_push(self, token: str, repo: str) -> int:
        """Attempt a contents write. 200/201 means this identity can push — G0 fail."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        info = await self._request("GET", f"{api}/repos/{org}/{repo}", headers=headers)
        if info.status_code in {401, 403, 404}:
            logger.info("GitHub push probe skipped", repo=repo, status=info.status_code)
            return int(info.status_code)
        default = str((info.json() or {}).get("default_branch") or "master")
        encoded = base64.b64encode(b"adh-g0-probe-must-fail").decode()
        response = await self._request(
            "PUT",
            f"{api}/repos/{org}/{repo}/contents/.g0-kill-must-not-land",
            headers=headers,
            json={
                "message": "adh-g0-probe-must-fail",
                "content": encoded,
                "branch": default,
            },
        )
        logger.info("GitHub push probe", repo=repo, status=response.status_code)
        if response.status_code in {200, 201}:
            sha = ((response.json() or {}).get("content") or {}).get("sha")
            if sha:
                await self._request(
                    "DELETE",
                    f"{api}/repos/{org}/{repo}/contents/.g0-kill-must-not-land",
                    headers=headers,
                    json={
                        "message": "revert adh-g0-probe",
                        "sha": sha,
                        "branch": default,
                    },
                )
        return int(response.status_code)

    async def ensure_kill_pr(
        self,
        token: str,
        repo: str,
        *,
        branch: str,
        path: str,
        contents: str,
        title: str,
    ) -> tuple[Optional[int], Optional[str]]:
        """Open (or reuse) a PR as this App. Fallback when Cursor did not land one."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        repo_url = f"{api}/repos/{org}/{repo}"
        info = await self._request("GET", repo_url, headers=headers)
        info.raise_for_status()
        default = str(info.json()["default_branch"])
        ref = await self._request("GET", f"{repo_url}/git/ref/heads/{default}", headers=headers)
        ref.raise_for_status()
        sha = str(ref.json()["object"]["sha"])
        existing = await self._request("GET", f"{repo_url}/git/ref/heads/{branch}", headers=headers)
        if existing.status_code == 404:
            created = await self._request(
                "POST",
                f"{repo_url}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch}", "sha": sha},
            )
            created.raise_for_status()
        encoded = base64.b64encode(contents.encode()).decode()
        file_resp = await self._request(
            "GET",
            f"{repo_url}/contents/{path}",
            headers=headers,
            params={"ref": branch},
        )
        payload: dict[str, Any] = {
            "message": "chore: G0 kill marker (backend App)",
            "content": encoded,
            "branch": branch,
        }
        if file_resp.status_code == 200:
            payload["sha"] = file_resp.json()["sha"]
        put = await self._request(
            "PUT",
            f"{repo_url}/contents/{path}",
            headers=headers,
            json=payload,
        )
        if put.status_code >= 400:
            logger.info(
                "Kill PR content put", repo=repo, status=put.status_code, body=put.text[:300]
            )
        pulls = await self._request(
            "GET",
            f"{repo_url}/pulls",
            headers=headers,
            params={"state": "open", "head": f"{org}:{branch}"},
        )
        rows = pulls.json() if pulls.status_code < 400 else []
        if isinstance(rows, list) and rows:
            number = int(rows[0]["number"])
            url = str(rows[0].get("html_url") or f"https://github.com/{org}/{repo}/pull/{number}")
            return number, url
        created_pr = await self._request(
            "POST",
            f"{repo_url}/pulls",
            headers=headers,
            json={
                "title": title,
                "head": branch,
                "base": default,
                "body": contents,
            },
        )
        if created_pr.status_code >= 400:
            logger.info(
                "Kill PR create",
                repo=repo,
                status=created_pr.status_code,
                body=created_pr.text[:300],
            )
            return None, None
        body = created_pr.json()
        number = int(body["number"])
        url = str(body.get("html_url") or f"https://github.com/{org}/{repo}/pull/{number}")
        logger.info("Opened kill PR", repo=repo, pr=number, url=url)
        return number, url

    async def create_pull_request(
        self,
        token: str,
        repo: str,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool,
        labels: list[str],
    ) -> tuple[int, str]:
        """Open a PR from an existing branch (optionally draft) and apply labels. Never merges."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        repo_url = f"{api}/repos/{org}/{repo}"
        created = await self._request(
            "POST",
            f"{repo_url}/pulls",
            headers=headers,
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
        if created.status_code == 422:
            # Idempotent open_draft_pr: head/base PR may already exist from a prior authorize.
            existing = await self._existing_pull_request(token, repo, head=head, base=base)
            if existing is not None:
                number, url = existing
                logger.info(
                    "Reusing existing pull request",
                    repo=repo,
                    pr=number,
                    url=url,
                    head=head,
                    base=base,
                )
                if labels:
                    labelled = await self._request(
                        "POST",
                        f"{repo_url}/issues/{number}/labels",
                        headers=headers,
                        json={"labels": labels},
                    )
                    labelled.raise_for_status()
                return number, url
        if created.status_code >= 400:
            logger.info(
                "GitHub create pull request failed",
                repo=repo,
                status=created.status_code,
                body=created.text[:300],
            )
            created.raise_for_status()
        payload = created.json()
        number = int(payload["number"])
        url = str(payload.get("html_url") or f"https://github.com/{org}/{repo}/pull/{number}")
        if labels:
            labelled = await self._request(
                "POST",
                f"{repo_url}/issues/{number}/labels",
                headers=headers,
                json={"labels": labels},
            )
            labelled.raise_for_status()
        logger.info("Opened pull request", repo=repo, pr=number, url=url, draft=draft)
        return number, url

    async def _existing_pull_request(
        self,
        token: str,
        repo: str,
        *,
        head: str,
        base: str,
    ) -> tuple[int, str] | None:
        """Return (number, url) for an open PR with the same head/base, else None."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        head_ref = head if ":" in head else f"{org}:{head}"
        listed = await self._request(
            "GET",
            f"{api}/repos/{org}/{repo}/pulls",
            headers=_token_headers(token),
            params={"state": "open", "head": head_ref, "base": base},
        )
        if listed.status_code >= 400:
            logger.info(
                "GitHub list pull requests failed",
                repo=repo,
                status=listed.status_code,
                body=listed.text[:300],
            )
            return None
        rows = listed.json()
        if not isinstance(rows, list) or not rows:
            return None
        payload = rows[0]
        number = int(payload["number"])
        url = str(payload.get("html_url") or f"https://github.com/{org}/{repo}/pull/{number}")
        return number, url

    async def put_text_file(
        self,
        token: str,
        repo: str,
        *,
        path: str,
        contents: str,
        branch: str,
        message: str,
        from_branch: str | None = None,
        reset_branch: bool = False,
    ) -> dict[str, Any]:
        """Create or update a file on `branch`. Never merges.

        ``from_branch`` (e.g. tenant ``integration_branch`` / ``develop``) is the
        tip used when creating or force-resetting ``branch``. Defaults to the
        repo default branch only when omitted — Spec/PRD lanes must pass develop.
        """
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        repo_url = f"{api}/repos/{org}/{repo}"
        await self._ensure_branch(
            repo_url,
            headers,
            branch,
            from_branch=from_branch,
            reset=reset_branch,
        )
        encoded = base64.b64encode(contents.encode("utf-8")).decode("ascii")
        api_path = "/".join(quote(part, safe="") for part in path.split("/") if part)
        file_url = f"{repo_url}/contents/{api_path}"
        existing = await self._request("GET", file_url, headers=headers, params={"ref": branch})
        payload: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if existing.status_code == 200:
            payload["sha"] = existing.json()["sha"]
        response = await self._request("PUT", file_url, headers=headers, json=payload)
        if response.status_code >= 400:
            logger.info(
                "GitHub content put failed",
                repo=repo,
                path=path,
                branch=branch,
                status=response.status_code,
                body=response.text[:300],
            )
            response.raise_for_status()
        body = response.json()
        content = body.get("content") or {}
        commit = body.get("commit") or {}
        sha = str(content.get("sha") or "")
        commit_sha = str(commit.get("sha") or "")
        html_url = str(content.get("html_url") or "")
        logger.info(
            "GitHub content put",
            repo=repo,
            path=path,
            branch=branch,
            sha=sha,
            commit=commit_sha,
        )
        return {
            "sha": sha,
            "commit_sha": commit_sha,
            "html_url": html_url,
            "path": path,
            "branch": branch,
        }

    async def delete_text_file(
        self,
        token: str,
        repo: str,
        *,
        path: str,
        branch: str,
        message: str,
    ) -> Optional[dict[str, Any]]:
        """Delete a file on `branch`. Never merges. Returns None if missing."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        repo_url = f"{api}/repos/{org}/{repo}"
        await self._ensure_branch(repo_url, headers, branch)
        api_path = "/".join(quote(part, safe="") for part in path.split("/") if part)
        file_url = f"{repo_url}/contents/{api_path}"
        existing = await self._request("GET", file_url, headers=headers, params={"ref": branch})
        if existing.status_code == 404:
            return None
        if existing.status_code >= 400:
            existing.raise_for_status()
        sha = str(existing.json().get("sha") or "")
        if not sha:
            return None
        response = await self._request(
            "DELETE",
            file_url,
            headers=headers,
            json={"message": message, "sha": sha, "branch": branch},
        )
        if response.status_code >= 400:
            logger.info(
                "GitHub content delete failed",
                repo=repo,
                path=path,
                branch=branch,
                status=response.status_code,
                body=response.text[:300],
            )
            response.raise_for_status()
        body = response.json() if response.content else {}
        commit = body.get("commit") or {}
        return {
            "commit_sha": str(commit.get("sha") or ""),
            "path": path,
            "branch": branch,
        }

    async def ensure_branch_from(
        self,
        token: str,
        repo: str,
        branch: str,
        *,
        from_branch: str,
        reset: bool = True,
    ) -> None:
        """Public: create/reset ``branch`` to tip of ``from_branch`` (never merge)."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        repo_url = f"{api}/repos/{org}/{repo}"
        await self._ensure_branch(
            repo_url,
            headers,
            branch,
            from_branch=from_branch,
            reset=reset,
        )

    async def _ensure_branch(
        self,
        repo_url: str,
        headers: dict[str, str],
        branch: str,
        *,
        from_branch: str | None = None,
        reset: bool = False,
    ) -> None:
        """Ensure ``branch`` exists; optionally force it onto ``from_branch`` tip.

        Delivery lanes must pass ``from_branch=tenant.integration_branch`` (develop).
        Falling back to GitHub ``default_branch`` is only for callers that omit it —
        many product repos still default to ``main``, which must not be Spec base.
        """
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        base_name = (from_branch or "").strip()
        if not base_name:
            info = await self._request("GET", repo_url, headers=headers)
            info.raise_for_status()
            base_name = str(info.json()["default_branch"])
        base = await self._request("GET", f"{repo_url}/git/ref/heads/{base_name}", headers=headers)
        if base.status_code >= 400:
            logger.info(
                "GitHub base branch missing",
                base=base_name,
                status=base.status_code,
                body=base.text[:300],
            )
            base.raise_for_status()
        sha = str(base.json()["object"]["sha"])
        ref = await self._request("GET", f"{repo_url}/git/ref/heads/{branch}", headers=headers)
        if ref.status_code == 200:
            current = str((ref.json().get("object") or {}).get("sha") or "")
            if not reset or current == sha:
                return
            updated = await self._request(
                "PATCH",
                f"{repo_url}/git/refs/heads/{branch}",
                headers=headers,
                json={"sha": sha, "force": True},
            )
            if updated.status_code >= 400:
                logger.info(
                    "GitHub reset branch failed",
                    branch=branch,
                    from_branch=base_name,
                    status=updated.status_code,
                    body=updated.text[:300],
                )
                updated.raise_for_status()
            logger.info(
                "Reset GitHub branch to base tip",
                branch=branch,
                from_branch=base_name,
                sha=sha[:8],
            )
            return
        created = await self._request(
            "POST",
            f"{repo_url}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if created.status_code >= 400 and created.status_code != 422:
            logger.info(
                "GitHub ensure branch failed",
                branch=branch,
                from_branch=base_name,
                status=created.status_code,
                body=created.text[:300],
            )
            created.raise_for_status()
        logger.info(
            "Ensured GitHub branch",
            branch=branch,
            from_branch=base_name,
            status=created.status_code,
        )

    async def create_issue_comment(
        self,
        token: str,
        repo: str,
        *,
        issue_number: int,
        body: str,
    ) -> str:
        """Post an issue/PR conversation comment. Returns html_url."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        created = await self._request(
            "POST",
            f"{api}/repos/{org}/{repo}/issues/{issue_number}/comments",
            headers=_token_headers(token),
            json={"body": body},
        )
        if created.status_code >= 400:
            logger.info(
                "GitHub create issue comment failed",
                repo=repo,
                issue=issue_number,
                status=created.status_code,
                body=created.text[:300],
            )
            created.raise_for_status()
        payload = created.json()
        url = str(payload.get("html_url") or "")
        logger.info("Posted GitHub issue comment", repo=repo, issue=issue_number, url=url)
        return url

    async def create_pull_review(
        self,
        token: str,
        repo: str,
        *,
        pr_number: int,
        body: str,
        event: str = "APPROVE",
        commit_id: str | None = None,
    ) -> str:
        """Submit a PR review (APPROVE / COMMENT / REQUEST_CHANGES). Returns html_url."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        payload: dict[str, Any] = {"body": body, "event": event}
        if commit_id:
            payload["commit_id"] = commit_id
        created = await self._request(
            "POST",
            f"{api}/repos/{org}/{repo}/pulls/{pr_number}/reviews",
            headers=_token_headers(token),
            json=payload,
        )
        if created.status_code >= 400:
            logger.info(
                "GitHub create pull review failed",
                repo=repo,
                pr=pr_number,
                status=created.status_code,
                body=created.text[:300],
            )
            created.raise_for_status()
        data = created.json()
        url = str(data.get("html_url") or "")
        logger.info(
            "Submitted GitHub pull review",
            repo=repo,
            pr=pr_number,
            event=event,
            url=url,
        )
        return url

    async def merge_pull_request(
        self,
        token: str,
        repo: str,
        *,
        pr_number: int,
        commit_title: str,
        merge_method: str = "squash",
    ) -> str:
        """Merge a PR. Returns merged commit SHA / url marker."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        merged = await self._request(
            "PUT",
            f"{api}/repos/{org}/{repo}/pulls/{pr_number}/merge",
            headers=_token_headers(token),
            json={
                "merge_method": merge_method,
                "commit_title": commit_title,
            },
        )
        if merged.status_code >= 400:
            logger.info(
                "GitHub merge pull request failed",
                repo=repo,
                pr=pr_number,
                status=merged.status_code,
                body=merged.text[:300],
            )
            merged.raise_for_status()
        data = merged.json()
        sha = str(data.get("sha") or "")
        logger.info("Merged pull request", repo=repo, pr=pr_number, sha=sha)
        return sha or f"https://github.com/{org}/{repo}/pull/{pr_number}"

    async def close_pull_request(
        self,
        token: str,
        repo: str,
        *,
        pr_number: int,
        comment: str | None = None,
    ) -> None:
        """Close a PR (zombie / superseding draft hygiene). Optionally comment first."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        if comment and comment.strip():
            await self.create_issue_comment(
                token, repo, issue_number=pr_number, body=comment.strip()
            )
        closed = await self._request(
            "PATCH",
            f"{api}/repos/{org}/{repo}/pulls/{pr_number}",
            headers=headers,
            json={"state": "closed"},
        )
        if closed.status_code >= 400:
            logger.info(
                "GitHub close pull request failed",
                repo=repo,
                pr=pr_number,
                status=closed.status_code,
                body=closed.text[:300],
            )
            closed.raise_for_status()
        logger.info("Closed pull request", repo=repo, pr=pr_number)

    async def replace_issue_labels(
        self,
        token: str,
        repo: str,
        *,
        issue_number: int,
        add: list[str],
        remove: list[str],
    ) -> None:
        """Add/remove issue/PR labels (projection). Does not invent *-lgtm policy."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        base = f"{api}/repos/{org}/{repo}/issues/{issue_number}/labels"
        for name in remove:
            deleted = await self._request(
                "DELETE",
                f"{base}/{quote(name, safe='')}",
                headers=headers,
            )
            if deleted.status_code >= 400 and deleted.status_code not in (404,):
                logger.info(
                    "GitHub remove label failed",
                    repo=repo,
                    issue=issue_number,
                    label=name,
                    status=deleted.status_code,
                    body=deleted.text[:200],
                )
                deleted.raise_for_status()
        if add:
            added = await self._request(
                "POST",
                base,
                headers=headers,
                json={"labels": add},
            )
            if added.status_code >= 400:
                logger.info(
                    "GitHub add labels failed",
                    repo=repo,
                    issue=issue_number,
                    labels=add,
                    status=added.status_code,
                    body=added.text[:200],
                )
                added.raise_for_status()
        logger.info(
            "Updated GitHub labels",
            repo=repo,
            issue=issue_number,
            add=add,
            remove=remove,
        )

    async def mark_ready_for_review(self, token: str, repo: str, *, pr_number: int) -> None:
        """Convert a draft PR to ready-for-review.

        GitHub has **no** REST ``…/pulls/{n}/ready_for_review`` route (404).
        Use GraphQL ``markPullRequestReadyForReview`` with the PR ``node_id``.
        No-op when the PR is already non-draft.
        """
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        meta = await self._request(
            "GET",
            f"{api}/repos/{org}/{repo}/pulls/{pr_number}",
            headers=headers,
        )
        if meta.status_code >= 400:
            logger.info(
                "GitHub ready_for_review: cannot load PR",
                repo=repo,
                pr=pr_number,
                status=meta.status_code,
                body=meta.text[:300],
            )
            meta.raise_for_status()
        raw_meta = meta.json()
        data = raw_meta if isinstance(raw_meta, dict) else {}
        if not bool(data.get("draft")):
            logger.info(
                "GitHub ready_for_review skipped — PR already ready",
                repo=repo,
                pr=pr_number,
            )
            return
        node_id = str(data.get("node_id") or "").strip()
        if not node_id:
            raise ValidationError(
                f"GitHub PR {org}/{repo}#{pr_number} has no node_id for ready_for_review"
            )
        # GraphQL is the supported convert-draft API.
        mutation = (
            "mutation($id: ID!) {"
            " markPullRequestReadyForReview(input: {pullRequestId: $id}) {"
            "  pullRequest { number isDraft }"
            " }"
            "}"
        )
        gql_headers = {
            **headers,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }
        response = await self._request(
            "POST",
            f"{api}/graphql",
            headers=gql_headers,
            json={"query": mutation, "variables": {"id": node_id}},
        )
        if response.status_code >= 400:
            logger.info(
                "GitHub ready_for_review GraphQL HTTP failed",
                repo=repo,
                pr=pr_number,
                status=response.status_code,
                body=response.text[:300],
            )
            response.raise_for_status()
        raw_gql = response.json()
        payload = raw_gql if isinstance(raw_gql, dict) else {}
        errors = payload.get("errors")
        if errors:
            msg = "; ".join(
                str(e.get("message") or e) for e in errors if isinstance(e, dict)
            ) or str(errors)
            logger.info(
                "GitHub ready_for_review GraphQL errors",
                repo=repo,
                pr=pr_number,
                errors=msg[:300],
            )
            raise ValidationError(
                f"GitHub markPullRequestReadyForReview failed for "
                f"{org}/{repo}#{pr_number}: {msg[:200]}"
            )
        logger.info("Marked pull request ready for review", repo=repo, pr=pr_number)

    async def pull_head_sha(self, token: str, repo: str, *, pr_number: int) -> str | None:
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        response = await self._request(
            "GET",
            f"{api}/repos/{org}/{repo}/pulls/{pr_number}",
            headers=_token_headers(token),
        )
        if response.status_code >= 400:
            return None
        data = response.json()
        head = data.get("head") if isinstance(data, dict) else None
        if not isinstance(head, dict):
            return None
        sha = head.get("sha")
        return str(sha) if sha else None

    async def probe_merge(self, token: str, repo: str, pr_number: int) -> int:
        """Attempt merge. Must not succeed. 403/405/422 is the G0 pass."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        response = await self._request(
            "PUT",
            f"{self._settings.github_api.rstrip('/')}/repos/{org}/{repo}/pulls/{pr_number}/merge",
            headers=_token_headers(token),
            json={"merge_method": "squash", "commit_title": "adh-g0-probe-must-fail"},
        )
        logger.info(
            "GitHub merge probe",
            repo=repo,
            pr=pr_number,
            status=response.status_code,
        )
        return int(response.status_code)

    async def latest_pr_number(self, token: str, repo: str) -> Optional[int]:
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        response = await self._request(
            "GET",
            f"{self._settings.github_api.rstrip('/')}/repos/{org}/{repo}/pulls",
            headers=_token_headers(token),
            params={"state": "open", "per_page": 5},
        )
        if response.status_code >= 400:
            return None
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            return None
        return int(rows[0]["number"])

    def merge_forbidden(self, pin_allow_merge: bool, granted: dict[str, Any]) -> bool:
        contents = str(granted.get("contents") or "none")
        return (not pin_allow_merge) or contents != "write"

    async def _installation_id(self, app_jwt: str, app_id: int) -> int:
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        response = await self._request(
            "GET",
            f"{self._settings.github_api.rstrip('/')}/app/installations",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        for row in response.json():
            if int(row.get("app_id") or 0) == app_id:
                return int(row["id"])
        raise ValidationError(f"no installation for GitHub App {app_id}")

    async def repo_has_issues(self, token: str, repo: str) -> bool:
        """True when GitHub Issues hosting is enabled for ``repo``."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        response = await self._request(
            "GET",
            f"{api}/repos/{org}/{repo}",
            headers=_token_headers(token),
        )
        response.raise_for_status()
        raw = response.json()
        data = raw if isinstance(raw, dict) else {}
        return bool(data.get("has_issues"))

    async def ensure_label(
        self,
        token: str,
        repo: str,
        *,
        name: str,
        color: str = "0E8A16",
        description: str = "initiative",
    ) -> None:
        """Create a repo label when missing (idempotent)."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        headers = _token_headers(token)
        encoded = quote(name, safe="")
        existing = await self._request(
            "GET",
            f"{api}/repos/{org}/{repo}/labels/{encoded}",
            headers=headers,
        )
        if existing.status_code == 200:
            return
        created = await self._request(
            "POST",
            f"{api}/repos/{org}/{repo}/labels",
            headers=headers,
            json={"name": name, "color": color, "description": description},
        )
        if created.status_code in (201, 422):
            return
        created.raise_for_status()

    async def list_issues_by_label(
        self,
        token: str,
        repo: str,
        *,
        label: str,
        state: str = "all",
    ) -> list[dict[str, Any]]:
        """List issues (not PRs) with ``label``."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        response = await self._request(
            "GET",
            f"{api}/repos/{org}/{repo}/issues",
            headers=_token_headers(token),
            params={"labels": label, "state": state, "per_page": 100},
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("pull_request"):
                continue
            out.append(row)
        return out

    async def create_issue(
        self,
        token: str,
        repo: str,
        *,
        title: str,
        body: str,
        labels: list[str],
    ) -> tuple[int, str, str, int]:
        """Create an issue. Returns (number, html_url, node_id, numeric_id)."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        created = await self._request(
            "POST",
            f"{api}/repos/{org}/{repo}/issues",
            headers=_token_headers(token),
            json={"title": title, "body": body, "labels": labels},
        )
        if created.status_code >= 400:
            logger.info(
                "GitHub create_issue failed",
                repo=repo,
                status=created.status_code,
                body=created.text[:300],
            )
            created.raise_for_status()
        data = created.json()
        number = int(data["number"])
        url = str(data.get("html_url") or f"https://github.com/{org}/{repo}/issues/{number}")
        node_id = str(data.get("node_id") or "")
        numeric_id = int(data.get("id") or 0)
        logger.info("Created GitHub issue", repo=repo, issue=number, url=url)
        return number, url, node_id, numeric_id

    async def add_sub_issue(
        self,
        token: str,
        repo: str,
        *,
        parent_number: int,
        child_numeric_id: int,
    ) -> None:
        """Link ``child`` as a sub-issue of ``parent`` (REST; idempotent-ish)."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        api = self._settings.github_api.rstrip("/")
        response = await self._request(
            "POST",
            f"{api}/repos/{org}/{repo}/issues/{parent_number}/sub_issues",
            headers=_token_headers(token),
            json={"sub_issue_id": child_numeric_id},
        )
        # 201 created; 422 when already linked / duplicate — treat as ok.
        if response.status_code in (201, 204, 422):
            logger.info(
                "Linked sub-issue",
                repo=repo,
                parent=parent_number,
                child_id=child_numeric_id,
                status=response.status_code,
            )
            return
        logger.info(
            "GitHub add_sub_issue failed",
            repo=repo,
            parent=parent_number,
            status=response.status_code,
            body=response.text[:300],
        )
        response.raise_for_status()

    async def resolve_org_project(
        self,
        token: str,
        *,
        org: str,
        name: str,
    ) -> tuple[str, int, str]:
        """Resolve Projects V2 by title. Returns (node_id, number, url)."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        api = self._settings.github_api.rstrip("/")
        query = (
            "query($org: String!, $q: String!) {"
            " organization(login: $org) {"
            "  projectsV2(first: 20, query: $q) {"
            "   nodes { id number title url }"
            "  }"
            " }"
            "}"
        )
        response = await self._request(
            "POST",
            f"{api}/graphql",
            headers={**_token_headers(token), "Content-Type": "application/json"},
            json={"query": query, "variables": {"org": org, "q": name}},
        )
        response.raise_for_status()
        raw = response.json()
        payload = raw if isinstance(raw, dict) else {}
        if payload.get("errors"):
            msg = "; ".join(
                str(e.get("message") or e) for e in payload["errors"] if isinstance(e, dict)
            )
            raise ValidationError(f"resolve org project GraphQL failed: {msg[:200]}")
        nodes = (
            ((payload.get("data") or {}).get("organization") or {}).get("projectsV2") or {}
        ).get("nodes") or []
        wanted = name.strip().lower()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = str(node.get("title") or "").strip()
            if title.lower() == wanted:
                node_id = str(node.get("id") or "")
                number = int(node.get("number") or 0)
                url = str(node.get("url") or "")
                if not node_id or not number:
                    break
                return node_id, number, url
        raise ValidationError(f"org project {name!r} not found for {org}")

    async def add_issue_to_project(
        self,
        token: str,
        *,
        project_id: str,
        content_node_id: str,
    ) -> None:
        """Add an issue to a Projects V2 board (idempotent on duplicate)."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        api = self._settings.github_api.rstrip("/")
        mutation = (
            "mutation($project: ID!, $content: ID!) {"
            " addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {"
            "  item { id }"
            " }"
            "}"
        )
        response = await self._request(
            "POST",
            f"{api}/graphql",
            headers={**_token_headers(token), "Content-Type": "application/json"},
            json={
                "query": mutation,
                "variables": {"project": project_id, "content": content_node_id},
            },
        )
        response.raise_for_status()
        raw = response.json()
        payload = raw if isinstance(raw, dict) else {}
        errors = payload.get("errors") or []
        if errors:
            msg = "; ".join(
                str(e.get("message") or e) for e in errors if isinstance(e, dict)
            ) or str(errors)
            # Duplicate / already present — accept.
            if "already" in msg.lower() or "duplicate" in msg.lower():
                logger.info("Project item already present", project=project_id)
                return
            raise ValidationError(f"addProjectV2ItemById failed: {msg[:200]}")
        logger.info("Added issue to project", project=project_id)


def _token_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
