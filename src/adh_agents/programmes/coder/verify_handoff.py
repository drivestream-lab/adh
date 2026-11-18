"""Coder → Verify handoff — emit ``verify.wave`` after wave-pr-action."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.verify.roles import verify_role
from src.adh_agents.settings import CoderAgentSettings, VerifyAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.models.buzz_models import EventType, MessageCreate, MessageKind, RoomMemberCreate
from src.models.tenant_models import TenantContext

_BATON_TYPE = "verify.wave"


class CoderVerifyHandoff(BaseBusinessService):
    """After wave Draft PR: baton Verify to prove tip (V.12 / 1A)."""

    role_id = "adh.coder"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
    ) -> None:
        super().__init__()
        self._buzz = buzz
        self._batons = batons
        self._poster = poster
        self._coder = CoderAgentSettings.get_instance()
        self._verify = VerifyAgentSettings.get_instance()

    async def emit_verify_wave(
        self,
        tenant: TenantContext,
        *,
        initiative: str,
        engg_room: str,
        repo: str,
        wave_id: str,
        pr_url: str = "",
        pr_number: str = "",
        verify_command: str = "make verify",
        compose_dir: str = "",
        coverage_packet: str = "",
        coder_handle: str = "adh.coder",
        tip_sha: str = "",
        round_n: int = 1,
    ) -> Baton:
        init = (initiative or "").strip().upper()
        engg = (engg_room or "").strip() or tenant.ops_room
        repo_s = (repo or "").strip()
        wave = (wave_id or "").strip()
        overlay = (compose_dir or "").strip() or self._verify.default_overlay_name
        ttl = int(self._coder.baton_ttl_seconds)
        handle = verify_role()
        baton = Baton(
            type=_BATON_TYPE,
            from_role=coder_handle or self.role_id,
            to_role=handle,
            tenant=tenant.slug,
            ops_room=engg,
            initiative=init,
            idempotency_key=(f"{_BATON_TYPE}:{tenant.slug}:{init}:{repo_s}:{wave}:r{int(round_n)}"),
            payload={
                "repo": repo_s,
                "wave_id": wave,
                "pr_url": pr_url or "",
                "pr_number": pr_number or "",
                "verify_command": verify_command or "make verify",
                "compose_dir": overlay,
                "lab_name": self._verify.lab_root_name,
                "coverage_packet": coverage_packet or "",
                "coder_handle": coder_handle or self.role_id,
                "tip_sha": tip_sha or "",
                "collab_round": int(round_n),
                "stage": "verify_ready",
            },
        )
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        try:
            await self._buzz.ensure_member(RoomMemberCreate(room_slug=engg, identity_handle=handle))
        except Exception:
            self.logger.exception("verify engg member ensure failed", room=engg)
        notice = (
            f"@{handle} baton `{_BATON_TYPE}` "
            f"(init={init}; repo=`{repo_s}`; wave=`{wave}`; round={round_n}; "
            f"correlation={stored.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        try:
            await self._buzz.post_message(
                engg,
                MessageCreate(
                    identity_handle=self.role_id,
                    body=notice,
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": "baton_emitted",
                        "collab": True,
                        "baton_type": _BATON_TYPE,
                        "baton_id": stored.id,
                        "created": created,
                        "correlation_id": stored.correlation_id,
                        "idempotency_key": stored.idempotency_key,
                        "initiative": init,
                        "tenant": tenant.slug,
                        "repo": repo_s,
                        "to_role": handle,
                    },
                ),
            )
        except Exception:
            self.logger.exception("verify baton notice failed", initiative=init)
        await self._poster.post_status(
            engg,
            (
                f"Coder → Verify **{init}** `{wave}` on `{repo_s}` "
                f"(overlay=`{overlay}`; round={round_n})."
            ),
            EventType.PROGRESS,
            {
                "status": "coder_verify_handoff",
                "initiative": init,
                "wave_id": wave,
                "repo": repo_s,
                "round": round_n,
            },
            identity_handle=self.role_id,
        )
        return stored
