"""CoderAgent — claim ``coder.wave`` batons for ``adh.coder.<repo>`` (one worker)."""

from __future__ import annotations

import asyncio

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.coder.programme import CoderWaveProgramme
from src.adh_agents.programmes.coder.repo_lease import CoderRepoLeaseStore
from src.adh_agents.programmes.coder.roles import coder_role_prefix, is_coder_role
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.runtime.room_resolve import listen_rooms_for_role, resolve_tenant_for_room
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import CoderAgentSettings
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageKind, MessageRead

_BATON_TYPE = "coder.wave"


class CoderAgent(BaseHermesAgent):
    role_id = "adh.coder"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        tenants: TenantRegistryService,
        orchestrator: Orchestrator,
        programme: CoderWaveProgramme,
        leases: CoderRepoLeaseStore,
        work_store: AgentWorkStore,
        presence: PresenceService,
        autonomy: AutonomyPolicy,
    ) -> None:
        settings = CoderAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings, presence=presence)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._programme = programme
        self._leases = leases
        self._work_store = work_store
        self._autonomy = autonomy
        self._coder_settings = settings
        self._lead = HermesSettings.get_instance().lead_handle
        self._bg: set[asyncio.Task[None]] = set()

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._programme)
        for tenant in self._tenants.active():
            await self.ensure_hub_member(tenant.ops_room)
        rooms = await listen_rooms_for_role(self._buzz, self._tenants, self.role_id)
        await self.start_ops_listeners(rooms)
        await self._catch_up_pending_batons()
        self.start_listen_refresh_loop(
            lambda: listen_rooms_for_role(self._buzz, self._tenants, self.role_id),
            interval_seconds=15.0,
            on_added=self._on_rooms_added,
        )
        catch = asyncio.create_task(self._pending_baton_loop())
        self._bg.add(catch)
        catch.add_done_callback(self._bg.discard)
        self.logger.info(
            "CoderAgent listening",
            rooms=rooms,
            max_parallel_coders=self._coder_settings.max_parallel_coders,
        )

    async def _on_rooms_added(self, added: list[str]) -> None:
        del added
        await self._catch_up_pending_batons()

    async def _pending_baton_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(12.0)
                await self._catch_up_pending_batons()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Coder pending baton loop failed")

    async def _catch_up_pending_batons(self) -> None:
        ttl = int(self._agent_settings.baton_ttl_seconds)
        for tenant in self._tenants.active():
            await self._batons.reclaim_stale(tenant=tenant.slug, max_age_seconds=ttl)
            pending = await self._batons.list_pending_for(
                tenant=tenant.slug,
                to_role_prefix=coder_role_prefix(),
                baton_type=_BATON_TYPE,
            )
            # Clip by held leases + max_parallel_coders (C.17); per-repo NX in programme.
            repos: list[str] = []
            by_repo: dict[str, Baton] = {}
            for baton in pending:
                repo = str((baton.payload or {}).get("repo") or "").strip()
                if not repo or repo in by_repo:
                    continue
                by_repo[repo] = baton
                repos.append(repo)
            allowed = await self._leases.clip_ready(
                repos,
                tenant=tenant.slug,
                max_parallel=int(self._coder_settings.max_parallel_coders),
            )
            for repo in allowed:
                claimed = by_repo[repo]
                await self._programme.handle_baton(
                    claimed, room=claimed.ops_room or tenant.ops_room
                )

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
        if tenant is None:
            return
        payload = message.payload or {}
        status = str(payload.get("status") or "")
        if status == "baton_emitted" and payload.get("baton_type") == _BATON_TYPE:
            key = payload.get("idempotency_key")
            if key:
                baton = await self._batons.get(
                    tenant=str(payload.get("tenant") or tenant.slug),
                    idempotency_key=str(key),
                )
                if baton is not None and is_coder_role(baton.to_role):
                    await self._programme.handle_baton(baton, room=room)
                    return
        if status == "coder_handoff":
            await self._catch_up_pending_batons()
            return

        if message.kind != MessageKind.MESSAGE or (message.identity_handle or "") != self._lead:
            return
        # C2+: Lead tokens for wave-acceptance / signoff via Orchestrator.
        del message
