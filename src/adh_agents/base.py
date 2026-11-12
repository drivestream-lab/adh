"""BaseHermesAgent — enabler: Buzz listen/broadcast, batons, forge ACL hooks."""

from __future__ import annotations

import abc
import asyncio
from typing import Any, Callable, Coroutine, Optional

from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.gate_coach import TokenAction, format_human_next
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.settings import AgentSettings
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger
from src.models.buzz_models import (
    EventType,
    HeartbeatIngest,
    MessageCreate,
    MessageKind,
    MessageRead,
    RoomMemberCreate,
    TaskEventCreate,
    TaskEventKind,
)

logger = get_logger()

ProgressCallback = Callable[[str], Coroutine[Any, Any, None]]


class BaseHermesAgent(BaseBusinessService, abc.ABC):
    """Enabler base for responsibility agents. Subclasses override handle_ops_message."""

    role_id: str = "adh.agent"

    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        settings: AgentSettings,
        *,
        presence: Optional[PresenceService] = None,
    ) -> None:
        super().__init__()
        self._buzz = buzz
        self._batons = batons
        self._agent_settings = settings
        self._presence = presence
        self.role_id = settings.role_id or self.role_id
        self._listen_tasks: list[asyncio.Task[None]] = []
        self._work_tasks: set[asyncio.Task[None]] = set()
        self._listening_rooms: set[str] = set()

    @abc.abstractmethod
    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        """Process one ops-room message for this role."""

    def assert_forge(self, action: str) -> None:
        if not forge_allowed(self.role_id, action):
            raise PermissionError(f"forge action {action!r} denied for role {self.role_id}")

    async def ack_received(
        self,
        room: str,
        *,
        lead_body: str,
        source_message_id: str | None = None,
    ) -> MessageRead:
        """Base premise: immediate ingest ack before long work (Lead must never see silence)."""
        from src.adh_agents.surface.buzz_poster import _lead_snippet

        snippet = _lead_snippet(lead_body)
        quoted = f"`{snippet}`" if snippet else "your message"
        return await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=self.role_id,
                body=f"Got it — working on {quoted}.",
                kind=MessageKind.EVENT,
                event_type=EventType.START,
                payload={
                    "status": "received",
                    "ack": True,
                    "role": self.role_id,
                    "source_message_id": source_message_id or "",
                },
            ),
        )

    async def broadcast_progress(
        self,
        room: str,
        body: str,
        *,
        payload: Optional[dict[str, Any]] = None,
    ) -> MessageRead:
        return await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=self.role_id,
                body=body,
                kind=MessageKind.EVENT,
                event_type=EventType.PROGRESS,
                payload=payload or {"status": "still_working", "role": self.role_id},
            ),
        )

    def still_working_callback(
        self,
        room: str,
        *,
        hop: str,
        initiative: str,
        label: str = "",
    ) -> ProgressCallback:
        steps = int(self._agent_settings.wait_steps)
        interval = float(self._agent_settings.progress_seconds)
        state = {"step": 0}

        async def _on_progress(_msg: str) -> None:
            state["step"] += 1
            step = int(state["step"])
            if step > steps:
                logger.warning(
                    "Agent hop exceeded wait_steps",
                    role=self.role_id,
                    hop=hop,
                    initiative=initiative,
                    step=step,
                    steps=steps,
                )
            elapsed = int(step * interval)
            body = f"still working ({min(step, steps)}/{steps}, ~{elapsed}s)"
            if label:
                body = f"{label}: {body}"
            await self.broadcast_progress(
                room,
                body,
                payload={
                    "status": "still_working",
                    "hop": hop,
                    "initiative": initiative,
                    "wait_step": step,
                    "wait_steps": steps,
                    "role": self.role_id,
                },
            )
            try:
                await self._buzz.ingest_heartbeat(
                    HeartbeatIngest(
                        identity_handle=self.role_id,
                        room_slug=room,
                        body=body,
                        event_type=EventType.PROGRESS,
                        payload={"service": "adh_agents", "role": self.role_id},
                    )
                )
            except Exception:
                logger.exception("progress heartbeat failed", role=self.role_id, hop=hop)

        return _on_progress

    async def post_human_next(
        self,
        room: str,
        *,
        i_did: str,
        recommend: str,
        outside_adh: str,
        tokens: list[TokenAction],
        recommend_why: str = "",
        evidence: str = "",
        human_role: str = "Lead",
        hop: str = "",
        example: str = "",
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
    ) -> MessageRead:
        """Post the helpful-army coach for one open human gate (working role only)."""
        body = format_human_next(
            i_did=i_did,
            recommend=recommend,
            outside_adh=outside_adh,
            tokens=tokens,
            recommend_why=recommend_why,
            evidence=evidence,
            human_role=human_role,
            hop=hop,
            example=example,
        )
        return await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=self.role_id,
                body=body,
                kind=MessageKind.EVENT,
                event_type=event_type,
                payload={
                    **(payload or {}),
                    "status": (payload or {}).get("status") or "human_next",
                    "role": self.role_id,
                    "coach": True,
                },
            ),
        )

    async def ensure_hub_member(self, hub_room: str) -> None:
        """Join tenant hub roster on boot (idempotent)."""
        try:
            await self._buzz.ensure_member(
                RoomMemberCreate(room_slug=hub_room, identity_handle=self.role_id)
            )
        except Exception:
            logger.exception("hub member ensure failed", role=self.role_id, room=hub_room)

    async def emit_baton(self, baton: Baton) -> tuple[Baton, bool]:
        ttl = int(self._agent_settings.baton_ttl_seconds)
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        # Idempotent re-emit: log only — never spam ops with "(idempotent) baton…".
        if not created:
            logger.info(
                "baton emit idempotent (no Buzz)",
                baton_type=stored.type,
                baton_id=stored.id,
                correlation_id=stored.correlation_id,
                initiative=stored.initiative,
            )
            return stored, created
        notice = (
            f"@{stored.to_role} baton `{baton.type}` "
            f"(init={baton.initiative or '—'}; correlation={baton.correlation_id})"
        )
        try:
            await self._buzz.post_message(
                baton.ops_room,
                MessageCreate(
                    identity_handle=self.role_id,
                    body=notice,
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": "baton_emitted",
                        "collab": True,
                        "baton_id": stored.id,
                        "baton_type": stored.type,
                        "to_role": stored.to_role,
                        "created": True,
                        "correlation_id": stored.correlation_id,
                        "idempotency_key": stored.idempotency_key,
                        "tenant": stored.tenant,
                        "initiative": stored.initiative,
                    },
                ),
            )
        except Exception:
            logger.exception("baton notice post failed", baton_type=baton.type)
        await self._append_baton_event(stored, purpose="emit")
        return stored, created

    async def post_collab_baton(
        self,
        room: str,
        *,
        body: str,
        status: str,
        baton: Baton,
        mention: str = "",
    ) -> None:
        """CollabPost for claim/done sites (emit already posts on create)."""
        text = (body or "").strip()
        if mention and f"@{mention}" not in text:
            text = f"@{mention} {text}".strip()
        try:
            await self._buzz.post_message(
                room,
                MessageCreate(
                    identity_handle=self.role_id,
                    body=text,
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": status,
                        "collab": True,
                        "baton_id": baton.id,
                        "baton_type": baton.type,
                        "tenant": baton.tenant,
                        "initiative": baton.initiative,
                    },
                ),
            )
        except Exception:
            logger.exception("collab post failed", status=status, baton_type=baton.type)

    async def start_ops_listeners(self, rooms: list[str]) -> None:
        added = await self.ensure_listening(rooms)
        if added:
            self.logger.info("Agent ops listeners scheduled", role=self.role_id, rooms=added)

    async def ensure_listening(self, rooms: list[str]) -> list[str]:
        """Subscribe to any rooms not yet listened; return newly added slugs.

        Also joins the Buzz roster so desktop presence strips show the bot
        (membership ≠ SSE — both are required).
        """
        added: list[str] = []
        for room in rooms:
            if not room or room in self._listening_rooms:
                continue
            try:
                await self._buzz.ensure_member(
                    RoomMemberCreate(room_slug=room, identity_handle=self.role_id)
                )
            except Exception:
                logger.exception("listen room member ensure failed", role=self.role_id, room=room)
            self._listening_rooms.add(room)
            task = asyncio.create_task(self._listen_ops(room))
            self._listen_tasks.append(task)
            added.append(room)
        return added

    def start_listen_refresh_loop(
        self,
        rooms_provider,
        *,
        interval_seconds: float = 15.0,
        on_added=None,
    ) -> None:
        """Periodically discover hub+task rooms and subscribe (Floor multi-room)."""

        async def _loop() -> None:
            delay = max(5.0, float(interval_seconds))
            while True:
                try:
                    rooms = await rooms_provider()
                    added = await self.ensure_listening(list(rooms or []))
                    if added and on_added is not None:
                        await on_added(added)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.logger.exception("listen refresh failed", role=self.role_id)
                await asyncio.sleep(delay)

        task = asyncio.create_task(_loop())
        self._listen_tasks.append(task)

    async def close(self) -> None:
        tasks = [*self._listen_tasks, *self._work_tasks]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._listen_tasks = []
        self._work_tasks.clear()
        self._listening_rooms.clear()
        await super().close()

    async def _presence_heartbeat(self, room: str) -> None:
        if self._presence is None:
            return
        tenant = ""
        if room.endswith("-ops"):
            tenant = room[: -len("-ops")]
        elif room.startswith("task-"):
            task = await self._buzz.get_task_by_room_slug(room)
            tenant = task.tenant_slug if task is not None else ""
        elif room.startswith("engg-"):
            from src.adh_agents.runtime.room_resolve import task_id_from_engg_room

            engg_id = task_id_from_engg_room(room)
            if engg_id:
                # Prefer task row; fall back to INIT prefix → tenant slug.
                try:
                    # Buzz get_task needs tenant — scan via task room naming:
                    # engg-init-realworld-002 ↔ task-init-realworld-002.
                    task = await self._buzz.get_task_by_room_slug(f"task-{engg_id.lower()}")
                    tenant = task.tenant_slug if task is not None else ""
                except Exception:
                    tenant = ""
                if not tenant and engg_id.lower().startswith("init-"):
                    # INIT-REALWORLD-002 → realworld (strip INIT- prefix segment).
                    parts = engg_id.split("-")
                    if len(parts) >= 3:
                        tenant = parts[1].lower()
        if not tenant:
            return
        try:
            await self._presence.heartbeat(
                tenant=tenant,
                role_id=self.role_id,
                state="listening",
                ttl_seconds=int(self._agent_settings.presence_ttl_seconds),
            )
        except Exception:
            logger.exception("presence heartbeat failed", role=self.role_id, room=room)

    async def _append_baton_event(self, baton: Baton, *, purpose: str) -> None:
        init = (baton.initiative or "").strip().upper()
        if not init:
            return
        try:
            await self._buzz.append_task_event(
                TaskEventCreate(
                    tenant_slug=baton.tenant,
                    task_id=init,
                    kind=TaskEventKind.BATON,
                    role_id=self.role_id,
                    purpose=purpose,
                    token=baton.type,
                    payload={"baton_id": baton.id, "to_role": baton.to_role},
                )
            )
        except Exception:
            logger.exception(
                "baton trajectory write failed",
                baton_type=baton.type,
                initiative=init,
            )

    async def _listen_ops(self, room: str) -> None:
        delay = 1.0
        while True:
            stream = self._buzz.stream_room(room)
            try:
                await anext(stream)
                delay = 1.0
                self.logger.info("Agent listener subscribed", role=self.role_id, room=room)
                await self._presence_heartbeat(room)
                async for raw in stream:
                    message = _parse_stream_message(raw)
                    if message is not None:
                        await self._presence_heartbeat(room)
                        await self.handle_ops_message(room, message)
                    else:
                        # ping / idle — still refresh presence
                        await self._presence_heartbeat(room)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Agent listener stopped", role=self.role_id, room=room)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
            finally:
                try:
                    await stream.aclose()
                except Exception:
                    self.logger.exception(
                        "Agent listener stream close failed", role=self.role_id, room=room
                    )


def _parse_stream_message(raw: Any) -> Optional[MessageRead]:
    """Buzz SSE yields JSON strings (same contract as former HermesService listener)."""
    import json

    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        data = raw
    else:
        return None
    if not isinstance(data, dict) or data.get("type") in {"ping", "subscribed"}:
        return None
    try:
        return MessageRead.model_validate(data)
    except Exception:
        return None
