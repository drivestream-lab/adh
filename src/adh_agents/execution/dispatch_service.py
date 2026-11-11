"""Execute phase: run catalogue skill nodes and Lead-authorized forge actions."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.runtime.room_resolve import collaboration_room
from src.adh_agents.settings import PmAgentSettings
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.cursor_cli_service import ProgressCallback
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_skill_runner_service import PmSkillRunnerService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.workflow_catalogue_service import WorkflowCatalogueService
from src.models.buzz_models import EventType, MessageCreate, MessageKind
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
        batons: RedisBatonStore,
        buzz: BuzzService,
    ) -> None:
        super().__init__()
        self._catalogue = catalogue
        self._skills = skills
        self._forge = forge
        self._workspace = workspace
        self._batons = batons
        self._buzz = buzz
        self._pm_settings = PmAgentSettings.get_instance()

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
        filled = dict(slots)
        action = (node.forge.action or "").strip()
        if action == "open_draft_pr":
            filled = await self._ensure_prd_draft_slots(tenant, initiative, filled)
        missing = [name for name in ("body_path", "head_branch") if not filled.get(name)]
        if missing:
            raise ValidationError(
                f"forge action {action!r} is missing inputs: {', '.join(missing)}"
            )
        # Mid-lane wrote local-only; authorized forge pushes the draft head first.
        if action == "open_draft_pr":
            push_paths = [
                p
                for p in (
                    filled.get("prd_path"),
                    filled.get("body_path"),
                    filled.get("resolution_path"),
                    filled.get("validation_path"),
                )
                if p
            ]
            await self._workspace.push_paths_to_branch(
                tenant,
                branch=filled["head_branch"],
                relative_paths=push_paths,
                commit_message=f"docs({initiative}): forge draft head",
            )
        request = ForgeActionRequest(
            app=self._workspace.pm_app_role(),
            repo=filled.get("repo") or tenant.meta_repo,
            title=filled.get("title") or f"{initiative}: {node.node_id}",
            body_path=filled["body_path"],
            head_branch=filled["head_branch"],
            draft=node.forge.draft if node.forge.draft is not None else True,
            labels=list(node.forge.apply_labels),
        )
        result = await self._forge.run_action(
            tenant,
            action,
            app=request.app,
            title=request.title,
            body_path=request.body_path,
            head_branch=request.head_branch,
            draft=request.draft,
            labels=request.labels,
            repo=request.repo,
        )
        if action == "open_draft_pr":
            await self._emit_pe_review_baton(
                tenant,
                initiative=initiative,
                pr_url=result.url or "",
                artefact_refs=[filled.get("body_path") or "", filled.get("prd_path") or ""],
            )
        return result

    async def _emit_pe_review_baton(
        self,
        tenant: TenantContext,
        *,
        initiative: str,
        pr_url: str,
        artefact_refs: list[str],
    ) -> None:
        """Wave 0a Phase1 #1B — park pe.review until PE worker exists."""
        if not self._pm_settings.emit_pe_review_baton:
            return
        refs = [r for r in artefact_refs if r]
        collab = await collaboration_room(
            self._buzz, tenant, initiative=initiative, fallback=tenant.ops_room
        )
        baton = Baton(
            type="pe.review",
            from_role="adh.pm",
            to_role="adh.pe",
            tenant=tenant.slug,
            ops_room=collab,
            initiative=initiative,
            idempotency_key=f"pe.review:{tenant.slug}:{initiative}:{pr_url or 'draft'}",
            payload={
                "pr_url": pr_url,
                "stage": "gate1_review",
                "note": "PE worker claims pe.review on Team OS",
            },
            artefact_refs=refs,
        )
        ttl = int(self._pm_settings.baton_ttl_seconds)
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        notice = (
            f"@{baton.to_role} baton `pe.review` "
            f"(init={initiative}; waiting for PE; correlation={stored.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        try:
            await self._buzz.post_message(
                collab,
                MessageCreate(
                    identity_handle="adh.pm",
                    body=notice,
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": "baton_emitted",
                        "collab": True,
                        "baton_type": "pe.review",
                        "baton_id": stored.id,
                        "created": created,
                        "correlation_id": stored.correlation_id,
                        "idempotency_key": stored.idempotency_key,
                        "initiative": initiative,
                        "tenant": tenant.slug,
                    },
                ),
            )
        except Exception:
            self.logger.exception("pe.review baton notice failed", initiative=initiative)

    async def _ensure_prd_draft_slots(
        self,
        tenant: TenantContext,
        initiative: str,
        slots: dict[str, str],
    ) -> dict[str, str]:
        """Fill open_draft_pr slots for a meta PRD draft when the programme omitted them."""
        from src.adh_agents.programmes.pm.validation_report import (
            impact_map_path,
            resolution_path,
            validation_report_path,
        )
        from src.infra_services.pm_workspace_service import prd_path

        filled = dict(slots)
        init = (initiative or "").strip()
        if not init:
            return filled
        filled.setdefault("prd_path", prd_path(init))
        filled.setdefault("body_path", impact_map_path(init))
        filled.setdefault("resolution_path", resolution_path(init))
        filled.setdefault("validation_path", validation_report_path(init))
        filled.setdefault("head_branch", f"chore/{init}-prd")
        filled.setdefault("title", f"[{init}] PRD draft")
        filled.setdefault("repo", tenant.meta_repo)
        return filled
