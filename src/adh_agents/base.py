"""BaseHermesAgent — enabler: Buzz listen/broadcast, batons, forge ACL hooks."""

from __future__ import annotations

import abc
import asyncio
from typing import Any, Callable, Coroutine, Optional

from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.forge_acl import forge_allowed
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
    ) -> None:
        super().__init__()
        self._buzz = buzz
        self._batons = batons
        self._agent_settings = settings
        self.role_id = settings.role_id or self.role_id
        self._listen_tasks: list[asyncio.Task[None]] = []
        self._work_tasks: set[asyncio.Task[None]] = set()

    @abc.abstractmethod
    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        """Process one ops-room message for this role."""

    def assert_forge(self, action: str) -> None:
        if not forge_allowed(self.role_id, action):
            raise PermissionError(f"forge action {action!r} denied for role {self.role_id}")

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

    async def emit_baton(self, baton: Baton) -> tuple[Baton, bool]:
        ttl = int(self._agent_settings.baton_ttl_seconds)
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        notice = (
            f"baton `{baton.type}` → `{baton.to_role}` "
            f"(init={baton.initiative or '—'}; correlation={baton.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
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
                        "baton_id": stored.id,
                        "baton_type": stored.type,
                        "to_role": stored.to_role,
                        "created": created,
                        "correlation_id": stored.correlation_id,
                    },
                ),
            )
        except Exception:
            logger.exception("baton notice post failed", baton_type=baton.type)
        return stored, created

    async def start_ops_listeners(self, rooms: list[str]) -> None:
        for room in rooms:
            task = asyncio.create_task(self._listen_ops(room))
            self._listen_tasks.append(task)
        self.logger.info("Agent ops listeners scheduled", role=self.role_id, rooms=rooms)

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
        await super().close()

    async def _listen_ops(self, room: str) -> None:
        delay = 1.0
        while True:
            stream = self._buzz.stream_room(room)
            try:
                await anext(stream)
                delay = 1.0
                self.logger.info("Agent listener subscribed", role=self.role_id, room=room)
                async for raw in stream:
                    message = _parse_stream_message(raw)
                    if message is not None:
                        await self.handle_ops_message(room, message)
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
    if not isinstance(raw, dict) or raw.get("type") in {"ping", "subscribed"}:
        return None
    data = raw.get("message") or raw.get("data") or raw
    if not isinstance(data, dict):
        return None
    try:
        return MessageRead.model_validate(data)
    except Exception:
        return None
