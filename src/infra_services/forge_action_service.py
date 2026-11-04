"""Forge side-effects declared by the workflow catalogue. Never merges."""

from __future__ import annotations

from pathlib import Path

from injector import inject

from src.exceptions.app_exceptions import ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.infra_services.github_app_service import GitHubAppService
from src.logging import get_logger
from src.models.orchestrator_models import AppRole
from src.models.hermes.execution_models import ForgeActionResult
from src.models.tenant_models import TenantContext

logger = get_logger()

_OPEN_DRAFT_PR = "open_draft_pr"


class ForgeActionService(BaseInfraService):
    """Run one forge action. The action id is passed in from the catalogue, not enumerated."""

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
        if action != _OPEN_DRAFT_PR:
            raise ValidationError(f"unsupported forge action: {action!r}")
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
