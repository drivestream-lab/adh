"""Execute a confirmed human rewind — traj, close drafts, purge, reopen."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.adh_agents.collaboration.temp_papers import (
    PurgeContext,
    buzz_purge_notice,
    execute_purge,
)
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.pm.authoring import AuthoringProgrammeService
from src.adh_agents.programmes.pm.meta_pm import MetaPmProgrammeService
from src.adh_agents.runtime.rewind import RewindTarget, RewindTargetId
from src.adh_agents.runtime.work_models import (
    AWAITING_NONE,
    PROGRAMME_AUTHORING,
    PROGRAMME_META_PM,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.buzz_service import BuzzService
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.logging import get_logger
from src.models.buzz_models import EventType, TaskEventCreate, TaskEventKind, TaskState
from src.models.tenant_models import TenantContext

logger = get_logger()


class RewindExecuteService:
    """Apply one confirmed ``RewindTarget`` for an INIT."""

    role_id = "adh.pm"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        poster: HermesBuzzPoster,
        store: AgentWorkStore,
        workspace: PmWorkspaceService,
        forge: ForgeActionService,
        authoring: AuthoringProgrammeService,
        meta_pm: MetaPmProgrammeService,
    ) -> None:
        self._buzz = buzz
        self._poster = poster
        self._store = store
        self._workspace = workspace
        self._forge = forge
        self._authoring = authoring
        self._meta_pm = meta_pm

    async def execute(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        target: RewindTarget,
        reason: str,
        tip_purpose: str,
        session: Optional[AgentWorkSession] = None,
        lead_handle: str = "",
    ) -> dict:
        init = (initiative or "").strip().upper()
        live = session or await self._store.load(tenant.slug, self.role_id, init)
        slots = dict(live.slots) if live is not None else {}
        outline = slots.get("authoring_outline") or slots.get("outline") or ""

        closed: list[str] = []
        if target.close_prs:
            closed = await self._close_open_drafts(tenant, room, slots, init)

        purged: list[str] = []
        try:
            listing = self._workspace.inventory(tenant)
            candidates = list(listing.think_paths or []) + list(listing.prd_paths or [])
        except Exception:
            candidates = []
        ctx = PurgeContext(
            initiative=init,
            meta_repo=tenant.meta_repo,
            candidates=candidates,
        )
        try:
            purged = execute_purge(self._workspace, tenant, target.purge_event, ctx)
        except Exception:
            logger.exception("rewind purge failed", initiative=init, target=target.id.value)

        await self._clear_sibling_sessions(tenant, init)
        await self._strip_forward_slots(tenant, init, live, outline=outline, target=target)

        await self._buzz.append_task_event(
            TaskEventCreate(
                tenant_slug=tenant.slug,
                task_id=init,
                kind=TaskEventKind.REWIND,
                role_id=lead_handle or self.role_id,
                purpose=target.id.value,
                token="confirm rewind",
                payload={
                    "from_purpose": tip_purpose,
                    "to_purpose": target.id.value,
                    "reason": reason,
                    "purged": purged,
                    "closed_prs": closed,
                },
            )
        )

        if purged:
            await self._poster.post_status(
                room,
                buzz_purge_notice(target.purge_event, init, purged),
                EventType.PROGRESS,
                {"status": "rewind_purged", "initiative": init, "paths": purged},
            )
        if closed:
            await self._poster.post_status(
                room,
                f"Closed draft PR(s) for rewind: {', '.join(closed)}.",
                EventType.PROGRESS,
                {"status": "rewind_closed_prs", "initiative": init, "prs": closed},
            )

        await self._reopen(tenant, room, init=init, target=target, outline=outline, tip=tip_purpose)

        await self._poster.post_status(
            room,
            (
                f"**Rewound** `{init}` → `{target.id.value}` "
                f"(from `{tip_purpose or '—'}`). Reason: {reason or '(none)'}."
            ),
            EventType.PROGRESS,
            {
                "status": "rewound",
                "initiative": init,
                "to_purpose": target.id.value,
                "from_purpose": tip_purpose,
                "reason": reason,
            },
        )
        return {
            "to_purpose": target.id.value,
            "purged": purged,
            "closed_prs": closed,
        }

    async def _close_open_drafts(
        self,
        tenant: TenantContext,
        room: str,
        slots: dict[str, str],
        init: str,
    ) -> list[str]:
        if not forge_allowed(self.role_id, "close_pull_request"):
            await self._poster.post_status(
                room,
                "Forge ACL denies `close_pull_request` for adh.pm — drafts left open.",
                EventType.STALL,
            )
            return []
        closed: list[str] = []
        pairs: list[tuple[str, int]] = []
        for key in ("pr_url", "pr_number"):
            raw = slots.get(key) or ""
            num = (
                _pr_number(raw) if key == "pr_url" else (_int(raw) if key == "pr_number" else None)
            )
            if num is not None:
                pairs.append((tenant.meta_repo, num))
        enrich_url = slots.get("enrich_pr") or ""
        enrich_num = _pr_number(enrich_url) or _int(slots.get("enrich_pr_number") or "")
        if enrich_num is not None:
            pairs.append((tenant.meta_repo, enrich_num))
        # Dedupe
        seen: set[tuple[str, int]] = set()
        app = self._workspace.pm_app_role()
        for repo, number in pairs:
            key = (repo, number)
            if key in seen:
                continue
            seen.add(key)
            try:
                result = await self._forge.close_pull_request(
                    app=app,
                    repo=repo,
                    pr_number=number,
                    comment=f"ADH rewind closed draft for {init}",
                )
                closed.append(result.url or f"{repo}#{number}")
            except Exception as exc:
                logger.exception("close draft PR failed", repo=repo, pr=number)
                await self._poster.post_status(
                    room,
                    f"Could not close draft PR #{number}: {str(exc)[:160]}",
                    EventType.STALL,
                )
        return closed

    async def _clear_sibling_sessions(self, tenant: TenantContext, init: str) -> None:
        for role in ("adh.pe", "adh.read", "adh.kb"):
            try:
                await self._store.clear(tenant.slug, role, init)
            except Exception:
                logger.exception("clear sibling session failed", role=role, initiative=init)

    async def _strip_forward_slots(
        self,
        tenant: TenantContext,
        init: str,
        live: Optional[AgentWorkSession],
        *,
        outline: str,
        target: RewindTarget,
    ) -> None:
        keep_outline = outline
        if live is None:
            live = AgentWorkSession(
                tenant_slug=tenant.slug,
                role_id=self.role_id,
                room=f"task-{init.lower()}" if init else tenant.ops_room,
                programme=PROGRAMME_AUTHORING,
            )
            live.bind_initiative(init)
        # Drop forge / forward markers; keep outline for authoring reopens.
        for key in list(live.slots.keys()):
            if key in {
                "pr_url",
                "pr_number",
                "enrich_pr",
                "enrich_pr_number",
                "merge_sha",
                "attestation_url",
                "head_branch",
                "title",
                "body_path",
                "resolution_path",
                "validation_path",
                "prd_path",
            }:
                live.slots.pop(key, None)
            if key.startswith("reply:"):
                live.slots.pop(key, None)
            if key.startswith("rewind_"):
                live.slots.pop(key, None)
        if target.id is RewindTargetId.START:
            live.slots.clear()
            live.programme = PROGRAMME_AUTHORING
            live.stage = "start"
        elif target.id in {
            RewindTargetId.AUTHORING_THINK,
            RewindTargetId.AUTHORING_QUALITY,
            RewindTargetId.AUTHORING_PROMOTE,
            RewindTargetId.GATE_REOPEN,
        }:
            live.programme = PROGRAMME_AUTHORING
            if keep_outline:
                live.slots["authoring_outline"] = keep_outline
            if target.id is not RewindTargetId.GATE_REOPEN:
                live.stage = target.resume_purpose or target.id.value
        else:
            live.programme = PROGRAMME_META_PM
            live.stage = target.resume_purpose or target.id.value
        live.open_brief = None
        live.awaiting = AWAITING_NONE
        live.handoff_outcome = None
        await self._store.save(live)
        try:
            await self._buzz.set_task_state(
                tenant.slug, init, TaskState.RUNNING, role_id=self.role_id
            )
        except Exception:
            logger.exception("rewind task state update failed", initiative=init)

    async def _reopen(
        self,
        tenant: TenantContext,
        room: str,
        *,
        init: str,
        target: RewindTarget,
        outline: str,
        tip: str,
    ) -> None:
        if target.id is RewindTargetId.GATE_REOPEN:
            # Prefer meta/authoring resume from remaining artefacts / stage.
            live = await self._store.load(tenant.slug, self.role_id, init)
            if live is not None and (live.programme == PROGRAMME_META_PM or live.stage):
                await self._meta_pm.resume_programme(tenant, room, init)
            else:
                await self._authoring.reopen_after_rewind(
                    tenant, room, initiative=init, target_id=target.id.value, outline=outline
                )
            return
        if target.id is RewindTargetId.START:
            await self._authoring.reopen_after_rewind(
                tenant, room, initiative=init, target_id=target.id.value, outline=""
            )
            return
        if target.id in {
            RewindTargetId.AUTHORING_THINK,
            RewindTargetId.AUTHORING_QUALITY,
            RewindTargetId.AUTHORING_PROMOTE,
        }:
            await self._authoring.reopen_after_rewind(
                tenant,
                room,
                initiative=init,
                target_id=target.id.value,
                outline=outline,
            )
            return
        # Mid-meta targets
        live = await self._store.load(tenant.slug, self.role_id, init)
        if live is not None:
            live.programme = PROGRAMME_META_PM
            live.stage = target.resume_purpose or target.id.value
            live.awaiting = AWAITING_NONE
            live.open_brief = None
            await self._store.save(live)
        await self._meta_pm.resume_programme(tenant, room, init)
        del tip  # recorded on traj already


def _pr_number(pr_url: str) -> Optional[int]:
    from src.adh_agents.runtime.agentic_extract import github_pull_number

    return github_pull_number(pr_url or "")


def _int(raw: str) -> Optional[int]:
    text = (raw or "").strip()
    return int(text) if text.isdigit() else None
