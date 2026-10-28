"""Mint GitHub App installation tokens. Never merges."""

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

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

    async def installation_token(
        self,
        app: AppRole,
        *,
        write: bool,
        repositories: Optional[list[str]] = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return (token, permissions). Scoped to `repositories` when given."""
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
        permissions: dict[str, str]
        if write:
            permissions = {
                "contents": "write",
                "pull_requests": "write",
                "checks": "write",
                "metadata": "read",
            }
        else:
            permissions = {"contents": "read", "metadata": "read"}
        payload: dict[str, Any] = {"permissions": permissions}
        repos = repositories if repositories is not None else list(app.repos)
        if repos:
            payload["repositories"] = repos
        url = (
            f"{self._settings.github_api.rstrip('/')}"
            f"/app/installations/{installation_id}/access_tokens"
        )
        response = await self._client.post(
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
        granted = body.get("permissions") or permissions
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
        response = await self._client.get(
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
        info = await self._client.get(f"{api}/repos/{org}/{repo}", headers=headers)
        if info.status_code in {401, 403, 404}:
            logger.info("GitHub push probe skipped", repo=repo, status=info.status_code)
            return int(info.status_code)
        default = str((info.json() or {}).get("default_branch") or "master")
        encoded = base64.b64encode(b"adh-g0-probe-must-fail").decode()
        response = await self._client.put(
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
                await self._client.request(
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
        info = await self._client.get(repo_url, headers=headers)
        info.raise_for_status()
        default = str(info.json()["default_branch"])
        ref = await self._client.get(f"{repo_url}/git/ref/heads/{default}", headers=headers)
        ref.raise_for_status()
        sha = str(ref.json()["object"]["sha"])
        existing = await self._client.get(f"{repo_url}/git/ref/heads/{branch}", headers=headers)
        if existing.status_code == 404:
            created = await self._client.post(
                f"{repo_url}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch}", "sha": sha},
            )
            created.raise_for_status()
        encoded = base64.b64encode(contents.encode()).decode()
        file_resp = await self._client.get(
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
        put = await self._client.put(
            f"{repo_url}/contents/{path}",
            headers=headers,
            json=payload,
        )
        if put.status_code >= 400:
            logger.info(
                "Kill PR content put", repo=repo, status=put.status_code, body=put.text[:300]
            )
        pulls = await self._client.get(
            f"{repo_url}/pulls",
            headers=headers,
            params={"state": "open", "head": f"{org}:{branch}"},
        )
        rows = pulls.json() if pulls.status_code < 400 else []
        if isinstance(rows, list) and rows:
            number = int(rows[0]["number"])
            url = str(rows[0].get("html_url") or f"https://github.com/{org}/{repo}/pull/{number}")
            return number, url
        created_pr = await self._client.post(
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

    async def probe_merge(self, token: str, repo: str, pr_number: int) -> int:
        """Attempt merge. Must not succeed. 403/405/422 is the G0 pass."""
        if self._client is None:
            raise RuntimeError("GitHub App service has not been initialized")
        org = self._settings.github_org
        response = await self._client.put(
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
        response = await self._client.get(
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
        response = await self._client.get(
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


def _token_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
