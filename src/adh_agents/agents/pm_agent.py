"""PMAgent — product/requirements delivery; embeds Team OS Orchestrator."""

from __future__ import annotations

import asyncio
from typing import Any

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.pm.authoring import AuthoringProgrammeService
from src.adh_agents.programmes.pm.lead_tokens import (
    is_lead_outline_body,
    lock_token as _lock_token,
    outline_fingerprint,
)
from src.adh_agents.programmes.pm.meta_pm import MetaPmProgrammeService
from src.adh_agents.programmes.pm.outline_lock import OutlineLockMixin
from src.adh_agents.programmes.pm.pe_glue import PmPeGlueProgramme
from src.adh_agents.programmes.pm.rewind_coach import RewindCoachProgramme
from src.adh_agents.programmes.pm.task_lifecycle import TaskLifecycleProgramme
from src.adh_agents.programmes.pm.traj_coach import TrajCoachProgramme
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.catch_up import (
    latest_unacked_lead,
    open_gate_sessions,
    should_skip_catch_up,
)
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.runtime.room_resolve import (
    is_engg_room,
    listen_rooms_for_role,
    resolve_tenant_for_room,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import PmAgentSettings
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.redis_service import RedisService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.logging import get_logger
from src.models.buzz_models import (
    EventType,
    HeartbeatIngest,
    MessageCreate,
    MessageKind,
    MessageRead,
    TaskKind,
    TaskState,
)

logger = get_logger()

_PM_BATON_TYPES = frozenset({"pm.pe_questions", "pm.prd_merge_ready"})


class PMAgent(OutlineLockMixin, BaseHermesAgent):
    """Product / requirements agent. Control plane + PM programmes; no HermesService facade."""

    role_id = "adh.pm"
    programme_id = "meta-pm"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        redis: RedisService,
        tenants: TenantRegistryService,
        work_store: AgentWorkStore,
        orchestrator: Orchestrator,
        meta_pm: MetaPmProgrammeService,
        authoring: AuthoringProgrammeService,
        pe_glue: PmPeGlueProgramme,
        presence: PresenceService,
        task_lifecycle: TaskLifecycleProgramme,
        rewind_coach: RewindCoachProgramme,
        traj_coach: TrajCoachProgramme,
        autonomy: AutonomyPolicy,
    ) -> None:
        settings = PmAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings, presence=presence)
        self._redis = redis
        self._tenants = tenants
        self._work_store = work_store
        self._orchestrator = orchestrator
        self._meta_pm = meta_pm
        self._authoring = authoring
        self._pe_glue = pe_glue
        self._task_lifecycle = task_lifecycle
        self._rewind_coach = rewind_coach
        self._traj_coach = traj_coach
        self._autonomy = autonomy
        self._pm_settings = settings
        self._settings = HermesSettings.get_instance()
        self._inflight: dict[str, str] = {}
        self._outline_tasks: dict[str, asyncio.Task[None]] = {}

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._meta_pm)
        for tenant in self._tenants.active():
            await self.ensure_hub_member(tenant.ops_room)
        rooms = await listen_rooms_for_role(self._buzz, self._tenants, self.role_id)
        await self.start_ops_listeners(rooms)
        for room in rooms:
            if room.endswith("-ops"):
                await self.catch_up_ops(room)
            elif room.startswith("task-"):
                await self.catch_up_task_room(room)
        await self._catch_up_pending_batons()
        # God resume runs validate/skills — never block listener boot on it.
        task = asyncio.create_task(self._god_resume_stalled_inits())
        self._outline_tasks["__god_resume__"] = task
        task.add_done_callback(lambda t: self._outline_tasks.pop("__god_resume__", None))
        self.start_listen_refresh_loop(
            lambda: listen_rooms_for_role(self._buzz, self._tenants, self.role_id),
            interval_seconds=15.0,
            on_added=self._on_new_listen_rooms,
        )
        self.logger.info("PMAgent listening", rooms=rooms)

    async def _god_resume_stalled_inits(self) -> None:
        """God mode: promoted INIT with no open PM gate must not wait Lead `post-pm`."""
        if not self._autonomy.is_god:
            return
        for tenant in self._tenants.active():
            try:
                tasks = await self._buzz.list_tasks(tenant.slug, include_archived=False)
            except Exception:
                self.logger.exception("god resume list_tasks failed", tenant=tenant.slug)
                continue
            for task in tasks:
                if task.kind != TaskKind.INIT:
                    continue
                room = task.task_room_slug or tenant.ops_room
                # Delivery done → final archive gate (Hermes recommend; god auto-plays).
                if task.state == TaskState.DONE:
                    try:
                        await self._task_lifecycle.coach_archive(
                            tenant,
                            room,
                            task_id=task.task_id,
                            i_did=(
                                f"God e2e — delivery done for **{task.task_id}**; "
                                "opening archive gate."
                            ),
                            identity_handle=self.role_id,
                        )
                        self.logger.info(
                            "god archive coach for DONE INIT",
                            tenant=tenant.slug,
                            task_id=task.task_id,
                        )
                    except Exception:
                        self.logger.exception(
                            "god archive coach failed",
                            tenant=tenant.slug,
                            task_id=task.task_id,
                        )
                    continue
                # Halted forge/auth gates: reopen so Hermes recommend can auto-play.
                if task.state == TaskState.HALTED:
                    try:
                        await self._meta_pm.resume_programme(tenant, room, task.task_id)
                        self.logger.info(
                            "god resumed halted INIT",
                            tenant=tenant.slug,
                            task_id=task.task_id,
                        )
                    except Exception:
                        self.logger.exception(
                            "god resume halted failed",
                            tenant=tenant.slug,
                            task_id=task.task_id,
                        )
                    continue
                if task.state not in {TaskState.GATED, TaskState.RUNNING, TaskState.BOUND}:
                    continue
                try:
                    resumed = await self._authoring.god_resume_awaiting_post_pm(
                        tenant, room, task.task_id
                    )
                except Exception:
                    self.logger.exception(
                        "god resume post-pm failed",
                        tenant=tenant.slug,
                        task_id=task.task_id,
                    )
                    continue
                if resumed:
                    self.logger.info(
                        "god resumed INIT past promote",
                        tenant=tenant.slug,
                        task_id=task.task_id,
                        room=room,
                    )

    async def _on_new_listen_rooms(self, rooms: list[str]) -> None:
        for room in rooms:
            if room.startswith("task-"):
                await self.catch_up_task_room(room)

    async def catch_up_task_room(self, room: str) -> None:
        """Replay at most the newest unacked Lead token — and only with an open PM gate.

        Never re-run historical C2 / post-pm / outline chatter on every boot when the
        initiative has already moved on (e.g. KB land waiting on ``go ahead``).
        """
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
        if tenant is None:
            return
        active = await self._work_store.list_active(tenant.slug, self.role_id)
        gates = open_gate_sessions(active)
        if not gates:
            logger.info(
                "task-room catch_up skipped — no open PM gate",
                room=room,
                tenant=tenant.slug,
            )
            return
        page = await self._buzz.list_messages(room, limit=40)

        def _lead_gate_line(message: MessageRead) -> bool:
            if not self._is_lead_text(message):
                return False
            # Outline bodies belong on hub; task room Lead lines are gate tokens.
            return not self._is_lead_outline(message)

        tip = latest_unacked_lead(page.items, is_lead=_lead_gate_line)
        if tip is None:
            logger.info(
                "task-room catch_up skipped — no unacked Lead tip",
                room=room,
                tenant=tenant.slug,
            )
            return
        await self.handle_ops_message(room, tip)

    async def _catch_up_pending_batons(self) -> None:
        for tenant in self._tenants.active():
            for baton_type in _PM_BATON_TYPES:
                pending = await self._batons.list_pending_for(
                    tenant=tenant.slug, to_role=self.role_id, baton_type=baton_type
                )
                for baton in pending:
                    await self._pe_glue.handle_baton(baton, room=baton.ops_room or tenant.ops_room)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
        if tenant is None:
            return
        payload = message.payload or {}
        if (
            payload.get("status") == "baton_emitted"
            and payload.get("baton_type") in _PM_BATON_TYPES
            and payload.get("idempotency_key")
        ):
            baton = await self._batons.get(
                tenant=str(payload.get("tenant") or tenant.slug),
                idempotency_key=str(payload["idempotency_key"]),
            )
            if baton is not None:
                await self._pe_glue.handle_baton(baton, room=room)
                return
        # `#engg-*` is Dev YAML floor — never steal Lead for product authoring.
        if is_engg_room(room) and self._is_lead_text(message):
            return
        if self._is_lead_text(message):
            task_hint = room[len("task-") :].upper() if room.startswith("task-") else None
            if await self._rewind_coach.handle_lead(
                tenant,
                room,
                body=message.body or "",
                lead_handle=self._settings.lead_handle,
                task_id=task_hint,
            ):
                return
            if await self._traj_coach.handle_lead(
                tenant,
                room,
                body=message.body or "",
                task_id=task_hint,
            ):
                return
            if await self._task_lifecycle.handle_lead_token(
                tenant,
                room,
                body=message.body or "",
                lead_handle=self._settings.lead_handle,
            ):
                return
        if await self._try_lead_stop(tenant, room, message):
            return
        if self._is_lead_text(message) and await self._orchestrator.handle_lead_message(
            tenant, room, message
        ):
            return
        if await self._authoring.handle_lead_message(tenant, room, message):
            return
        if not self._is_lead_outline(message):
            return
        # Outlines bind on hub; army talk continues in the task room.
        await self._start_outline(tenant, room, message)

    async def catch_up_ops(self, room: str) -> None:
        """Replay recent unacked Lead outlines; skip when role already has work."""
        tenant = self._tenants.by_ops_room(room)
        if tenant is not None and await should_skip_catch_up(
            self._work_store, tenant.slug, self.role_id
        ):
            return
        page = await self._buzz.list_messages(room, limit=200)
        rows = page.items
        seen: set[str] = set()
        pending: list[MessageRead] = []
        for message in rows:
            if not self._is_lead_outline(message):
                continue
            fingerprint = outline_fingerprint(message.body)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            if _outline_already_acked(rows, fingerprint):
                continue
            pending.append(message)
        for message in pending:
            await self.handle_ops_message(room, message)

    async def emit_pe_review_after_draft_pr(
        self,
        *,
        tenant_slug: str,
        ops_room: str,
        initiative: str,
        pr_url: str = "",
        artefact_refs: list[str] | None = None,
    ) -> Baton | None:
        if not self._pm_settings.emit_pe_review_baton:
            return None
        baton = Baton(
            type="pe.review",
            from_role=self.role_id,
            to_role="adh.pe",
            tenant=tenant_slug,
            ops_room=ops_room,
            initiative=initiative,
            idempotency_key=f"pe.review:{tenant_slug}:{initiative}:{pr_url or 'draft'}",
            payload={
                "pr_url": pr_url,
                "stage": "gate1_review",
                "note": "PE worker claims pe.review on Team OS",
            },
            artefact_refs=list(artefact_refs or []),
        )
        stored, _created = await self.emit_baton(baton)
        return stored

    async def _start_outline(self, tenant, room: str, message: MessageRead) -> None:
        fingerprint = outline_fingerprint(message.body)
        token = _lock_token(tenant.slug, fingerprint)
        if token in self._inflight:
            owner = self._inflight.get(token) or await self._redis.get(
                self._lock_key(tenant.slug, fingerprint)
            )
            await self._status(
                room,
                "Duplicate outline — already in progress.",
                EventType.STALL,
                {
                    "status": "duplicate",
                    "outline_fingerprint": fingerprint,
                    "programme_slug": tenant.slug,
                    "in_progress_source": owner,
                },
            )
            return
        source_id = str(message.id) if message.id else ""
        claimed = await self._claim_outline(tenant.slug, fingerprint, source_id)
        if not claimed:
            await self._status(
                room,
                "Duplicate outline — already in progress.",
                EventType.STALL,
                {
                    "status": "duplicate",
                    "outline_fingerprint": fingerprint,
                    "programme_slug": tenant.slug,
                    "source_message_id": source_id,
                },
            )
            return
        await self._status(
            room,
            (
                f"Outline received for `{tenant.slug}` "
                f"(branch `{tenant.integration_branch}`, meta `{tenant.meta_repo}`)."
            ),
            EventType.START,
            {
                "status": "received",
                "outline_fingerprint": fingerprint,
                "programme_slug": tenant.slug,
                "source_message_id": source_id,
            },
        )

        async def _run() -> None:
            try:
                await self._authoring.start_outline(
                    tenant,
                    room,
                    message.body,
                    fingerprint=fingerprint,
                    source_id=source_id,
                    source_message_id=message.id,
                )
            finally:
                await self._release_outline(tenant.slug, fingerprint)

        self._track_outline_task(tenant.slug, fingerprint, asyncio.create_task(_run()))

    def _is_lead_text(self, message: MessageRead) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        return (message.identity_handle or "") == self._settings.lead_handle

    def _is_lead_outline(self, message: MessageRead) -> bool:
        if not self._is_lead_text(message):
            return False
        return is_lead_outline_body(message.body, min_chars=int(self._settings.outline_min_chars))

    def _track_outline_task(self, slug: str, fingerprint: str, task: asyncio.Task[None]) -> None:
        key = f"{slug}:{fingerprint}"
        prior = self._outline_tasks.pop(key, None)
        if prior is not None and not prior.done():
            prior.cancel()
        self._outline_tasks[key] = task

        def _done(done: asyncio.Task[None]) -> None:
            if self._outline_tasks.get(key) is done:
                self._outline_tasks.pop(key, None)

        task.add_done_callback(_done)

    async def _status(
        self,
        room: str,
        body: str,
        event: EventType,
        payload: dict[str, Any],
    ) -> None:
        await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=self.role_id,
                body=body,
                kind=MessageKind.EVENT,
                event_type=event,
                payload={**payload, "lane": "pm", "role": self.role_id},
            ),
        )
        try:
            await self._buzz.ingest_heartbeat(
                HeartbeatIngest(
                    identity_handle=self.role_id,
                    room_slug=room,
                    body=body[:200],
                    event_type=event,
                    payload={"service": "adh_agents", "role": self.role_id},
                )
            )
        except Exception:
            self.logger.exception("PM status heartbeat failed")


def _outline_already_acked(rows: list[MessageRead], fingerprint: str) -> bool:
    for message in rows:
        payload = message.payload or {}
        if payload.get("outline_fingerprint") == fingerprint and payload.get("status") in {
            "received",
            "duplicate",
            "done",
        }:
            return True
    return False
