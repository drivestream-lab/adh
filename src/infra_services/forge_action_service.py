"""Forge side-effects declared by the workflow catalogue / role ACL."""

from __future__ import annotations

from pathlib import Path

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
    ) -> ForgeActionResult:
        """PE Gate‑1 attest: APPROVE review + impact-map label projection.

        Delivery policy (prd-impact-map): on Approve exact head remove
        pending/blocked/revised/stale and add ``impact-map-lgtm``.
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
            await self._github.replace_issue_labels(
                token,
                repo,
                issue_number=pr_number,
                add=["impact-map-lgtm"],
                remove=[
                    "impact-map-pending",
                    "impact-map-blocked",
                    "impact-map-revised",
                    "impact-map-stale",
                ],
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

    async def prd_merge(
        self,
        *,
        app: AppRole,
        repo: str,
        pr_number: int,
        commit_title: str,
    ) -> ForgeActionResult:
        """Merge meta PRD PR after Lead authorize (GitHub permissions still apply).

        Draft PRs cannot be merged (GitHub 405) — convert to ready_for_review first.
        """
        token, _ = await self._github.installation_token(app, write=True, repositories=[repo])
        try:
            await self._github.mark_ready_for_review(token, repo, pr_number=pr_number)
        except Exception as exc:
            # Already ready, or App lacks draft conversion — merge may still work if not draft.
            logger.info(
                "ready_for_review before merge skipped/failed",
                repo=repo,
                pr=pr_number,
                error=str(exc)[:200],
            )
        sha = await self._github.merge_pull_request(
            token,
            repo,
            pr_number=pr_number,
            commit_title=commit_title,
        )
        return ForgeActionResult(action=_PRD_MERGE, repo=repo, pr_number=pr_number, url=sha)
