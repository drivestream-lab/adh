"""Run prayog PM skills in a tenant meta workspace via Cursor CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from injector import inject

from src.configs.hermes_settings import HermesSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.infra_services.cursor_cli_service import CursorCliService, ProgressCallback
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.prompt_service import PromptService
from src.logging import get_logger
from src.models.tenant_models import TenantContext

logger = get_logger()

_PM_APP_SLUG = "adh-dev-pm"


class PmSkillRunnerService(BaseInfraService):
    """Skill runner v0: Cursor CLI in meta_root with a skill-bound prompt."""

    @inject
    def __init__(
        self,
        cursor: CursorCliService,
        github: GitHubAppService,
        workspace: PmWorkspaceService,
        prompts: PromptService,
    ) -> None:
        super().__init__()
        self._cursor = cursor
        self._github = github
        self._workspace = workspace
        self._prompts = prompts
        self._settings = HermesSettings.get_instance()
        self._initialized = False

    async def initialize(self) -> None:
        self._initialized = True
        logger.info("Created PmSkillRunnerService")

    async def close(self) -> None:
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized

    async def run_skill(
        self,
        tenant: TenantContext,
        skill_id: str,
        initiative: str,
        *,
        extra_prompt: str = "",
        on_progress: Optional[ProgressCallback] = None,
        workspace: Optional[Path] = None,
        repo: str = "",
        prd_path: str = "",
        reports_dir: str = "",
    ) -> dict[str, Any]:
        if not self._settings.pm_skill_runner_enabled:
            raise ValidationError("PM skill runner is disabled")
        root = Path(workspace).expanduser() if workspace else Path(tenant.meta_root).expanduser()
        if not root.is_dir():
            raise ValidationError(f"skill workspace missing: {root}")
        prompt = self._prompts.render_copy(
            "hermes.pm.skill.invoke",
            {
                "skill": skill_id.lstrip("/"),
                "initiative": initiative,
                "prd_path": (prd_path or f"prd/{initiative}.md").strip(),
                "reports_dir": (reports_dir or "prd/reports").strip(),
                "extra": (extra_prompt or "").strip() or "(none)",
            },
        )
        token = await self._mint_token(tenant, repo=(repo or "").strip() or None)
        bot = "adh-dev[bot]" if repo else "adh-dev-pm[bot]"
        code, output, model = await self._cursor.run(
            workspace=root,
            prompt=prompt,
            mode="force",
            github_token=token,
            git_name=bot,
            git_email=f"{bot}@users.noreply.github.com",
            write=True,
            on_progress=on_progress,
            heartbeat_seconds=float(self._settings.progress_seconds),
            timeout_seconds=float(self._settings.wait_budget_seconds()),
        )
        logger.info(
            "PM skill runner finished",
            slug=tenant.slug,
            skill=skill_id,
            initiative=initiative,
            repo=repo or tenant.meta_repo,
            code=code,
            model=model,
        )
        return {
            "exit_code": code,
            "output": output,
            "model": model,
            "skill": skill_id,
            "ok": code == 0,
        }

    async def run_hermes_copy(
        self,
        tenant: TenantContext,
        copy_id: str,
        variables: dict[str, Any],
        *,
        on_progress: Optional[ProgressCallback] = None,
        label: str = "hermes-copy",
    ) -> dict[str, Any]:
        """Run a Hermes-owned copy prompt in the tenant meta workspace (agentic PM)."""
        if not self._settings.pm_skill_runner_enabled:
            raise ValidationError("PM skill runner is disabled")
        workspace = Path(tenant.meta_root).expanduser()
        if not workspace.is_dir():
            raise ValidationError(f"meta workspace missing: {workspace}")
        prompt = self._prompts.render_copy(copy_id, variables)
        token = await self._mint_token(tenant)
        code, output, model = await self._cursor.run(
            workspace=workspace,
            prompt=prompt,
            mode="force",
            github_token=token,
            git_name="adh-dev-pm[bot]",
            git_email="adh-dev-pm[bot]@users.noreply.github.com",
            write=True,
            on_progress=on_progress,
            heartbeat_seconds=float(self._settings.progress_seconds),
            timeout_seconds=float(self._settings.wait_budget_seconds()),
        )
        logger.info(
            "Hermes copy runner finished",
            slug=tenant.slug,
            copy_id=copy_id,
            label=label,
            code=code,
            model=model,
        )
        return {
            "exit_code": code,
            "output": output,
            "model": model,
            "copy_id": copy_id,
            "ok": code == 0,
        }

    async def _mint_token(self, tenant: TenantContext, *, repo: Optional[str] = None) -> str:
        roles_path = self._workspace._roles_path()
        if roles_path is None:
            raise ValidationError("roles.yaml missing; cannot mint PM GitHub token")
        target = (repo or "").strip() or tenant.meta_repo
        short = target.rsplit("/", 1)[-1]
        if short == tenant.meta_repo:
            from src.infra_services.pm_workspace_service import _pm_app

            app = _pm_app(roles_path)
            if tenant.meta_repo not in app.repos:
                raise ValidationError(f"{tenant.meta_repo} is not on identity {_PM_APP_SLUG}")
            token, _granted = await self._github.installation_token(
                app,
                write=True,
                repositories=[short],
            )
            return token

        from src.adh_agents.programmes.dev.forge_ops import app_for_repo, apps_with_installation

        candidates = [
            app_for_repo(self._workspace, short),
            *apps_with_installation(self._workspace),
        ]
        seen: set[int] = set()
        errors: list[str] = []
        for app in candidates:
            if app.app_id in seen:
                continue
            seen.add(app.app_id)
            try:
                token, _granted = await self._github.installation_token(
                    app,
                    write=True,
                    repositories=[short],
                )
                return token
            except ValidationError as exc:
                errors.append(f"app {app.app_id}: {exc}")
                continue
        detail = "; ".join(errors) or "no candidate apps"
        raise ValidationError(f"cannot mint GitHub token for repo {short!r} ({detail})")
