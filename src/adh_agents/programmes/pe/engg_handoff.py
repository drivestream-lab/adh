"""PE → Dev engg-think handoff — open `#engg-<id>` + emit `dev.engg_think`."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.pm.validation_report import impact_map_path
from src.adh_agents.settings import PeAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.exceptions.app_exceptions import NotFoundError, ValidationError
from src.infra_services.pm_workspace_service import PmWorkspaceService, prd_path
from src.models.buzz_models import (
    EventType,
    MessageCreate,
    MessageKind,
    RoomMemberCreate,
    TaskCreate,
    TaskKind,
    TaskSource,
    TaskState,
)
from src.models.tenant_models import TenantContext

_BATON_TYPE = "dev.engg_think"


class PeEnggHandoff(BaseBusinessService):
    """Greenfield PE authority: only PE starts Dev (not PM draft-PR)."""

    role_id = "adh.pe"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        workspace: PmWorkspaceService,
    ) -> None:
        super().__init__()
        self._buzz = buzz
        self._batons = batons
        self._poster = poster
        self._workspace = workspace
        self._settings = PeAgentSettings.get_instance()
        self._lead = HermesSettings.get_instance().lead_handle

    async def handoff_to_dev(
        self,
        tenant: TenantContext,
        *,
        initiative: str,
        prd_pr_url: str,
        source_room: str | None = None,
    ) -> Baton | None:
        """Ensure engg floor + emit Dev baton. Idempotent on baton key."""
        init = (initiative or "").strip().upper()
        pr_url = (prd_pr_url or "").strip()
        if not init:
            await self._poster.post_status(
                source_room or tenant.ops_room,
                "engg go needs an initiative id.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return None
        if not pr_url:
            await self._poster.post_status(
                source_room or tenant.ops_room,
                (
                    f"**{init}** needs a product PR URL for engg-think "
                    "(merged OK). Example: `engg go {init} https://github.com/…/pull/N`"
                ),
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return None

        impact = impact_map_path(init)
        if not (self._workspace.read_local(tenant, impact) or "").strip():
            await self._poster.post_status(
                source_room or tenant.ops_room,
                f"**{init}** missing Impact-Map at `{impact}` — PE cannot hand off to Dev.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return None
        if not (self._workspace.read_local(tenant, prd_path(init)) or "").strip():
            await self._poster.post_status(
                source_room or tenant.ops_room,
                f"**{init}** missing PRD — PE cannot hand off to Dev.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return None

        await self._ensure_task(tenant, init)
        engg = await self._buzz.ensure_engg_room(task_id=init, title=f"Engg {init}")
        for handle in (self.role_id, "adh.dev", self._lead):
            if not (handle or "").strip():
                continue
            try:
                await self._buzz.ensure_member(
                    RoomMemberCreate(room_slug=engg.slug, identity_handle=handle)
                )
            except Exception:
                self.logger.exception("engg member ensure failed", room=engg.slug, handle=handle)

        ttl = int(self._settings.baton_ttl_seconds)
        baton = Baton(
            type=_BATON_TYPE,
            from_role=self.role_id,
            to_role="adh.dev",
            tenant=tenant.slug,
            ops_room=engg.slug,
            initiative=init,
            idempotency_key=f"{_BATON_TYPE}:{tenant.slug}:{init}:{pr_url}",
            payload={
                "prd_pr_url": pr_url,
                "pr_url": pr_url,
                "stage": "engg_think",
                "engg_room": engg.slug,
                "note": "PE product fence → Dev engg-think",
            },
            artefact_refs=[prd_path(init), impact],
        )
        stored, created = await self._batons.create_pending(baton, ttl=ttl)

        hub_body = f"PE → Dev engg-think **{init}** → `#{engg.slug}` " f"(product PR `{pr_url}`)"
        try:
            await self._buzz.post_message(
                tenant.ops_room,
                MessageCreate(
                    identity_handle=self.role_id,
                    body=hub_body,
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": "engg_handoff",
                        "initiative": init,
                        "engg_room": engg.slug,
                        "prd_pr_url": pr_url,
                    },
                ),
            )
        except Exception:
            self.logger.exception("engg hub announce failed", initiative=init)

        notice = (
            f"@adh.dev baton `{_BATON_TYPE}` "
            f"(init={init}; engg=`#{engg.slug}`; correlation={stored.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        try:
            await self._buzz.post_message(
                engg.slug,
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
                        "prd_pr_url": pr_url,
                    },
                ),
            )
        except Exception:
            self.logger.exception("engg baton notice failed", initiative=init)

        await self._poster.post_status(
            source_room or engg.slug,
            (
                f"Handed **{init}** to Dev on `#{engg.slug}` "
                f"({'new' if created else 'idempotent'} baton)."
            ),
            EventType.DONE,
            {
                "status": "engg_handoff_done",
                "initiative": init,
                "engg_room": engg.slug,
                "created": created,
            },
            identity_handle=self.role_id,
        )
        return stored

    async def _ensure_task(self, tenant: TenantContext, init: str) -> None:
        try:
            await self._buzz.get_task(tenant.slug, init)
            return
        except NotFoundError:
            pass
        try:
            await self._buzz.create_task(
                TaskCreate(
                    tenant_slug=tenant.slug,
                    kind=TaskKind.INIT,
                    task_id=init,
                    title=f"{init} engg-think",
                    state=TaskState.BOUND,
                    source=TaskSource.BUZZ,
                    source_ref=f"engg-handoff:{tenant.slug}:{init}",
                    hub_room_slug=tenant.ops_room,
                )
            )
        except ValidationError:
            # Race / duplicate source_ref — task may already exist.
            try:
                await self._buzz.get_task(tenant.slug, init)
            except Exception:
                self.logger.exception("engg ensure task failed", initiative=init)
