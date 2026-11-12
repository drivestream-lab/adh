"""Lead ``traj`` — Buzz card of recent ``buzz_task_events`` (kind|purpose|token|who)."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.adh_agents.collaboration.human_replies import TRAJ, normalize_reply
from src.adh_agents.runtime.agentic_extract import find_init_token
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext

logger = get_logger()

_DEFAULT_LIMIT = 20


class TrajCoachProgramme:
    """Render trajectory on Buzz for the current INIT."""

    role_id = "adh.pm"

    @inject
    def __init__(self, buzz: BuzzService, poster: HermesBuzzPoster) -> None:
        self._buzz = buzz
        self._poster = poster

    async def handle_lead(
        self,
        tenant: TenantContext,
        room: str,
        *,
        body: str,
        task_id: str | None = None,
    ) -> bool:
        token = normalize_reply(body, [TRAJ])
        if token != TRAJ and (body or "").strip().lower() not in {
            TRAJ,
            "trajectory",
            "show trajectory",
        }:
            return False
        init = await self._resolve_init(tenant, room, task_id=task_id, body=body)
        if not init:
            await self._poster.post_status(
                room,
                "Say `traj INIT-…` (or `traj` from a task/engg room).",
                EventType.STALL,
            )
            return True
        await self._poster.ack_received(room, lead_body=TRAJ, identity_handle=self.role_id)
        # Detailed card always on ops (portfolio radar) — not task/engg scroll.
        await self.post_card(tenant, tenant.ops_room, initiative=init)
        if (room or "").strip() != tenant.ops_room:
            await self._poster.post_status(
                room,
                f"Trajectory card for `{init}` posted on `#{tenant.ops_room}`.",
                EventType.PROGRESS,
                {"status": "traj_card_pointer", "initiative": init, "ops": tenant.ops_room},
            )
        return True

    async def post_card(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        limit: int = _DEFAULT_LIMIT,
    ) -> None:
        """Post detailed traj table. Callers should pass ``tenant.ops_room`` (L12)."""
        init = (initiative or "").strip().upper()
        target = (room or "").strip() or tenant.ops_room
        try:
            events = await self._buzz.list_task_events(tenant.slug, init)
        except Exception:
            logger.exception("traj list_task_events failed", initiative=init)
            await self._poster.post_status(
                target,
                f"Could not load trajectory for `{init}`.",
                EventType.STALL,
            )
            return
        rows = events[-max(1, limit) :]
        if not rows:
            body = f"**Trajectory** `{init}`\n_(no events yet)_"
        else:
            lines = [
                f"**Trajectory** `{init}` (latest {len(rows)})",
                "",
                "| kind | purpose | token | who |",
                "|---|---|---|---|",
            ]
            for event in rows:
                kind = getattr(event.kind, "value", None) or str(event.kind or "")
                purpose = (event.purpose or "—").replace("|", "/")
                tok = (event.token or "—").replace("|", "/")
                who = (event.role_id or "—").replace("|", "/")
                reason = ""
                payload = event.payload or {}
                if isinstance(payload, dict) and payload.get("reason"):
                    reason = f" — {str(payload.get('reason'))[:80]}"
                lines.append(f"| `{kind}` | `{purpose}` | `{tok}`{reason} | `{who}` |")
            body = "\n".join(lines)
        await self._poster.post_status(
            target,
            body,
            EventType.PROGRESS,
            {"status": "traj_card", "initiative": init, "count": len(rows), "ops": True},
        )

    async def _resolve_init(
        self,
        tenant: TenantContext,
        room: str,
        *,
        task_id: Optional[str],
        body: str,
    ) -> str:
        if task_id:
            return task_id.strip().upper()
        if room.startswith("task-"):
            return room[len("task-") :].upper()
        if room.startswith("engg-"):
            return room[len("engg-") :].upper()
        token = find_init_token(body or "")
        if token:
            return token
        try:
            active = await self._buzz.list_tasks(tenant.slug, include_archived=False)
        except Exception:
            return ""
        if len(active) == 1:
            return active[0].task_id
        return ""
