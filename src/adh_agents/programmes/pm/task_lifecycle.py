"""Lead archive / delete / keep-open tokens for durable Buzz tasks."""

from __future__ import annotations

from injector import inject

from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import (
    ARCHIVE_TASK,
    DELETE_TASK,
    KEEP_OPEN,
    normalize_reply,
)
from src.adh_agents.runtime.gate_opener import CoachSpec, GateOpener
from src.adh_agents.runtime.work_models import AWAITING_JUDGMENT, AgentWorkSession
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger
from src.models.buzz_models import EventType, TaskEventCreate, TaskEventKind, TaskState
from src.models.tenant_models import TenantContext

logger = get_logger()

_PROGRAMME = "task-lifecycle"


class TaskLifecycleProgramme:
    """Coach archive after done; god auto-plays ``archive task`` (never ``delete task``)."""

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        poster: HermesBuzzPoster,
        gates: GateOpener,
        briefs: HermesBriefService,
        store: AgentWorkStore,
    ) -> None:
        self._buzz = buzz
        self._poster = poster
        self._gates = gates
        self._briefs = briefs
        self._store = store

    async def coach_archive(
        self,
        tenant: TenantContext,
        room: str,
        *,
        task_id: str,
        i_did: str,
        identity_handle: str = "adh.pm",
    ) -> None:
        """Open archive gate via GateOpener — god plays Hermes recommend ``archive task``."""
        init = (task_id or "").strip().upper()
        if not init:
            return
        # Harness: delivery work complete → DONE; archive is the final gate.
        try:
            await self._buzz.set_task_state(
                tenant.slug, init, TaskState.DONE, role_id=identity_handle
            )
        except Exception:
            logger.exception("task state → done failed", tenant=tenant.slug, task_id=init)

        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=identity_handle,
            room=room,
            programme=_PROGRAMME,
            stage="task-archive",
            awaiting=AWAITING_JUDGMENT,
        )
        session.bind_initiative(init)
        brief = self._briefs.build_brief(
            purpose="task-archive",
            node_id="task-archive",
            question=f"Archive task `{init}` now that delivery is done?",
            example="Archive keeps history; delete purges the room (Lead-explicit only).",
            options=[
                f"{ARCHIVE_TASK} — archive the task room (keep history)",
                f"{KEEP_OPEN} — leave the task room active",
                f"{DELETE_TASK} — hard-delete room + messages",
            ],
            recommend=ARCHIVE_TASK,
            recommend_why="Put the task room away when the initiative is done — history stays.",
            reply_tokens=[ARCHIVE_TASK, KEEP_OPEN, DELETE_TASK],
        )
        god_token = await self._gates.open(
            session,
            brief=brief,
            coach=CoachSpec(
                i_did=i_did,
                recommend=ARCHIVE_TASK,
                recommend_why="Put the task room away when the initiative is done — history stays.",
                outside_adh="Confirm nothing else is open on this INIT before archiving.",
                tokens=[
                    TokenAction(ARCHIVE_TASK, "archive the task room (keep history)"),
                    TokenAction(KEEP_OPEN, "leave the task room active"),
                    TokenAction(DELETE_TASK, "hard-delete room + messages (Lead-explicit)"),
                ],
                hop="task-archive",
                payload={
                    "status": "need_archive",
                    "task_id": init,
                    "purpose": "task-archive",
                },
                identity_handle=identity_handle,
            ),
        )
        if god_token:
            await self.handle_lead_token(
                tenant,
                room,
                body=god_token,
                lead_handle="adh.system",
                task_id=init,
                ack=False,
            )
            await self._store.clear(tenant.slug, identity_handle, init)

    async def handle_lead_token(
        self,
        tenant: TenantContext,
        room: str,
        *,
        body: str,
        lead_handle: str,
        task_id: str | None = None,
        ack: bool = True,
    ) -> bool:
        """True when archive/delete/keep was applied."""
        token = normalize_reply(body, [ARCHIVE_TASK, DELETE_TASK, KEEP_OPEN])
        if token is None:
            return False
        if ack:
            await self._poster.ack_received(
                room,
                lead_body=body,
                identity_handle="adh.pm",
            )
        resolved = (task_id or "").strip().upper()
        if not resolved:
            # Infer from task room slug.
            if room.startswith("task-"):
                resolved = room[len("task-") :].upper()
            else:
                active = await self._buzz.list_tasks(tenant.slug, include_archived=False)
                if len(active) == 1:
                    resolved = active[0].task_id
                else:
                    await self._poster.post_status(
                        room,
                        "Say which task: reply from the task room, or include the INIT id.",
                        EventType.STALL,
                    )
                    return True
        if token == KEEP_OPEN:
            await self._poster.post_status(
                room,
                f"Keeping `{resolved}` open.",
                EventType.PROGRESS,
                {"status": "keep_open", "task_id": resolved},
            )
            return True
        if token == ARCHIVE_TASK:
            task = await self._buzz.archive_task(tenant.slug, resolved, archived_by=lead_handle)
            await self._poster.post_status(
                tenant.ops_room,
                f"Archived task `{task.task_id}` (`#{task.task_room_slug}`).",
                EventType.DONE,
                {"status": "task_archived", "task_id": task.task_id},
            )
            return True
        if token == DELETE_TASK:
            await self._buzz.append_task_event(
                TaskEventCreate(
                    tenant_slug=tenant.slug,
                    task_id=resolved,
                    kind=TaskEventKind.DELETE,
                    role_id=lead_handle,
                    purpose="delete",
                    token=DELETE_TASK,
                )
            )
            await self._buzz.delete_task(tenant.slug, resolved, deleted_by=lead_handle)
            await self._poster.post_status(
                tenant.ops_room,
                f"Deleted task `{resolved}` (room + messages purged).",
                EventType.DONE,
                {"status": "task_deleted", "task_id": resolved},
            )
            return True
        return False
