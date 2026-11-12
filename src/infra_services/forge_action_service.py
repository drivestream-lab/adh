"""Forge side-effects declared by the workflow catalogue / role ACL."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from injector import inject

from src.exceptions.app_exceptions import ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.infra_services.github_app_service import GitHubAppService
from src.logging import get_logger
from src.models.hermes.execution_models import ForgeActionResult
from src.models.orchestrator_models import AppRole
from src.models.tenant_models import TenantContext

logger = get_logger()

_OPEN_DRAFT_PR = "open_draft_pr"
_COMMENT_PR = "comment_pr"
_APPROVE_ATTESTATION = "approve_attestation"
_PRD_MERGE = "prd_merge"
_READY_FOR_REVIEW = "ready_for_review"
_CREATE_BOARD_TICKETS = "create_board_tickets"
_ISSUE_WRITE_PERMS = {
    "issues": "write",
    "metadata": "read",
    "contents": "read",
    "pull_requests": "read",
}
# GitHub grants org Projects V2 as organization_projects (not ``projects``).
_ORG_PROJECTS_WRITE_PERMS = {
    "organization_projects": "write",
    "metadata": "read",
}


class ForgeActionService(BaseInfraService):
    """Run one forge action. The action id is passed in from the catalogue / programme."""

    @inject
    def __init__(self, github: GitHubAppService) -> None:
        super().__init__()
        self._github = github
        self._initialized = False

    async def initialize(self) -> None:
        self._initialized = True
        logger.info("Created ForgeActionService")

    async def close(self) -> None:
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized

    async def run_action(
        self,
        tenant: TenantContext,
        action: str,
        *,
        app: AppRole,
        title: str,
        body_path: str,
        head_branch: str,
        draft: bool,
        labels: list[str],
        repo: str,
    ) -> ForgeActionResult:
        """Catalogue path for ``open_draft_pr`` (body from file on disk)."""
        if action != _OPEN_DRAFT_PR:
            raise ValidationError(f"unsupported forge action via run_action: {action!r}")
        body_file = Path(body_path).expanduser()
        if not body_file.is_absolute():
            body_file = Path(tenant.meta_root).expanduser() / body_path
        if not body_file.is_file():
            raise ValidationError(f"forge body file missing: {body_file}")
        token, _granted = await self._github.installation_token(
            app,
            write=True,
            repositories=[repo],
        )
        number, url = await self._github.create_pull_request(
            token,
            repo,
            title=title,
            body=body_file.read_text(encoding="utf-8"),
            head=head_branch,
            base=tenant.integration_branch,
            draft=draft,
            labels=labels,
        )
        logger.info(
            "Forge action finished",
            slug=tenant.slug,
            action=action,
            repo=repo,
            pr=number,
        )
        return ForgeActionResult(action=action, repo=repo, pr_number=number, url=url)

    async def comment_pr(
        self,
        *,
        app: AppRole,
        repo: str,
        pr_number: int,
        body: str,
    ) -> ForgeActionResult:
        token, _ = await self._github.installation_token(app, write=True, repositories=[repo])
        url = await self._github.create_issue_comment(
            token, repo, issue_number=pr_number, body=body
        )
        return ForgeActionResult(action=_COMMENT_PR, repo=repo, pr_number=pr_number, url=url)

    async def approve_attestation(
        self,
        *,
        app: AppRole,
        repo: str,
        pr_number: int,
        body: str,
        commit_id: str | None = None,
        gate_labels: bool = True,
        label_add: list[str] | None = None,
        label_remove: list[str] | None = None,
    ) -> ForgeActionResult:
        """APPROVE on exact head + optional gate label projection.

        Default labels = Gate 1 (impact-map). Gate 2 (spec) callers pass
        ``label_add=["spec-lgtm"]`` / remove ``spec-pending`` family — same
        delivery rule as PRD: labels move + attestation before merge.
        """
        token, _ = await self._github.installation_token(app, write=True, repositories=[repo])
        sha = commit_id or await self._github.pull_head_sha(token, repo, pr_number=pr_number)
        url = await self._github.create_pull_review(
            token,
            repo,
            pr_number=pr_number,
            body=body,
            event="APPROVE",
            commit_id=sha,
        )
        if gate_labels:
            add = list(label_add) if label_add is not None else ["impact-map-lgtm"]
            remove = (
                list(label_remove)
                if label_remove is not None
                else [
                    "impact-map-pending",
                    "impact-map-blocked",
                    "impact-map-revised",
                    "impact-map-stale",
                ]
            )
            await self._github.replace_issue_labels(
                token,
                repo,
                issue_number=pr_number,
                add=add,
                remove=remove,
            )
        return ForgeActionResult(
            action=_APPROVE_ATTESTATION, repo=repo, pr_number=pr_number, url=url
        )

    async def ready_for_review(
        self,
        *,
        app: AppRole,
        repo: str,
        pr_number: int,
    ) -> ForgeActionResult:
        """Mark draft PR ready for review."""
        token, _ = await self._github.installation_token(app, write=True, repositories=[repo])
        await self._github.mark_ready_for_review(token, repo, pr_number=pr_number)
        from src.configs.orchestrator_settings import OrchestratorSettings

        org = OrchestratorSettings.get_instance().github_org
        url = f"https://github.com/{org}/{repo}/pull/{pr_number}"
        return ForgeActionResult(action=_READY_FOR_REVIEW, repo=repo, pr_number=pr_number, url=url)

    async def land_pull_request(
        self,
        *,
        app: AppRole,
        repo: str,
        pr_number: int,
        commit_title: str,
        action: str = _PRD_MERGE,
        pre_approve_app: AppRole | None = None,
        pre_approve_body: str = "",
        gate_label_add: list[str] | None = None,
        gate_label_remove: list[str] | None = None,
    ) -> ForgeActionResult:
        """Undraft (fail-closed), optional APPROVE + gate labels, then merge.

        Shared by product + knowledge + Spec lands. Knowledge PRs have no PE
        attest, so callers pass ``pre_approve_app`` (typically adh-reviewer)
        after Lead authorize on Buzz. Spec lands pass Gate 2 label sets so
        ``spec-pending`` → ``spec-lgtm`` before merge (delivery workflow).
        """
        token, _ = await self._github.installation_token(app, write=True, repositories=[repo])
        # Draft PRs cannot merge (405). Undraft via GraphQL must succeed before merge.
        await self._github.mark_ready_for_review(token, repo, pr_number=pr_number)
        want_labels = bool(gate_label_add or gate_label_remove)
        if pre_approve_app is not None:
            # Branch protection (required reviews) otherwise returns 405 on merge.
            await self.approve_attestation(
                app=pre_approve_app,
                repo=repo,
                pr_number=pr_number,
                body=pre_approve_body
                or "Lead authorized land on Buzz — forge APPROVE for branch protection.",
                gate_labels=want_labels,
                label_add=gate_label_add,
                label_remove=gate_label_remove,
            )
        elif want_labels:
            # Same-app / no reviewer: still project gate labels before merge.
            await self._github.replace_issue_labels(
                token,
                repo,
                issue_number=pr_number,
                add=list(gate_label_add or []),
                remove=list(gate_label_remove or []),
            )
        sha = await self._github.merge_pull_request(
            token,
            repo,
            pr_number=pr_number,
            commit_title=commit_title,
        )
        return ForgeActionResult(action=action, repo=repo, pr_number=pr_number, url=sha)

    async def prd_merge(
        self,
        *,
        app: AppRole,
        repo: str,
        pr_number: int,
        commit_title: str,
    ) -> ForgeActionResult:
        """Merge meta product PR after Lead authorize (thin wrapper on land_pull_request)."""
        return await self.land_pull_request(
            app=app,
            repo=repo,
            pr_number=pr_number,
            commit_title=commit_title,
            action=_PRD_MERGE,
        )

    async def close_pull_request(
        self,
        *,
        app: AppRole,
        repo: str,
        pr_number: int,
        comment: str = "",
    ) -> ForgeActionResult:
        """Close a superseding / zombie draft PR (U5 hygiene)."""
        token, _ = await self._github.installation_token(app, write=True, repositories=[repo])
        await self._github.close_pull_request(
            token, repo, pr_number=pr_number, comment=comment or None
        )
        from src.configs.orchestrator_settings import OrchestratorSettings

        org = OrchestratorSettings.get_instance().github_org
        url = f"https://github.com/{org}/{repo}/pull/{pr_number}"
        return ForgeActionResult(action="close_pr", repo=repo, pr_number=pr_number, url=url)

    async def create_board_tickets(
        self,
        *,
        apps: list[AppRole],
        initiative: str,
        board_name: str,
        org: str,
        epic_repo: str,
        epic_title: str,
        epic_body: str,
        labels: list[str],
        waves: list[dict[str, Any]],
    ) -> ForgeActionResult:
        """Create EPIC + wave issues and attach them to the programme Project.

        Fully programmatic via GitHub App installation tokens — never ``gh`` CLI
        or user PATs. Requires ``issues: write`` and ``organization_projects: write``
        on at least one candidate App install.
        """
        if not apps:
            raise ValidationError("create_board_tickets requires ≥1 AppRole candidate")
        if not waves:
            raise ValidationError("create_board_tickets requires ≥1 wave")

        issue_app, issue_token = await self._mint_issues_token(apps, epic_repo)
        repos_needed = {epic_repo, *(str(w.get("repo") or epic_repo) for w in waves)}
        for repo in sorted(repos_needed):
            # Re-mint when repo differs (token may be repo-scoped).
            if repo != epic_repo:
                issue_app, issue_token = await self._mint_issues_token(apps, repo)
            if not await self._github.repo_has_issues(issue_token, repo):
                raise ValidationError(
                    f"repo {repo} has_issues=false — enable GitHub Issues before board seed"
                )
            for label in labels:
                await self._github.ensure_label(issue_token, repo, name=label)

        proj_token = await self._mint_org_projects_token(apps, epic_repo)
        if not proj_token:
            raise ValidationError(
                "no GitHub App installation grants organization_projects:write — "
                "grant Organization → Projects (read/write) on the engg App and "
                "accept the install; forge never uses gh CLI"
            )
        project_id, project_number, board_url = await self._github.resolve_org_project(
            proj_token, org=org, name=board_name
        )

        # Idempotent EPIC
        issue_app, issue_token = await self._mint_issues_token(apps, epic_repo)
        epic = await self._ensure_issue(
            issue_token,
            epic_repo,
            title=epic_title,
            body=epic_body,
            labels=labels,
            initiative_label=labels[0] if labels else initiative,
        )
        await self._github.add_issue_to_project(
            proj_token, project_id=project_id, content_node_id=epic["node_id"]
        )

        issue_urls = [str(epic["url"])]
        roles = ["EPIC"]
        for wave in waves:
            repo = str(wave.get("repo") or epic_repo).rsplit("/", 1)[-1]
            title = str(wave.get("title") or "").strip()
            body = str(wave.get("body") or "").strip()
            wid = str(wave.get("id") or "").strip()
            if not title or not wid:
                raise ValidationError(f"wave missing id/title: {wave!r}")
            if repo != epic_repo:
                _, issue_token = await self._mint_issues_token(apps, repo)
            created = await self._ensure_issue(
                issue_token,
                repo,
                title=title,
                body=body,
                labels=labels,
                initiative_label=labels[0] if labels else initiative,
            )
            # Parent link only when same repo (GitHub sub-issues are same-repo).
            if repo == epic_repo:
                await self._github.add_sub_issue(
                    issue_token,
                    repo,
                    parent_number=int(epic["number"]),
                    child_numeric_id=int(created["numeric_id"]),
                )
            await self._github.add_issue_to_project(
                proj_token, project_id=project_id, content_node_id=created["node_id"]
            )
            issue_urls.append(str(created["url"]))
            roles.append(wid)

        detail_lines = [
            f"# Board seed report — {initiative}",
            "",
            f"Board: {board_name} (#{project_number})",
            f"Board URL: {board_url}",
            f"App: {issue_app.app_id}",
            "",
            "## Result tree",
            "",
        ]
        for role, url in zip(roles, issue_urls, strict=True):
            detail_lines.append(f"- {role}: {url}")
        detail_lines.append("")
        detail_lines.append("signals.seeded: true")
        detail = "\n".join(detail_lines)

        logger.info(
            "Forge create_board_tickets finished",
            initiative=initiative,
            board=board_name,
            issues=len(issue_urls),
        )
        return ForgeActionResult(
            action=_CREATE_BOARD_TICKETS,
            repo=epic_repo,
            url=issue_urls[0],
            issue_urls=issue_urls,
            detail=detail,
        )

    async def _mint_issues_token(self, apps: list[AppRole], repo: str) -> tuple[AppRole, str]:
        """Mint ``issues: write`` for ``repo`` from the first capable installation."""
        short = repo.rsplit("/", 1)[-1]
        errors: list[str] = []
        for app in apps:
            listed = [str(r).strip().rsplit("/", 1)[-1] for r in (app.repos or [])]
            if listed and short not in listed:
                continue
            try:
                token, granted = await self._github.installation_token(
                    app,
                    write=True,
                    repositories=[short],
                    permissions=dict(_ISSUE_WRITE_PERMS),
                )
            except Exception as exc:  # noqa: BLE001 — try next app
                errors.append(f"app_id={app.app_id}: {exc}")
                continue
            if str(granted.get("issues") or "").lower() != "write":
                errors.append(f"app_id={app.app_id}: issues!={granted.get('issues')!r}")
                continue
            return app, token
        raise ValidationError(
            "no GitHub App installation grants issues:write for "
            f"{short} ({'; '.join(errors) or 'no candidates'})"
        )

    async def _mint_org_projects_token(self, apps: list[AppRole], repo: str) -> Optional[str]:
        """Mint ``organization_projects: write`` when an install grants it."""
        short = repo.rsplit("/", 1)[-1]
        for app in apps:
            listed = [str(r).strip().rsplit("/", 1)[-1] for r in (app.repos or [])]
            if listed and short not in listed:
                continue
            try:
                token, granted = await self._github.installation_token(
                    app,
                    write=True,
                    repositories=[short],
                    permissions=dict(_ORG_PROJECTS_WRITE_PERMS),
                )
            except Exception:  # noqa: BLE001 — try next app
                continue
            if str(granted.get("organization_projects") or "").lower() != "write":
                continue
            logger.info(
                "Minted organization_projects token for board seed",
                app_id=app.app_id,
                repo=short,
            )
            return token
        return None

    async def _ensure_issue(
        self,
        token: str,
        repo: str,
        *,
        title: str,
        body: str,
        labels: list[str],
        initiative_label: str,
    ) -> dict[str, Any]:
        """Reuse an existing issue with the same title + initiative label, else create."""
        existing = await self._github.list_issues_by_label(
            token, repo, label=initiative_label, state="open"
        )
        for row in existing:
            if str(row.get("title") or "").strip() == title:
                number = int(row["number"])
                from src.configs.orchestrator_settings import OrchestratorSettings

                org = OrchestratorSettings.get_instance().github_org
                url = str(row.get("html_url") or f"https://github.com/{org}/{repo}/issues/{number}")
                return {
                    "number": number,
                    "url": url,
                    "node_id": str(row.get("node_id") or ""),
                    "numeric_id": int(row.get("id") or 0),
                    "reused": True,
                }
        number, url, node_id, numeric_id = await self._github.create_issue(
            token, repo, title=title, body=body, labels=labels
        )
        return {
            "number": number,
            "url": url,
            "node_id": node_id,
            "numeric_id": numeric_id,
            "reused": False,
        }
