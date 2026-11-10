"""Read walk programme — one-repo filesystem sketch (codegraph stub later)."""

from __future__ import annotations

from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.ports.filesystem import structured_repo_sketch
from src.adh_agents.ports.repo_resolve import RepoResolveError, resolve_repo_root
from src.adh_agents.runtime.work_models import PROGRAMME_READ, AgentWorkSession
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import ReadAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class ReadWalkProgramme(BaseBusinessService):
    programme_id = PROGRAMME_READ
    role_id = "adh.read"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        tenants: TenantRegistryService,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._tenants = tenants
        self._settings = ReadAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._poster.post_status(
            room,
            f"Read programme bound for {session.work_id}.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        return None

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        await self._poster.post_status(
            room,
            f"Resume read walk `{work_id}` (no-op if finished).",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        return []

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        ttl = int(self._settings.baton_ttl_seconds)
        claimed = await self._batons.claim(baton, claimant=self.role_id, ttl=ttl)
        if not claimed:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="claim failed",
                correlation_id=baton.correlation_id,
                error="claim_failed",
            )
        await self._batons.mark_running(baton, ttl=ttl)
        tenant = self._tenants.by_slug(baton.tenant)
        if tenant is None:
            await self._batons.mark_done(baton, ttl=ttl, error="unknown_tenant")
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="unknown tenant",
                correlation_id=baton.correlation_id,
                error="unknown_tenant",
            )
        payload = baton.payload or {}
        repo_ref = str(payload.get("repo_ref") or payload.get("repo") or tenant.meta_repo)
        ops = room or baton.ops_room
        try:
            root = resolve_repo_root(
                tenant, repo_ref, workspace_root=self._tenants.workspace_root()
            )
        except RepoResolveError as exc:
            await self._poster.post_status(
                ops,
                (
                    f"Read walk failed for `{repo_ref}`: {exc}. "
                    "Next: PE/Lead fix baton repo_ref or tenant checkout."
                ),
                EventType.STALL,
                identity_handle=self.role_id,
            )
            failed = await self._batons.mark_done(baton, ttl=ttl, error="repo_resolve_failed")
            return Rollup(
                baton_id=failed.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary=str(exc),
                correlation_id=failed.correlation_id,
                error="repo_resolve_failed",
            )

        sketch = structured_repo_sketch(root, repo_ref=repo_ref, limit=80)
        init = (baton.initiative or "INIT").strip().upper()
        safe = repo_ref.replace("/", "-")
        rel = f"prd/reports/{init}-read-walk-{safe}.md"
        artefact = Path(tenant.meta_root).expanduser() / rel
        artefact.parent.mkdir(parents=True, exist_ok=True)
        artefact.write_text(sketch.to_markdown(), encoding="utf-8")

        summary = (
            f"read.walk `{repo_ref}`: {sketch.path_count} paths, "
            f"{len(sketch.entrypoints)} entrypoints"
        )
        await self._poster.post_status(
            ops,
            (
                f"Read walk done for **{repo_ref}** ({init}).\n"
                f"Artefact: `{rel}`\n"
                f"**Next:** waiting on PE (product brief continues — no Lead action)."
            ),
            EventType.DONE,
            {
                "status": "read_rollup",
                "repo_ref": repo_ref,
                "artefact": rel,
                "baton_id": baton.id,
                "path_count": sketch.path_count,
            },
            identity_handle=self.role_id,
        )
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=done.status,
            summary=summary,
            correlation_id=done.correlation_id,
            artefact_refs=[rel],
            tools_used=["filesystem.structured_sketch"],
        )
