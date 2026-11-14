"""Dev → Coder handoff — emit ``coder.wave`` batons to ``adh.coder.<repo>`` after board seed."""

from __future__ import annotations

from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.coder.ready_set import ready_repos, ready_wave_ids_for_repo
from src.adh_agents.programmes.coder.roles import coder_role_for_repo, short_repo
from src.adh_agents.programmes.dev.paths import implementation_plan_path
from src.adh_agents.programmes.dev.workmanifest_board import parse_board_manifest
from src.adh_agents.settings import CoderAgentSettings, DevAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.models.buzz_models import (
    EventType,
    IdentityCreate,
    IdentityKind,
    IdentityRole,
    MessageCreate,
    MessageKind,
    RoomMemberCreate,
)
from src.models.tenant_models import TenantContext

_BATON_TYPE = "coder.wave"


class DevCoderHandoff(BaseBusinessService):
    """After board-seeded: one baton per ready repo → ``adh.coder.<repo>`` (C.3 / C.13)."""

    role_id = "adh.dev"

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
        self._dev_settings = DevAgentSettings.get_instance()
        self._coder_settings = CoderAgentSettings.get_instance()
        self._lead = HermesSettings.get_instance().lead_handle

    async def handoff_to_coder(
        self,
        tenant: TenantContext,
        *,
        initiative: str,
        engg_room: str,
        plan_path: Path | str | None = None,
        board_seed_marker: str = "",
        board_issue_urls: list[str] | None = None,
        source_room: str | None = None,
    ) -> list[Baton]:
        """Emit ready-repo ``coder.wave`` batons. Idempotent per seed marker + repo."""
        init = (initiative or "").strip().upper()
        engg = (engg_room or "").strip()
        if not init or not engg:
            await self._poster.post_status(
                source_room or tenant.ops_room,
                "Coder handoff needs initiative + engg room.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return []

        try:
            manifest_text = self._load_plan_text(tenant, plan_path=plan_path, initiative=init)
            manifest = parse_board_manifest(manifest_text)
        except Exception as exc:
            await self._poster.post_status(
                source_room or engg,
                (
                    f"**{init}** board seeded but Coder handoff failed to parse WorkManifest: "
                    f"{exc}. Fix plan §9 then `reseed board`."
                ),
                EventType.STALL,
                {"status": "coder_handoff_wm_failed", "initiative": init},
                identity_handle=self.role_id,
            )
            return []

        repos = ready_repos(manifest)
        if not repos:
            await self._poster.post_status(
                source_room or engg,
                (
                    f"**{init}** has no ready waves (empty ``depends_on`` set) — "
                    "Coder batons not emitted."
                ),
                EventType.STALL,
                {"status": "coder_handoff_no_ready", "initiative": init},
                identity_handle=self.role_id,
            )
            return []

        marker = (board_seed_marker or "").strip() or "seed"
        ttl = int(self._dev_settings.baton_ttl_seconds)
        issued: list[Baton] = []
        handles: list[str] = ["adh.coder", self.role_id]
        if self._lead:
            handles.append(self._lead)

        for repo in repos:
            handle = coder_role_for_repo(repo)
            handles.append(handle)
            await self._ensure_coder_identity(handle, repo)
            wave_ids = ready_wave_ids_for_repo(manifest, repo)
            baton = Baton(
                type=_BATON_TYPE,
                from_role=self.role_id,
                to_role=handle,
                tenant=tenant.slug,
                ops_room=engg,
                initiative=init,
                idempotency_key=f"{_BATON_TYPE}:{tenant.slug}:{init}:{short_repo(repo)}:{marker}",
                payload={
                    "repo": short_repo(repo),
                    "wave_ids": list(wave_ids),
                    "engg_room": engg,
                    "board_seed_marker": marker,
                    "board_issue_urls": list(board_issue_urls or []),
                    "stage": "wave_ready",
                    "note": "Dev board-seeded → Coder ready-set",
                    "max_parallel_coders": int(self._coder_settings.max_parallel_coders),
                },
                artefact_refs=[str(plan_path or implementation_plan_path(init))],
            )
            stored, created = await self._batons.create_pending(baton, ttl=ttl)
            issued.append(stored)
            notice = (
                f"@{handle} baton `{_BATON_TYPE}` "
                f"(init={init}; repo=`{short_repo(repo)}`; waves={','.join(wave_ids)}; "
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
                            "repo": short_repo(repo),
                            "to_role": handle,
                        },
                    ),
                )
            except Exception:
                self.logger.exception(
                    "coder baton notice failed", initiative=init, repo=repo, handle=handle
                )

        for handle in dict.fromkeys(h for h in handles if (h or "").strip()):
            try:
                await self._buzz.ensure_member(
                    RoomMemberCreate(room_slug=engg, identity_handle=handle)
                )
            except Exception:
                self.logger.exception("coder engg member ensure failed", room=engg, handle=handle)

        hub_body = (
            f"Dev → Coder **{init}** → `#{engg}` "
            f"({len(issued)} ready-repo baton(s): "
            f"{', '.join(short_repo(r) for r in repos)})"
        )
        try:
            await self._buzz.post_message(
                tenant.ops_room,
                MessageCreate(
                    identity_handle=self.role_id,
                    body=hub_body,
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": "coder_handoff",
                        "initiative": init,
                        "engg_room": engg,
                        "repos": [short_repo(r) for r in repos],
                        "baton_count": len(issued),
                    },
                ),
            )
        except Exception:
            self.logger.exception("coder hub announce failed", initiative=init)

        await self._poster.post_status(
            source_room or engg,
            (
                f"Handed **{init}** to Coder on `#{engg}` — "
                f"{len(issued)} `coder.wave` baton(s) for ready repos "
                f"(`{'`, `'.join(short_repo(r) for r in repos)}`)."
            ),
            EventType.DONE,
            {
                "status": "coder_handoff_done",
                "initiative": init,
                "engg_room": engg,
                "repos": [short_repo(r) for r in repos],
                "baton_count": len(issued),
            },
            identity_handle=self.role_id,
        )
        return issued

    def _load_plan_text(
        self,
        tenant: TenantContext,
        *,
        plan_path: Path | str | None,
        initiative: str,
    ) -> str:
        candidate = plan_path if plan_path is not None else implementation_plan_path(initiative)
        path = Path(candidate)
        if path.is_file():
            return path.read_text(encoding="utf-8")
        rel = str(candidate).strip()
        text = (self._workspace.read_local(tenant, rel) or "").strip()
        if text:
            return text
        raise ValidationError(f"implementation plan missing at {rel}")

    async def _ensure_coder_identity(self, handle: str, repo: str) -> None:
        try:
            await self._buzz.create_identity(
                IdentityCreate(
                    handle=handle,
                    display_name=f"Coder ({short_repo(repo)})",
                    kind=IdentityKind.AGENT,
                    role=IdentityRole.CODER,
                )
            )
        except ValidationError:
            return
        except Exception:
            self.logger.exception("coder identity ensure failed", handle=handle)
