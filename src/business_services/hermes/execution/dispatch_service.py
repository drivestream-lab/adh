"""Execute phase: run catalogue skill nodes and Lead-authorized forge actions."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.cursor_cli_service import ProgressCallback
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_skill_runner_service import PmSkillRunnerService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.workflow_catalogue_service import WorkflowCatalogueService
from src.models.hermes.catalogue_models import WorkflowNodeDocument
from src.models.hermes.execution_models import (
    ForgeActionRequest,
    ForgeActionResult,
    SkillRunResult,
)
from src.models.tenant_models import TenantContext


class HermesDispatchService(BaseBusinessService):
    """Dispatch skill and external-action nodes; authorization is enforced here."""

    @inject
    def __init__(
        self,
        catalogue: WorkflowCatalogueService,
        skills: PmSkillRunnerService,
        forge: ForgeActionService,
        workspace: PmWorkspaceService,
    ) -> None:
        super().__init__()
        self._catalogue = catalogue
        self._skills = skills
        self._forge = forge
        self._workspace = workspace

    async def run_skill_node(
        self,
        tenant: TenantContext,
        node_id: str,
        initiative: str,
        *,
        on_progress: Optional[ProgressCallback] = None,
    ) -> SkillRunResult:
        snap = self._catalogue.snapshot()
        try:
            node = snap.node(node_id)
        except KeyError as exc:
            raise ValidationError(f"unknown workflow node: {node_id}") from exc
        if not node.is_skill():
            raise ValidationError(f"node {node_id!r} is type {node.type!r}, not a skill")
        try:
            skill = snap.skill(node_id)
        except KeyError as exc:
            raise ValidationError(f"no catalogue skill for node {node_id!r}") from exc
        raw = await self._skills.run_skill(
            tenant,
            skill.skill_id,
            initiative,
            on_progress=on_progress,
        )
        return SkillRunResult.model_validate(raw)

    async def run_catalog_skill(
        self,
        tenant: TenantContext,
        skill_id: str,
        initiative: str,
        *,
        extra_prompt: str = "",
        on_progress: Optional[ProgressCallback] = None,
    ) -> SkillRunResult:
        """Run a skill from the SKILL.md index (not every skill is a workflow node)."""
        key = skill_id.lstrip("/")
        snap = self._catalogue.snapshot()
        try:
            skill = snap.skill(key)
        except KeyError as exc:
            raise ValidationError(f"unknown catalogue skill: {skill_id!r}") from exc
        raw = await self._skills.run_skill(
            tenant,
            skill.skill_id,
            initiative,
            extra_prompt=extra_prompt,
            on_progress=on_progress,
        )
        return SkillRunResult.model_validate(raw)

    async def run_hermes_copy(
        self,
        tenant: TenantContext,
        copy_id: str,
        variables: dict[str, str],
        *,
        on_progress: Optional[ProgressCallback] = None,
        label: str = "hermes-copy",
    ) -> SkillRunResult:
        """Run a Hermes-owned prompt (not a prayog skill) via the Cursor runner."""
        raw = await self._skills.run_hermes_copy(
            tenant,
            copy_id,
            variables,
            on_progress=on_progress,
            label=label,
        )
        return SkillRunResult.model_validate(
            {
                "exit_code": raw.get("exit_code", 1),
                "output": raw.get("output") or "",
                "model": raw.get("model") or "",
                "skill": copy_id,
                "ok": bool(raw.get("ok")),
            }
        )

    async def run_external_action(
        self,
        tenant: TenantContext,
        node: WorkflowNodeDocument,
        initiative: str,
        *,
        authorized: bool,
        slots: dict[str, str],
    ) -> ForgeActionResult:
        """Run ``node.forge.action``. ``slots`` supplies title/body_path/head_branch/repo."""
        if not node.is_external_action():
            raise ValidationError(f"node {node.node_id!r} is not an external action")
        if node.forge is None or not (node.forge.action or "").strip():
            raise ValidationError(f"node {node.node_id!r} declares no forge action")
        if node.requires_explicit_authorization() and not authorized:
            raise ValidationError(f"node {node.node_id!r} requires explicit Lead authorization")
        missing = [name for name in ("body_path", "head_branch") if not slots.get(name)]
        if missing:
            raise ValidationError(
                f"forge action {node.forge.action!r} is missing inputs: {', '.join(missing)}"
            )
        request = ForgeActionRequest(
            app=self._workspace.pm_app_role(),
            repo=slots.get("repo") or tenant.meta_repo,
            title=slots.get("title") or f"{initiative}: {node.node_id}",
            body_path=slots["body_path"],
            head_branch=slots["head_branch"],
            draft=node.forge.draft if node.forge.draft is not None else True,
            labels=list(node.forge.apply_labels),
        )
        return await self._forge.run_action(
            tenant,
            node.forge.action or "",
            app=request.app,
            title=request.title,
            body_path=request.body_path,
            head_branch=request.head_branch,
            draft=request.draft,
            labels=request.labels,
            repo=request.repo,
        )
