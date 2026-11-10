"""Thin Buzz posting helper for Hermes status and briefs."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Optional, Sequence

from injector import inject

from src.adh_agents.collaboration.gate_coach import TokenAction, format_human_next
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.prompt_service import PromptService
from src.logging import get_logger
from src.models.buzz_models import (
    EventType,
    HeartbeatIngest,
    MessageCreate,
    MessageKind,
    MessageRead,
)

_HERMES_HANDLE = "adh.pm"
logger = get_logger()

ProgressCallback = Callable[[str], Coroutine[Any, Any, None]]


class HermesBuzzPoster:
    """Post Hermes messages to a room; optionally render YAML copy templates."""

    @inject
    def __init__(self, buzz: BuzzService, prompts: PromptService) -> None:
        self._buzz = buzz
        self._prompts = prompts
        self._settings = HermesSettings.get_instance()

    def copy(self, template_id: str, variables: Optional[dict[str, Any]] = None) -> str:
        return self._prompts.render_copy(template_id, variables or {})

    async def post_status(
        self,
        room: str,
        body: str,
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
        *,
        identity_handle: str | None = None,
    ) -> MessageRead:
        return await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=identity_handle or _HERMES_HANDLE,
                body=body,
                kind=MessageKind.EVENT,
                event_type=event_type,
                payload=payload,
            ),
        )

    async def ack_received(
        self,
        room: str,
        *,
        lead_body: str,
        identity_handle: str | None = None,
        source_message_id: str | None = None,
    ) -> MessageRead:
        """Base premise: immediate Buzz ack so Lead sees ingest before long work.

        Post this **first** on every consumed Lead/human message, then do the work
        (still_working / Recorded / coach). Never leave the poster guessing silence.
        """
        snippet = _lead_snippet(lead_body)
        quoted = f"`{snippet}`" if snippet else "your message"
        handle = identity_handle or _HERMES_HANDLE
        return await self.post_status(
            room,
            f"Got it — working on {quoted}.",
            EventType.START,
            {
                "status": "received",
                "ack": True,
                "role": handle,
                "source_message_id": source_message_id or "",
            },
            identity_handle=handle,
        )

    async def post_human_next(
        self,
        room: str,
        *,
        i_did: str,
        recommend: str,
        outside_adh: str,
        tokens: Sequence[TokenAction],
        recommend_why: str = "",
        evidence: str = "",
        human_role: str = "Lead",
        hop: str = "",
        example: str = "",
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
        identity_handle: str | None = None,
    ) -> MessageRead:
        """Post helpful-army coach (programmes wire through poster + role handle)."""
        body = format_human_next(
            i_did=i_did,
            recommend=recommend,
            outside_adh=outside_adh,
            tokens=list(tokens),
            recommend_why=recommend_why,
            evidence=evidence,
            human_role=human_role,
            hop=hop,
            example=example,
        )
        handle = identity_handle or _HERMES_HANDLE
        return await self.post_status(
            room,
            body,
            event_type,
            {
                **(payload or {}),
                "status": (payload or {}).get("status") or "human_next",
                "role": handle,
                "coach": True,
            },
            identity_handle=handle,
        )

    async def post_heartbeat(self, room: str, body: str, event_type: EventType) -> None:
        await self._buzz.ingest_heartbeat(
            HeartbeatIngest(
                identity_handle=_HERMES_HANDLE,
                room_slug=room,
                body=body,
                event_type=event_type,
                payload={"service": "hermes", "lane": "pm"},
            )
        )

    async def post_collab(
        self,
        room: str,
        *,
        body: str,
        identity_handle: str,
        status: str,
        payload: Optional[dict[str, Any]] = None,
        event_type: EventType = EventType.PROGRESS,
        mention: str = "",
    ) -> MessageRead:
        """Army @-talk (CollabPost) — visible baton/claim/done chatter."""
        text = (body or "").strip()
        if mention and f"@{mention}" not in text:
            text = f"@{mention} {text}".strip()
        return await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=identity_handle,
                body=text,
                kind=MessageKind.EVENT,
                event_type=event_type,
                payload={
                    **(payload or {}),
                    "status": status,
                    "collab": True,
                    "role": identity_handle,
                },
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
        """Buzz still-working posts every ``progress_seconds`` while Cursor runs."""
        steps = int(self._settings.wait_steps)
        interval = float(self._settings.progress_seconds)
        state = {"step": 0}

        async def _on_progress(_msg: str) -> None:
            state["step"] += 1
            step = int(state["step"])
            if step > steps:
                logger.warning(
                    "PM hop exceeded wait_steps; Cursor still running",
                    hop=hop,
                    initiative=initiative,
                    step=step,
                    steps=steps,
                )
            elapsed = int(step * interval)
            wait_vars = {
                "step": min(step, steps),
                "steps": steps,
                "elapsed": elapsed,
                "interval": f"{interval:.0f}",
            }
            body = self.copy("hermes.pm.status.still-working", wait_vars)
            if label:
                body = f"{label}: {body}"
            await self.post_status(
                room,
                body,
                EventType.PROGRESS,
                {
                    "status": "still_working",
                    "hop": hop,
                    "initiative": initiative,
                    "wait_step": step,
                    "wait_steps": steps,
                },
            )
            try:
                await self.post_heartbeat(
                    room,
                    self.copy("hermes.pm.heartbeat.still-working", wait_vars),
                    EventType.PROGRESS,
                )
            except Exception:
                logger.exception("PM progress heartbeat failed", hop=hop)

        return _on_progress


def _lead_snippet(text: str, *, limit: int = 72) -> str:
    """Single-line quote for ack posts (Buzz-light)."""
    one = " ".join((text or "").split())
    if len(one) <= limit:
        return one
    return one[: max(0, limit - 1)] + "…"
