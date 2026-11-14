"""Coder wave programme — lease-gated claim; YAML wave-* walker continues in C2."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.coder.repo_lease import CoderRepoLeaseStore
from src.adh_agents.programmes.coder.roles import is_coder_role
from src.adh_agents.runtime.work_models import (
    PROGRAMME_CODER,
    AWAITING_NONE,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import CoderAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext

_BATON_TYPE = "coder.wave"
_WAVE_ENTRY = "wave-in-progress-action"
_WAVE_CHAIN = (
    "wave-in-progress-action",
    "pre-implement",
    "loop-spec",
    "wave-pr-action",
    "wave-acceptance",
    "wave-awaiting-closeout",
    "learning-extract",
    "ground-spec",
    "wave-done-action",
    "wave-signoff",
)


class CoderWaveProgramme(BaseBusinessService):
    """Claim ``coder.wave`` after repo lease; walk YAML wave-* (forge hops next)."""

    programme_id = PROGRAMME_CODER
    role_id = "adh.coder"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        tenants: TenantRegistryService,
        leases: CoderRepoLeaseStore,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._tenants = tenants
        self._leases = leases
        self._settings = CoderAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        del tenant, room, session
        # C2 walker: resume from session.stage along _WAVE_CHAIN.

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        del tenant, room, work_id

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        del tenant
        return []

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        del tenant, room, session, token

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        ttl = int(self._settings.baton_ttl_seconds)
        if (baton.type or "").strip() != _BATON_TYPE:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="unexpected baton type",
                correlation_id=baton.correlation_id,
                error="wrong_type",
            )
        if not is_coder_role(baton.to_role):
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="baton not addressed to coder",
                correlation_id=baton.correlation_id,
                error="wrong_role",
            )

        tenant = self._tenants.by_slug(baton.tenant)
        if tenant is None:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="unknown tenant",
                correlation_id=baton.correlation_id,
                error="unknown_tenant",
            )

        init = (baton.initiative or "").strip().upper()
        payload = baton.payload or {}
        repo = str(payload.get("repo") or "").strip()
        raw_waves = payload.get("wave_ids")
        wave_ids: list[str] = [str(x) for x in raw_waves] if isinstance(raw_waves, list) else []
        collab = (baton.ops_room or "").strip() or room or tenant.ops_room

        if not repo:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="coder baton missing repo",
                correlation_id=baton.correlation_id,
                error="missing_repo",
            )

        # Lease before claim so a held repo leaves the baton PENDING for retry.
        lease = await self._leases.try_acquire(
            tenant=tenant.slug,
            repo=repo,
            holder=self.role_id,
            ttl_seconds=ttl,
        )
        if not lease.acquired:
            await self._poster.post_status(
                collab,
                (
                    f"Coder deferred `{repo}` for **{init}** — repo lease held "
                    f"by `{lease.holder or 'another'}` "
                    f"(cap={self._settings.max_parallel_coders})."
                ),
                EventType.PROGRESS,
                {
                    "status": "coder_lease_deferred",
                    "initiative": init,
                    "repo": repo,
                    "holder": lease.holder,
                },
                identity_handle=self.role_id,
            )
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.PENDING,
                summary=f"lease_deferred:{repo}",
                correlation_id=baton.correlation_id,
                error="lease_held",
            )

        claimed = await self._batons.claim(baton, claimant=self.role_id, ttl=ttl)
        if not claimed:
            await self._leases.release(tenant=tenant.slug, repo=repo, holder=self.role_id)
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="claim failed",
                correlation_id=baton.correlation_id,
                error="claim_failed",
            )
        await self._batons.mark_running(baton, ttl=ttl)

        session = AgentWorkSession(
            role_id=self.role_id,
            tenant_slug=tenant.slug,
            room=collab,
            work_id=f"{init}:{repo}",
            programme=PROGRAMME_CODER,
            stage=_WAVE_ENTRY,
            awaiting=AWAITING_NONE,
            slots={
                "initiative": init,
                "repo": repo,
                "wave_ids": ",".join(str(x) for x in wave_ids),
                "coder_handle": baton.to_role,
                "board_seed_marker": str(payload.get("board_seed_marker") or ""),
                "coder_spine": "c2_leased",
                "lease_key": lease.key,
                "baton_idempotency_key": baton.idempotency_key or "",
            },
        )
        await self._store.save(session)

        waves_label = ",".join(str(x) for x in wave_ids) or "n/a"
        await self._poster.post_status(
            collab,
            (
                f"Coder leased `{repo}` for **{init}** "
                f"(waves={waves_label}; handle=`{baton.to_role}`; "
                f"YAML entry=`{_WAVE_ENTRY}`). Next: forge `update_board_status` "
                f"→ In Progress (walker continues through `{_WAVE_CHAIN[-1]}`)."
            ),
            EventType.PROGRESS,
            {
                "status": "coder_leased",
                "initiative": init,
                "repo": repo,
                "wave_ids": list(wave_ids),
                "to_role": baton.to_role,
                "baton_id": baton.id,
                "stage": _WAVE_ENTRY,
            },
            identity_handle=self.role_id,
        )

        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=BatonStatus.DONE,
            summary=f"c2_leased:{repo}:{_WAVE_ENTRY}",
            correlation_id=baton.correlation_id,
            artefact_refs=list(baton.artefact_refs or []),
        )
