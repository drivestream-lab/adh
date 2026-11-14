"""Coder wave programme — lease-gated claim + YAML wave-* hops (forge first)."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.coder.forge_ops import (
    move_wave_board_status,
    pick_wave_issue_url,
)
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
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_workspace_service import PmWorkspaceService
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
    """Claim ``coder.wave`` after repo lease; walk YAML wave-* from board move."""

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
        forge: ForgeActionService,
        workspace: PmWorkspaceService,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._tenants = tenants
        self._leases = leases
        self._forge = forge
        self._workspace = workspace
        self._settings = CoderAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._continue_wave(tenant, room, session)

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        session = await self._store.load(tenant.slug, self.role_id, work_id)
        if session is None:
            await self._poster.post_status(
                room,
                f"Coder resume: no session for `{work_id}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        await self._continue_wave(tenant, room, session)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        del tenant
        return []

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        del tenant, room, session, token
        # C3: wave-acceptance / wave-signoff GateOpener tokens.

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
        raw_urls = payload.get("board_issue_urls")
        board_urls: list[str] = [str(x) for x in raw_urls] if isinstance(raw_urls, list) else []
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
                "wave_ids": ",".join(wave_ids),
                "active_wave": wave_ids[0] if wave_ids else "",
                "coder_handle": baton.to_role,
                "board_seed_marker": str(payload.get("board_seed_marker") or ""),
                "board_issue_urls": " ".join(board_urls),
                "coder_spine": "c2_leased",
                "lease_key": lease.key,
                "baton_idempotency_key": baton.idempotency_key or "",
            },
        )
        await self._store.save(session)

        waves_label = ",".join(wave_ids) or "n/a"
        await self._poster.post_status(
            collab,
            (
                f"Coder leased `{repo}` for **{init}** "
                f"(waves={waves_label}; handle=`{baton.to_role}`; "
                f"YAML entry=`{_WAVE_ENTRY}`)."
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

        await self._continue_wave(tenant, collab, session)

        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=BatonStatus.DONE,
            summary=f"c2_leased:{repo}:{session.stage}",
            correlation_id=baton.correlation_id,
            artefact_refs=list(baton.artefact_refs or []),
        )

    async def _continue_wave(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        """Walk known automated hops; stall at skills/gates until wired."""
        stage = (session.stage or "").strip()
        if stage not in _WAVE_CHAIN:
            await self._poster.post_status(
                room,
                f"Coder stalled — unknown YAML stage `{stage}` (not in wave chain).",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return

        if stage == "wave-in-progress-action":
            ok = await self._run_wave_in_progress(tenant, room, session)
            if not ok:
                return
            session.stage = "pre-implement"
            await self._store.save(session)

        stage = (session.stage or "").strip()
        if stage == "pre-implement":
            init = session.slots.get("initiative") or session.work_id
            repo = session.slots.get("repo") or "?"
            await self._poster.post_status(
                room,
                (
                    f"Coder ready for YAML `{stage}` on **{init}** repo=`{repo}` — "
                    "skill dispatch (`pre-implement` → `loop-spec` → `wave-pr-action`) "
                    "lands next; board is In Progress."
                ),
                EventType.PROGRESS,
                {
                    "status": "coder_awaiting_skill",
                    "stage": stage,
                    "initiative": init,
                    "repo": repo,
                },
                identity_handle=self.role_id,
            )

    async def _run_wave_in_progress(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> bool:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        urls = (session.slots.get("board_issue_urls") or "").split()
        wave_ids = [w for w in (session.slots.get("wave_ids") or "").split(",") if w]
        try:
            wave_index = wave_ids.index(wave) if wave and wave in wave_ids else 0
            issue_url = pick_wave_issue_url(urls, wave_id=wave or "W?", wave_index=wave_index)
            result = await move_wave_board_status(
                forge=self._forge,
                workspace=self._workspace,
                tenant=tenant,
                issue_url=issue_url,
                status="in_progress",
                repo_hint=repo,
            )
        except Exception as exc:
            await self._poster.post_status(
                room,
                (
                    f"Coder forge `update_board_status` failed for **{init}** "
                    f"repo=`{repo}` wave=`{wave or '?'}`: {exc}. "
                    "Fix board/App perms; resume when ready."
                ),
                EventType.STALL,
                {
                    "status": "coder_board_status_failed",
                    "initiative": init,
                    "repo": repo,
                    "wave": wave,
                    "error": str(exc),
                },
                identity_handle=self.role_id,
            )
            return False

        await self._poster.post_status(
            room,
            (
                f"Coder moved wave `{wave or '?'}` → **In Progress** on the board "
                f"({result.detail or result.url or 'ok'})."
            ),
            EventType.PROGRESS,
            {
                "status": "coder_board_in_progress",
                "initiative": init,
                "repo": repo,
                "wave": wave,
                "detail": result.detail or "",
            },
            identity_handle=self.role_id,
        )
        session.slots["wave_in_progress"] = "true"
        return True
