"""Hermes: PM lane + after-PR verify/grade/RCA. Does not merge."""

import asyncio
import hashlib
import json
import re
from typing import Any, Optional
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.configs.rubrics import RUBRIC_ENG, RUBRIC_PM, weighted_overall
from src.infra_services.hermes_store_service import HermesStoreService
from src.infra_services.pm_workspace_service import (
    PmWorkspaceService,
    next_free_think_runs,
    next_programme_init,
    skeleton_material_fails,
    think_path,
)
from src.infra_services.prompt_service import PromptService
from src.infra_services.redis_service import RedisService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.tenant_models import (
    GLOBAL_MEMORY_ROOM,
    GLOBAL_REPO,
    MEMORY_SCOPE_GLOBAL,
    MEMORY_SCOPE_REPO,
    TenantContext,
    knowledge_scope_key,
    memory_room_for_repo,
)
from src.models.buzz_models import (
    EventType,
    HeartbeatIngest,
    MessageCreate,
    MessageKind,
    MessageRead,
)
from src.models.hermes_models import HermesArtifactRead, HermesBriefRequest, HermesGradeRequest


class HermesService(BaseBusinessService):
    """Autonomous LLM brain. Writes Buzz + meta-repo files as adh-dev-pm. Never merges."""

    @inject
    def __init__(
        self,
        store: HermesStoreService,
        buzz: BuzzService,
        redis: RedisService,
        prompts: PromptService,
        workspace: PmWorkspaceService,
        tenants: TenantRegistryService,
    ) -> None:
        super().__init__()
        self._store = store
        self._buzz = buzz
        self._redis = redis
        self._prompts = prompts
        self._workspace = workspace
        self._tenants = tenants
        self._settings = HermesSettings.get_instance()
        self._boot_task: Optional[asyncio.Task[None]] = None
        self._listen_tasks: list[asyncio.Task[None]] = []
        self._work_tasks: set[asyncio.Task[None]] = set()
        self._inflight: dict[str, str] = {}
        self._awaiting_init: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> None:
        await super().initialize()
        if self._settings.listen_ops:
            rooms = [tenant.ops_room for tenant in self._tenants.active()]
            for room in rooms:
                task = asyncio.create_task(self._listen_ops(room))
                self._listen_tasks.append(task)
            self.logger.info("Hermes PM listener scheduled", rooms=rooms)
        if self._settings.run_boot_jobs:
            self._boot_task = asyncio.create_task(self._boot_jobs())
            self.logger.info("Hermes boot jobs scheduled")

    async def close(self) -> None:
        tasks = [*self._listen_tasks, self._boot_task, *self._work_tasks]
        for task in tasks:
            if task is not None:
                task.cancel()
        for task in tasks:
            if task is None:
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._listen_tasks = []
        self._boot_task = None
        self._work_tasks.clear()
        await super().close()

    async def _boot_jobs(self) -> None:
        try:
            await self.run_pm_brief(HermesBriefRequest(), skip_existing=True)
            await self.run_eng_grade(HermesGradeRequest(), skip_existing=True)
        except Exception:
            self.logger.exception("Hermes boot jobs failed")

    async def run_pm_brief(
        self, request: HermesBriefRequest, *, skip_existing: bool = False
    ) -> HermesArtifactRead:
        initiative = request.initiative
        if skip_existing and await self._store.has_kind("pm_brief", initiative):
            entries = await self._store.list_ledger()
            for entry in entries:
                if entry.kind == "pm_brief" and entry.initiative == initiative:
                    self.logger.info("Hermes PM brief already in ledger", initiative=initiative)
                    return entry
        await self._heartbeat(
            "adh.pm", self._copy("hermes.pm.heartbeat.brief-start"), EventType.START
        )
        if request.outline.strip():
            result = await self._prompts.complete(
                "hermes.pm.outline",
                {
                    "source_message_id": str(request.source_message_id or "none"),
                    "rubric_dimensions": ", ".join(RUBRIC_PM["dimensions"]),
                    "outline": request.outline.strip(),
                },
            )
        else:
            result = await self._prompts.complete(
                "hermes.pm.brief",
                {
                    "initiative": initiative,
                    "rubric_dimensions": ", ".join(RUBRIC_PM["dimensions"]),
                },
            )
        parsed, raw, model = result.parsed, result.raw, result.model
        proposed = str(parsed.get("proposed_init") or "").strip()
        if proposed.startswith("INIT-"):
            initiative = proposed
        scores = _as_float_map(parsed.get("scores"))
        overall = weighted_overall(scores, RUBRIC_PM)
        body = self._render_brief(initiative, parsed, overall, model)
        payload = {
            "lane": "pm",
            "initiative": initiative,
            "rubric": RUBRIC_PM["id"],
            "overall": overall,
            "threshold_x": RUBRIC_PM["threshold_x"],
            "scores": scores,
            "model": model,
            "stub": result.stub,
            "artifact": parsed,
            "raw": raw[:4000],
        }
        posted = await self._post(
            GLOBAL_MEMORY_ROOM,
            "adh.pm",
            body,
            payload,
        )
        artifact = await self._persist(
            kind="pm_brief",
            lane="pm",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            overall=overall,
            recommend_merge=None,
            body=body,
            payload=payload,
            buzz_id=posted.id,
            dimension="req_coverage",
            repo=GLOBAL_REPO,
            scope=MEMORY_SCOPE_GLOBAL,
        )
        await self._heartbeat(
            "adh.pm", self._copy("hermes.pm.heartbeat.brief-done"), EventType.DONE
        )
        return artifact

    async def run_eng_grade(
        self, request: HermesGradeRequest, *, skip_existing: bool = False
    ) -> HermesArtifactRead:
        initiative = "INIT-ADH-000"
        key = f"eng_grade:{request.pr_ref}"
        if skip_existing and await self._store.has_kind("eng_grade", initiative):
            entries = await self._store.list_ledger()
            for entry in entries:
                if entry.kind == "eng_grade" and entry.payload.get("pr_ref") == request.pr_ref:
                    self.logger.info("Hermes eng grade already in ledger", pr_ref=request.pr_ref)
                    return entry
        await self._heartbeat(
            "adh.reviewer",
            self._copy("hermes.eng.heartbeat.grade-start"),
            EventType.START,
        )
        result = await self._prompts.complete(
            "hermes.eng.grade",
            {
                "pr_ref": request.pr_ref,
                "verify_exit": request.verify_exit,
                "notes": request.notes,
                "threshold_x": self._settings.threshold_x,
                "rubric_dimensions": ", ".join(RUBRIC_ENG["dimensions"]),
            },
        )
        parsed, raw, model = result.parsed, result.raw, result.model
        scores = _as_float_map(parsed.get("scores"))
        if request.verify_exit != 0:
            scores["verify"] = 0.0
        overall = weighted_overall(scores, RUBRIC_ENG)
        process = scores.get("process_integrity", 0.0)
        recommend = (
            request.verify_exit == 0 and process > 0 and overall >= self._settings.threshold_x
        )
        body = self._render_grade(request, parsed, overall, recommend, model)
        payload = {
            "lane": "eng",
            "initiative": initiative,
            "pr_ref": request.pr_ref,
            "verify_exit": request.verify_exit,
            "rubric": RUBRIC_ENG["id"],
            "overall": overall,
            "threshold_x": self._settings.threshold_x,
            "scores": scores,
            "recommend_merge": recommend,
            "model": model,
            "rca": parsed.get("rca"),
            "harness_proposal": parsed.get("harness_proposal"),
            "artifact": parsed,
            "raw": raw[:4000],
        }
        posted = await self._post(self._settings.ops_room, "adh.reviewer", body, payload)
        artifact = await self._persist(
            kind="eng_grade",
            lane="eng",
            initiative=initiative,
            rubric_id=RUBRIC_ENG["id"],
            overall=overall,
            recommend_merge="yes" if recommend else "no",
            body=body,
            payload=payload,
            buzz_id=posted.id,
            dimension="knowledge",
            knowledge_key=f"{MEMORY_SCOPE_GLOBAL}:{GLOBAL_REPO}:{key}",
            repo=GLOBAL_REPO,
            scope=MEMORY_SCOPE_GLOBAL,
        )
        await self._heartbeat(
            "adh.reviewer", self._copy("hermes.eng.heartbeat.grade-done"), EventType.DONE
        )
        return artifact

    async def run_pm_think(
        self,
        request: HermesBriefRequest,
        *,
        run: int,
        tenant: TenantContext,
        prior_candidate: Any = None,
        path: Optional[str] = None,
        fail_list: str = "(none)",
        remaining_thinks: int = 0,
    ) -> HermesArtifactRead:
        """Author one think candidate. Does not score, promote, or open a PR."""
        label = f"C{run}"
        template = "hermes.pm.think.c1" if run <= 1 else "hermes.pm.think.c2"
        slug = tenant.slug
        initiative = request.initiative
        claimed = path or think_path(initiative, run)
        occupied = self._workspace.inventory(tenant).inits
        variables: dict[str, Any] = {
            "source_message_id": str(request.source_message_id or "none"),
            "outline": request.outline.strip(),
            "programme_slug": slug,
            "meta_repo": tenant.meta_repo,
            "occupied_inits": ", ".join(occupied) if occupied else "(none)",
            "claimed_path": claimed,
            "initiative": initiative,
            "label": label,
            "fail_list": fail_list,
            "remaining_thinks": remaining_thinks,
            "prior_candidate": prior_candidate or "(none)",
        }
        result = await self._prompts.complete(
            template, variables, model=self._settings.model_for_lane("pm")
        )
        parsed = dict(result.parsed)
        parsed["proposed_init"] = initiative
        parsed["candidate_label"] = label
        path = claimed
        file_body = str(parsed.get("file_body") or "").strip()
        if not file_body:
            file_body = self._render_think_file(initiative, label, parsed, path)
        parsed["file_body"] = file_body
        body = (
            file_body
            if file_body.startswith("#")
            else self._render_think_hop_body(initiative, label, parsed, result.model, path)
        )
        payload = {
            "lane": "pm",
            "hop": f"think-{label.lower()}",
            "initiative": initiative,
            "programme_slug": slug,
            "path": path,
            "model": result.model,
            "stub": result.stub,
            "artifact": parsed,
            "file_body": file_body,
            "raw": result.raw[:4000],
        }
        posted = await self._post(
            tenant.memory_room,
            "adh.pm",
            body,
            payload,
        )
        artifact = await self._persist(
            kind=f"pm_think_{label.lower()}",
            lane="pm",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            overall=None,
            recommend_merge=None,
            body=body,
            payload=payload,
            buzz_id=posted.id,
            dimension="journeys",
            repo=tenant.meta_repo,
            scope=MEMORY_SCOPE_REPO,
        )
        self.logger.info(
            "Hermes think hop persisted",
            initiative=initiative,
            hop=label,
            stub=result.stub,
        )
        return artifact

    async def run_pm_quality(
        self,
        *,
        initiative: str,
        files: list[dict[str, str]],
        tenant: TenantContext,
        outline: str = "",
        pass_number: int = 1,
        max_passes: int = 2,
        source_message_id: Optional[UUID] = None,
    ) -> HermesArtifactRead:
        """Score think files against engineering-ready. Does not promote or merge."""
        result = await self._prompts.complete(
            "hermes.pm.quality",
            {
                "initiative": initiative,
                "source_message_id": str(source_message_id or "none"),
                "rubric_dimensions": ", ".join(RUBRIC_PM["dimensions"]),
                "threshold_x": RUBRIC_PM["threshold_x"],
                "outline": (outline or "").strip() or "(none)",
                "files": _format_ready_files(files),
                "pass_number": pass_number,
                "max_passes": max_passes,
            },
        )
        parsed = apply_ready_gate(dict(result.parsed), files)
        if not parsed.get("candidates"):
            raise TimeoutError(
                self._copy(
                    "hermes.pm.error.ready-no-bars",
                    {"pass_number": pass_number, "initiative": initiative},
                )
            )
        overall = max(
            (float(cand.get("overall") or 0) for cand in parsed["candidates"]),
            default=0.0,
        )
        path = f"prd/reports/{initiative}-prd-quality.md"
        body = self._render_quality_hop_body(
            initiative, parsed, result.model, pass_number, max_passes
        )
        file_body = self._render_quality_file(
            initiative, parsed, path, result.model, pass_number, max_passes
        )
        payload = {
            "lane": "pm",
            "hop": "quality",
            "initiative": initiative,
            "programme_slug": tenant.slug,
            "path": path,
            "rubric": RUBRIC_PM["id"],
            "threshold_x": RUBRIC_PM["threshold_x"],
            "overall": overall,
            "pass_number": pass_number,
            "max_passes": max_passes,
            "model": result.model,
            "stub": result.stub,
            "artifact": parsed,
            "file_body": file_body,
            "raw": result.raw[:4000],
        }
        posted = await self._post(tenant.memory_room, "adh.pm", body, payload)
        artifact = await self._persist(
            kind="pm_quality",
            lane="pm",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            overall=overall,
            recommend_merge=None,
            body=body,
            payload=payload,
            buzz_id=posted.id,
            dimension="findings_quality",
            repo=tenant.meta_repo,
            scope=MEMORY_SCOPE_REPO,
        )
        self.logger.info(
            "Hermes quality hop persisted",
            initiative=initiative,
            overall=overall,
            stub=result.stub,
        )
        return artifact

    async def list_ledger(self) -> list[HermesArtifactRead]:
        return await self._store.list_ledger()

    async def on_room_message(self, room: str, message: MessageRead) -> None:
        """Ack Lead outlines, reject duplicates while in progress, post status."""
        tenant = self._tenants.by_ops_room(room)
        if tenant is None:
            return
        if self._is_lead_init_name(message, tenant):
            await self._on_named_init(tenant, room, message)
            return
        if not self._is_lead_outline(message):
            return
        fingerprint = outline_fingerprint(message.body)
        source_id = str(message.id) if message.id else ""
        claimed = await self._claim_outline(tenant.slug, fingerprint, source_id)
        if not claimed:
            token = _lock_token(tenant.slug, fingerprint)
            owner = self._inflight.get(token) or await self._redis.get(
                self._lock_key(tenant.slug, fingerprint)
            )
            await self._status(
                room,
                self._copy("hermes.pm.status.duplicate"),
                EventType.STALL,
                {
                    "status": "duplicate",
                    "outline_fingerprint": fingerprint,
                    "programme_slug": tenant.slug,
                    "source_message_id": source_id,
                    "in_progress_source": owner,
                },
            )
            self.logger.info(
                "Rejected duplicate Lead outline",
                fingerprint=fingerprint,
                slug=tenant.slug,
                source=source_id,
            )
            return
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.outline-ack",
                {
                    "branch": tenant.integration_branch,
                    "meta_repo": tenant.meta_repo,
                },
            ),
            EventType.START,
            {
                "status": "received",
                "outline_fingerprint": fingerprint,
                "programme_slug": tenant.slug,
                "source_message_id": source_id,
            },
        )
        task = asyncio.create_task(
            self._run_outline_work(tenant, room, message.body, fingerprint, source_id, message.id)
        )
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    async def _run_outline_work(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        fingerprint: str,
        source_id: str,
        source_message_id: Optional[UUID] = None,
        initiative: Optional[str] = None,
    ) -> None:
        awaiting_init = False
        try:
            listing = self._workspace.inventory(tenant)
            try:
                resolved = (
                    _coerce_init(initiative, tenant.slug)
                    if initiative
                    else next_programme_init(tenant.init_prefix, listing.inits)
                )
            except ValueError:
                awaiting_init = True
                await self._ask_for_init(tenant, room, outline, fingerprint, source_id)
                return
            if not _is_numbered_init(resolved, tenant):
                awaiting_init = True
                await self._ask_for_init(tenant, room, outline, fingerprint, source_id)
                return
            await self._clear_pending_init(tenant.slug)
            max_think = int(self._settings.pm_max_think_runs)
            max_ready = int(self._settings.pm_max_ready_passes)
            first_run, second_run = next_free_think_runs(resolved, listing.think_paths)
            occupied = ", ".join(listing.inits) if listing.inits else "(none)"
            meta = {
                "status": "in_progress",
                "outline_fingerprint": fingerprint,
                "source_message_id": source_id,
                "programme_slug": tenant.slug,
                "initiative": resolved,
                "hop": "t0",
                "max_think": max_think,
                "max_ready": max_ready,
            }
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.t0-using-init",
                    {
                        "initiative": resolved,
                        "meta_repo": tenant.meta_repo,
                        "occupied_inits": occupied,
                        "path_c1": think_path(resolved, first_run),
                        "path_c2": think_path(resolved, second_run),
                        "max_think": max_think,
                        "max_ready": max_ready,
                    },
                ),
                EventType.PROGRESS,
                meta,
            )
            await self._walk_pm_authoring(
                tenant,
                room,
                outline,
                resolved,
                source_message_id,
                meta,
                first_run=first_run,
                max_think=max_think,
                max_ready=max_ready,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception(
                "PM outline work failed", fingerprint=fingerprint, slug=tenant.slug
            )
            await self._status(
                room,
                self._copy("hermes.pm.status.failed", {"error": exc}),
                EventType.STALL,
                {
                    "status": "failed",
                    "outline_fingerprint": fingerprint,
                    "programme_slug": tenant.slug,
                    "source_message_id": source_id,
                },
            )
        finally:
            await self._release_outline(tenant.slug, fingerprint)
            if not awaiting_init:
                await self._clear_pending_init(tenant.slug)

    async def _walk_pm_authoring(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        *,
        first_run: int,
        max_think: int,
        max_ready: int,
    ) -> None:
        thinks: list[HermesArtifactRead] = []
        next_run = first_run
        fail_list = "(none)"
        while len(thinks) < 2:
            remaining = max_think - len(thinks) - 1
            prior = _prior_candidate_text(thinks[-1]) if thinks else ""
            artifact = await self._author_think_hop(
                tenant,
                room,
                outline,
                initiative,
                source_message_id,
                meta,
                run=next_run,
                remaining_thinks=max(remaining, 0),
                prior_candidate=prior,
                fail_list=fail_list,
            )
            thinks.append(artifact)
            initiative = artifact.initiative
            meta["initiative"] = initiative
            next_run += 1

        ready_passes = 0
        quality = await self._ready_pass(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            meta,
            thinks,
            pass_number=1,
            max_passes=max_ready,
        )
        ready_passes = 1
        stop_reason = ""
        if _any_handover(quality):
            stop_reason = "handover-yes"
        elif len(thinks) >= max_think:
            stop_reason = "max-think"
        elif ready_passes >= max_ready:
            stop_reason = "max-ready"
        else:
            fail_list = _fail_list_from_quality(quality)
            next_label = f"C{next_run}"
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.loop-continue",
                    {
                        "pass_number": ready_passes,
                        "max_passes": max_ready,
                        "label": next_label,
                        "claimed_path": think_path(initiative, next_run),
                        "fail_list": fail_list,
                        "think_runs": len(thinks),
                        "max_think": max_think,
                    },
                ),
                EventType.PROGRESS,
                {**meta, "hop": "loop"},
            )
            while len(thinks) < max_think:
                remaining = max_think - len(thinks) - 1
                prior = _prior_candidate_text(thinks[-1])
                artifact = await self._author_think_hop(
                    tenant,
                    room,
                    outline,
                    initiative,
                    source_message_id,
                    meta,
                    run=next_run,
                    remaining_thinks=max(remaining, 0),
                    prior_candidate=prior,
                    fail_list=fail_list,
                )
                thinks.append(artifact)
                next_run += 1
            quality = await self._ready_pass(
                tenant,
                room,
                outline,
                initiative,
                source_message_id,
                meta,
                thinks,
                pass_number=2,
                max_passes=max_ready,
            )
            ready_passes = 2
            stop_reason = "handover-yes" if _any_handover(quality) else "max-ready"

        await self._status(
            room,
            self._copy(
                "hermes.pm.status.loop-stop",
                {
                    "reason": stop_reason,
                    "think_runs": len(thinks),
                    "max_think": max_think,
                    "ready_passes": ready_passes,
                    "max_ready": max_ready,
                },
            ),
            EventType.PROGRESS,
            {**meta, "hop": "loop", "stop_reason": stop_reason},
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.promote-is-you", {"initiative": initiative}),
            EventType.DONE,
            {
                **meta,
                "status": "done",
                "hop": "quality",
                "overall": quality.overall,
                "stop_reason": stop_reason,
            },
        )

    async def _author_think_hop(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        *,
        run: int,
        remaining_thinks: int,
        prior_candidate: Any,
        fail_list: str,
    ) -> HermesArtifactRead:
        label = f"C{run}"
        claimed = think_path(initiative, run)
        hop = f"think-{label.lower()}"
        meta["hop"] = hop
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.think", {"label": label}),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.think-next",
                {
                    "label": label,
                    "initiative": initiative,
                    "claimed_path": claimed,
                    "remaining_thinks": remaining_thinks,
                },
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": f"think {label}"}),
            EventType.PROGRESS,
            meta,
        )
        artifact = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_think(
                HermesBriefRequest(
                    initiative=initiative,
                    outline=outline,
                    source_message_id=source_message_id,
                ),
                run=run,
                tenant=tenant,
                path=claimed,
                prior_candidate=prior_candidate,
                fail_list=fail_list,
                remaining_thinks=remaining_thinks,
            ),
        )
        self._raise_if_stub(artifact, f"think {label}")
        await self._publish_hop(
            tenant,
            room,
            artifact,
            f"docs({artifact.initiative}): prd-think {label}",
            {**meta, "hop": hop},
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.think-returned",
                {"label": label, "initiative": artifact.initiative},
            ),
            EventType.PROGRESS,
            {**meta, "hop": hop},
        )
        await self._post_logical(room, self._render_think_hop(artifact), {**meta, "hop": hop})
        return artifact

    async def _ready_pass(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        *,
        pass_number: int,
        max_passes: int,
    ) -> HermesArtifactRead:
        meta["hop"] = "quality"
        files = [_think_file_ref(item) for item in thinks]
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.quality"),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.quality-next",
                {
                    "initiative": initiative,
                    "pass_number": pass_number,
                    "max_passes": max_passes,
                },
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": "quality"}),
            EventType.PROGRESS,
            meta,
        )
        quality = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_quality(
                initiative=initiative,
                files=files,
                tenant=tenant,
                outline=outline,
                pass_number=pass_number,
                max_passes=max_passes,
                source_message_id=source_message_id,
            ),
        )
        self._raise_if_stub(quality, "quality")
        await self._publish_hop(
            tenant,
            room,
            quality,
            f"docs({initiative}): prd-quality",
            meta,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.quality-returned",
                {"pass_number": pass_number, "max_passes": max_passes},
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._post_logical(
            room,
            self._render_quality_hop(quality),
            {**meta, "hop": "quality", "overall": quality.overall},
        )
        return quality

    async def _listen_ops(self, room: str) -> None:
        stream = self._buzz.stream_room(room)
        try:
            await anext(stream)
            self.logger.info("Hermes PM listener subscribed", room=room)
            catch = asyncio.create_task(self._catch_up_ops(room))
            self._work_tasks.add(catch)
            catch.add_done_callback(self._work_tasks.discard)
            async for raw in stream:
                message = _parse_stream_message(raw)
                if message is not None:
                    await self.on_room_message(room, message)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("PM outline listener stopped", room=room)

    async def _catch_up_ops(self, room: str) -> None:
        rows = await self._buzz.list_messages(room, limit=200)
        seen: set[str] = set()
        pending: list[MessageRead] = []
        for message in rows:
            if not self._is_lead_outline(message):
                continue
            fingerprint = outline_fingerprint(message.body)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            if _outline_already_acked(rows, fingerprint):
                continue
            pending.append(message)
        for message in pending:
            await self.on_room_message(room, message)
        tenant = self._tenants.by_ops_room(room)
        if tenant is not None:
            await self._resume_pending_outline(tenant)

    def _is_lead_outline(self, message: MessageRead) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        handle = message.identity_handle or ""
        if handle != self._settings.lead_handle:
            return False
        body = (message.body or "").strip()
        return len(body) >= self._settings.outline_min_chars

    def _is_lead_init_name(self, message: MessageRead, tenant: TenantContext) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        if (message.identity_handle or "") != self._settings.lead_handle:
            return False
        token = (message.body or "").strip().upper()
        prefix = tenant.init_prefix.rstrip("-").upper() + "-"
        if not token.startswith(prefix):
            return False
        if " " in token or "\n" in (message.body or ""):
            return False
        coerced = _coerce_init(token, tenant.slug)
        return _is_numbered_init(coerced, tenant)

    def _pending_init_key(self, slug: str) -> str:
        return f"adh:pm:awaiting-init:{slug}"

    async def _ask_for_init(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        fingerprint: str,
        source_id: str,
    ) -> None:
        listing = self._workspace.inventory(tenant)
        occupied = ", ".join(listing.inits) if listing.inits else "(none)"
        pending = {
            "outline": outline,
            "fingerprint": fingerprint,
            "source_id": source_id,
            "room": room,
        }
        self._awaiting_init[tenant.slug] = pending
        try:
            await self._redis.set(
                self._pending_init_key(tenant.slug),
                pending,
                self._settings.outline_lock_seconds,
            )
        except Exception:
            self.logger.exception("PM pending INIT store failed", slug=tenant.slug)
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.need-init",
                {
                    "meta_repo": tenant.meta_repo,
                    "occupied_inits": occupied,
                    "prefix": tenant.init_prefix,
                },
            ),
            EventType.PROGRESS,
            {
                "status": "need_init",
                "outline_fingerprint": fingerprint,
                "programme_slug": tenant.slug,
                "source_message_id": source_id,
                "hop": "t0",
            },
        )

    async def _load_pending_init(self, slug: str) -> Optional[dict[str, Any]]:
        local = self._awaiting_init.get(slug)
        if local:
            return local
        try:
            raw = await self._redis.get(self._pending_init_key(slug), as_json=True)
        except Exception:
            self.logger.exception("PM pending INIT load failed", slug=slug)
            return None
        return raw if isinstance(raw, dict) else None

    async def _clear_pending_init(self, slug: str) -> None:
        self._awaiting_init.pop(slug, None)
        try:
            await self._redis.delete(self._pending_init_key(slug))
        except Exception:
            self.logger.exception("PM pending INIT clear failed", slug=slug)

    async def _on_named_init(self, tenant: TenantContext, room: str, message: MessageRead) -> None:
        pending = await self._load_pending_init(tenant.slug)
        if pending is None:
            return
        if str(pending.get("room") or room) != room:
            return
        initiative = _coerce_init((message.body or "").strip(), tenant.slug)
        if not _is_numbered_init(initiative, tenant):
            return
        fingerprint = str(pending.get("fingerprint") or "")
        source_id = str(pending.get("source_id") or "")
        outline = str(pending.get("outline") or "")
        if not fingerprint or not outline:
            return
        claimed = await self._claim_outline(tenant.slug, fingerprint, source_id)
        if not claimed:
            return
        await self._clear_pending_init(tenant.slug)
        source_uuid: Optional[UUID] = None
        try:
            source_uuid = UUID(source_id) if source_id else None
        except ValueError:
            source_uuid = None
        task = asyncio.create_task(
            self._run_outline_work(
                tenant,
                room,
                outline,
                fingerprint,
                source_id,
                source_uuid,
                initiative=initiative,
            )
        )
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    async def _resume_pending_outline(self, tenant: TenantContext) -> None:
        """Continue an outline that T0 stored while waiting for an INIT name."""
        pending = await self._load_pending_init(tenant.slug)
        if pending is None:
            return
        room = str(pending.get("room") or tenant.ops_room)
        if room != tenant.ops_room:
            return
        fingerprint = str(pending.get("fingerprint") or "")
        source_id = str(pending.get("source_id") or "")
        outline = str(pending.get("outline") or "")
        if not fingerprint or not outline:
            return
        claimed = await self._claim_outline(tenant.slug, fingerprint, source_id)
        if not claimed:
            return
        await self._clear_pending_init(tenant.slug)
        source_uuid: Optional[UUID] = None
        try:
            source_uuid = UUID(source_id) if source_id else None
        except ValueError:
            source_uuid = None
        self.logger.info(
            "Resuming outline with harness-allocated INIT",
            slug=tenant.slug,
            fingerprint=fingerprint,
        )
        await self._run_outline_work(
            tenant,
            room,
            outline,
            fingerprint,
            source_id,
            source_uuid,
        )

    def _lock_key(self, slug: str, fingerprint: str) -> str:
        return f"adh:pm:inflight:{slug}:{fingerprint}"

    async def _claim_outline(self, slug: str, fingerprint: str, source_id: str) -> bool:
        token = _lock_token(slug, fingerprint)
        if token in self._inflight:
            return False
        try:
            won = await self._redis.set_if_absent(
                self._lock_key(slug, fingerprint),
                source_id,
                self._settings.outline_lock_seconds,
            )
        except Exception:
            self.logger.exception("PM outline lock failed; using process memory")
            won = token not in self._inflight
        if not won:
            return False
        self._inflight[token] = source_id
        return True

    async def _release_outline(self, slug: str, fingerprint: str) -> None:
        token = _lock_token(slug, fingerprint)
        self._inflight.pop(token, None)
        try:
            await self._redis.delete(self._lock_key(slug, fingerprint))
        except Exception:
            self.logger.exception("PM outline unlock failed", fingerprint=fingerprint, slug=slug)

    async def _with_pm_progress(
        self,
        room: str,
        meta: dict[str, Any],
        work: Any,
    ) -> HermesArtifactRead:
        """Wait in wait_step increments, up to wait_steps, then fail. Same model call."""
        interval = float(self._settings.wait_step_seconds)
        steps = int(self._settings.wait_steps)
        task = asyncio.ensure_future(work)
        try:
            for step in range(1, steps + 1):
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=interval)
                except asyncio.TimeoutError:
                    elapsed = step * interval
                    if step >= steps:
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                        raise TimeoutError(
                            self._copy(
                                "hermes.pm.error.model-timeout",
                                {
                                    "steps": steps,
                                    "interval": f"{interval:.0f}",
                                    "elapsed": int(elapsed),
                                },
                            )
                        )
                    wait_vars = {
                        "step": step,
                        "steps": steps,
                        "elapsed": int(elapsed),
                        "interval": f"{interval:.0f}",
                    }
                    await self._status(
                        room,
                        self._copy("hermes.pm.status.still-working", wait_vars),
                        EventType.PROGRESS,
                        {**meta, "wait_step": step, "wait_steps": steps},
                    )
                    await self._heartbeat(
                        "adh.pm",
                        self._copy("hermes.pm.heartbeat.still-working", wait_vars),
                        EventType.PROGRESS,
                    )
            raise TimeoutError(
                self._copy(
                    "hermes.pm.error.model-timeout-plain",
                    {"steps": steps, "interval": f"{interval:.0f}"},
                )
            )
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
            raise

    async def _status(
        self,
        room: str,
        body: str,
        event: EventType,
        payload: dict[str, Any],
    ) -> None:
        payload = {**payload, "lane": "pm", "service": "hermes"}
        await self._post(room, "adh.pm", body, payload, event_type=event)

    async def _publish_hop(
        self,
        tenant: TenantContext,
        room: str,
        artifact: HermesArtifactRead,
        commit_message: str,
        meta: dict[str, Any],
    ) -> None:
        path = str(artifact.payload.get("path") or "")
        contents = str(artifact.payload.get("file_body") or artifact.body)
        result = await self._workspace.publish(tenant, path, contents, commit_message)
        local = result.get("local_path") or "skipped"
        github = result.get("github") or {}
        sha = ""
        if isinstance(github, dict):
            sha = str(github.get("commit_sha") or github.get("sha") or "")
        github_state = f"committed {sha[:7]}" if sha else "skipped"
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.wrote-file",
                {
                    "path": path,
                    "branch": tenant.integration_branch,
                    "local": local,
                    "github_state": github_state,
                },
            ),
            EventType.PROGRESS,
            {**meta, "path": path, "publish": result, "programme_slug": tenant.slug},
        )
        self.logger.info(
            "PM hop published to meta repo",
            initiative=artifact.initiative,
            slug=tenant.slug,
            path=path,
            local=local,
            github=github_state,
        )

    async def _post_logical(self, room: str, body: str, payload: dict[str, Any]) -> None:
        await self._post(
            room,
            "adh.pm",
            body,
            {**payload, "status": str(payload.get("hop") or "logical"), "lane": "pm"},
            event_type=None,
            kind=MessageKind.MESSAGE,
        )

    async def _heartbeat(
        self,
        handle: str,
        body: str,
        event: EventType,
        room_slug: Optional[str] = None,
    ) -> None:
        try:
            await self._buzz.ingest_heartbeat(
                HeartbeatIngest(
                    identity_handle=handle,
                    room_slug=room_slug or self._settings.ops_room,
                    body=body,
                    event_type=event,
                    payload={"service": "hermes"},
                )
            )
        except Exception:
            self.logger.exception("Hermes heartbeat failed", handle=handle)

    async def _post(
        self,
        room: str,
        handle: str,
        body: str,
        payload: dict[str, Any],
        event_type: Optional[EventType] = EventType.DONE,
        kind: MessageKind = MessageKind.EVENT,
    ) -> Any:
        return await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=handle,
                body=body,
                kind=kind,
                event_type=event_type,
                payload=payload,
            ),
        )

    def _copy(self, template_id: str, variables: Optional[dict[str, Any]] = None) -> str:
        return self._prompts.render_copy(template_id, variables or {})

    def _raise_if_stub(self, artifact: HermesArtifactRead, hop: str) -> None:
        reason = str(artifact.payload.get("raw") or "").strip() or "no JSON object"
        if artifact.payload.get("stub") or artifact.payload.get("model") == "stub":
            raise TimeoutError(
                self._copy("hermes.pm.error.stub-hop", {"hop": hop, "reason": reason})
            )
        if str(artifact.initiative).endswith("-PENDING") or artifact.initiative == "INIT-PENDING":
            raise TimeoutError(self._copy("hermes.pm.error.pending-init", {"hop": hop}))

    def _think_copy_vars(
        self,
        initiative: str,
        label: str,
        parsed: dict[str, Any],
        path: str,
        *,
        model: str = "",
        numbered_locked: bool = False,
    ) -> dict[str, Any]:
        locked = parsed.get("locked_decisions")
        return {
            "initiative": initiative,
            "label": label,
            "path": path or f"prd/reports/{initiative}-prd-think.md",
            "model": model,
            "short": str(parsed.get("summary") or parsed.get("job") or "prd-think candidate").split(
                "\n"
            )[0],
            "job": parsed.get("job") or "(none)",
            "why_now": parsed.get("why_now") or "(none)",
            "if_we_do_nothing": parsed.get("if_we_do_nothing") or "(none)",
            "kill_assumption": parsed.get("kill_assumption") or "(none)",
            "locked_decisions": (_numbered(locked) if numbered_locked else _bullets(locked)),
            "in_scope": _bullets(parsed.get("in_scope")),
            "non_goals": _bullets(parsed.get("non_goals")),
            "capabilities": _format_caps(parsed.get("capabilities")),
            "requirements": _format_reqs(parsed.get("requirements")),
            "journeys": _format_journeys(parsed.get("journeys")),
            "open_questions": _format_oqs(parsed.get("open_questions")),
            "whole_product_delta": parsed.get("whole_product_delta") or "(none)",
            "equivalent_product_notes": parsed.get("equivalent_product_notes") or "(none)",
            "summary": parsed.get("summary") or "(none)",
        }

    def _render_think_hop_body(
        self,
        initiative: str,
        label: str,
        parsed: dict[str, Any],
        model: str,
        path: str,
    ) -> str:
        return self._copy(
            "hermes.pm.hop.think",
            self._think_copy_vars(initiative, label, parsed, path, model=model),
        )

    def _render_think_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        path = str(artifact.payload.get("path") or "")
        label = str(parsed.get("candidate_label") or "C1")
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        file_body = str(artifact.payload.get("file_body") or "").strip()
        if file_body.startswith("#"):
            excerpt = "\n".join(file_body.splitlines()[:28])
            return (
                f"Think {label}  {artifact.initiative}\n"
                f"path: {path}\n"
                f"model={model}  ·  not scored  ·  Hermes will not merge\n\n"
                f"{excerpt}\n…"
            )
        return self._render_think_hop_body(artifact.initiative, label, parsed, model, path)

    def _render_think_file(
        self, initiative: str, label: str, parsed: dict[str, Any], path: str
    ) -> str:
        return self._copy(
            "hermes.pm.file.think",
            self._think_copy_vars(initiative, label, parsed, path, numbered_locked=True),
        )

    def _render_quality_hop_body(
        self,
        initiative: str,
        parsed: dict[str, Any],
        model: str,
        pass_number: int = 1,
        max_passes: int = 2,
    ) -> str:
        return self._copy(
            "hermes.pm.hop.quality",
            {
                "initiative": initiative,
                "model": model,
                "threshold_x": RUBRIC_PM["threshold_x"],
                "rank": parsed.get("rank") or "tie",
                "pass_number": pass_number,
                "max_passes": max_passes,
                "candidate_block": _format_candidate_block(parsed.get("candidates") or []),
                "recommend_promote": parsed.get("recommend_promote") or "none",
                "notes": parsed.get("notes") or "(none)",
                "harness_proposal": parsed.get("harness_proposal") or "(none)",
            },
        )

    def _render_quality_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        return self._render_quality_hop_body(
            artifact.initiative,
            parsed,
            model,
            int(artifact.payload.get("pass_number") or 1),
            int(artifact.payload.get("max_passes") or 2),
        )

    def _render_quality_file(
        self,
        initiative: str,
        parsed: dict[str, Any],
        path: str,
        model: str,
        pass_number: int = 1,
        max_passes: int = 2,
    ) -> str:
        hop_body = self._render_quality_hop_body(initiative, parsed, model, pass_number, max_passes)
        candidates = parsed.get("candidates") or []
        return self._copy(
            "hermes.pm.file.quality",
            {
                "initiative": initiative,
                "files_row": _files_row(candidates),
                "handover_row": _handover_row(candidates),
                "path": path,
                "rank": parsed.get("rank") or "tie",
                "pass_number": pass_number,
                "max_passes": max_passes,
                "hop_body": hop_body,
            },
        )

    def _render_brief(
        self, initiative: str, parsed: dict[str, Any], overall: float, model: str
    ) -> str:
        return self._copy(
            "hermes.pm.hop.brief",
            {
                "initiative": initiative,
                "overall": overall,
                "model": model,
                "summary": parsed.get("summary") or "PM brief",
            },
        )

    def _render_grade(
        self,
        request: HermesGradeRequest,
        parsed: dict[str, Any],
        overall: float,
        recommend: bool,
        model: str,
    ) -> str:
        return self._copy(
            "hermes.eng.hop.grade",
            {
                "pr_ref": request.pr_ref,
                "verify_exit": request.verify_exit,
                "overall": overall,
                "threshold_x": self._settings.threshold_x,
                "merge": "recommend merge" if recommend else "do not merge",
                "model": model,
                "notes": parsed.get("notes") or parsed.get("rca") or "grade recorded",
            },
        )

    async def _persist(
        self,
        *,
        kind: str,
        lane: str,
        initiative: str,
        rubric_id: str,
        overall: Optional[float],
        recommend_merge: Optional[str],
        body: str,
        payload: dict[str, Any],
        buzz_id: Optional[UUID],
        dimension: str,
        repo: str,
        scope: str,
        knowledge_key: Optional[str] = None,
    ) -> HermesArtifactRead:
        scoped = {
            **payload,
            "repo": repo,
            "scope": scope,
            "memory_room": (
                GLOBAL_MEMORY_ROOM if scope == MEMORY_SCOPE_GLOBAL else memory_room_for_repo(repo)
            ),
        }
        key = knowledge_key or knowledge_scope_key(
            scope=scope, repo=repo, kind=kind, initiative=initiative
        )
        await self._store.save_memory(
            kind=kind,
            initiative=initiative,
            body=body,
            payload=scoped,
            source_buzz_id=buzz_id,
        )
        await self._store.save_knowledge(
            lane=lane,
            dimension=dimension,
            key=key,
            body=body,
            payload=scoped,
            source_buzz_id=buzz_id,
        )
        return await self._store.save_ledger(
            kind=kind,
            initiative=initiative,
            rubric_id=rubric_id,
            overall=overall,
            recommend_merge=recommend_merge,
            body=body,
            payload=scoped,
            buzz_message_id=buzz_id,
        )


def _lock_token(slug: str, fingerprint: str) -> str:
    return f"{slug}:{fingerprint}"


def outline_fingerprint(body: str) -> str:
    normalized = " ".join(body.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _parse_stream_message(raw: str) -> Optional[MessageRead]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("type") in {"ping", "subscribed"}:
        return None
    try:
        return MessageRead.model_validate(data)
    except Exception:
        return None


def _outline_already_acked(rows: list[MessageRead], fingerprint: str) -> bool:
    for message in rows:
        if message.identity_handle != "adh.pm":
            continue
        payload = message.payload or {}
        if payload.get("outline_fingerprint") != fingerprint:
            continue
        if payload.get("status") in {"received", "in_progress", "done", "need_init"}:
            return True
    return False


def _as_float_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        try:
            out[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


_MATERIAL_BARS = {
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B8",
    "B9",
    "B10",
    "B11",
    "B12",
    "B14",
    "B15",
}


def apply_ready_gate(parsed: dict[str, Any], files: list[dict[str, str]]) -> dict[str, Any]:
    """Merge LLM B-bar with code skeleton FAILs. Empty B-table cannot be handover yes."""
    by_label = {str(item.get("label") or ""): item for item in files}
    raw = parsed.get("candidates")
    if not isinstance(raw, list) or not raw:
        raw = [{"label": item.get("label"), "path": item.get("path")} for item in files]
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        source = by_label.get(label) or {}
        path = str(item.get("path") or source.get("path") or "")
        body = str(source.get("file_body") or "")
        skel = skeleton_material_fails(body)
        raw_bars = item.get("bars")
        bars_in: list[Any] = raw_bars if isinstance(raw_bars, list) else []
        bar_rows: list[dict[str, Any]] = []
        fails: list[str] = [str(fail) for fail in (item.get("material_fails") or []) if fail]
        for bar in bars_in:
            if not isinstance(bar, dict):
                continue
            bid = str(bar.get("bar") or "").strip().split()[0].upper()
            result = str(bar.get("result") or "").strip().upper()
            evidence = str(bar.get("evidence") or "")
            material = bool(bar.get("material", bid in _MATERIAL_BARS))
            bar_rows.append(
                {
                    "bar": bid or str(bar.get("bar") or ""),
                    "result": result,
                    "material": material,
                    "evidence": evidence,
                }
            )
            if result == "FAIL" and (material or bid in _MATERIAL_BARS):
                fails.append(f"{bid} {evidence}".strip())
        if not bar_rows:
            for fail in skel:
                bid = fail.split()[0]
                bar_rows.append({"bar": bid, "result": "FAIL", "material": True, "evidence": fail})
        fails.extend(skel)
        unique = list(dict.fromkeys(fails))
        if not bar_rows:
            unique.append("ready judge returned no B-bar")
            bar_rows.append(
                {
                    "bar": "B1",
                    "result": "FAIL",
                    "material": True,
                    "evidence": "ready judge returned no B-bar",
                }
            )
        scores = _as_float_map(item.get("scores"))
        handover = str(item.get("handover") or "no").strip().lower()
        if unique:
            handover = "no"
        candidates.append(
            {
                "label": label,
                "path": path,
                "handover": "yes" if handover == "yes" else "no",
                "material_fails": unique,
                "bars": bar_rows,
                "spec_lane_guesses": [str(row) for row in (item.get("spec_lane_guesses") or [])],
                "scores": scores,
                "overall": weighted_overall(scores, RUBRIC_PM),
            }
        )
    parsed["candidates"] = candidates
    yes_labels = [cand["label"] for cand in candidates if cand["handover"] == "yes"]
    recommend = str(parsed.get("recommend_promote") or "").strip().upper()
    allowed = {label.upper() for label in yes_labels}
    if recommend not in allowed:
        parsed["recommend_promote"] = yes_labels[0] if len(yes_labels) == 1 else ""
    return parsed


def _format_ready_files(files: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    for item in files:
        label = item.get("label") or "?"
        path = item.get("path") or ""
        body = item.get("file_body") or "(empty file)"
        chunks.append(f"### {label} `{path}`\n{body}")
    return "\n\n".join(chunks) if chunks else "(none)"


def _prior_candidate_text(artifact: HermesArtifactRead) -> str:
    body = str(artifact.payload.get("file_body") or "").strip()
    if body:
        return body
    parsed = artifact.payload.get("artifact") or {}
    if isinstance(parsed, dict):
        return json.dumps(parsed)
    return str(parsed or "")


def _think_file_ref(artifact: HermesArtifactRead) -> dict[str, str]:
    parsed = dict(artifact.payload.get("artifact") or {})
    return {
        "label": str(parsed.get("candidate_label") or "C1"),
        "path": str(artifact.payload.get("path") or ""),
        "file_body": str(artifact.payload.get("file_body") or ""),
    }


def _any_handover(artifact: HermesArtifactRead) -> bool:
    parsed = artifact.payload.get("artifact") or {}
    return any(
        str(cand.get("handover") or "").lower() == "yes" for cand in parsed.get("candidates") or []
    )


def _fail_list_from_quality(artifact: HermesArtifactRead) -> str:
    parsed = artifact.payload.get("artifact") or {}
    fails: list[str] = []
    for cand in parsed.get("candidates") or []:
        label = cand.get("label") or "?"
        for item in cand.get("material_fails") or []:
            fails.append(f"{label}: {item}")
    return "; ".join(fails) if fails else "(none)"


def _format_candidate_block(candidates: list[Any]) -> str:
    lines: list[str] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        label = cand.get("label") or "?"
        lines.append(
            f"{label} handover={cand.get('handover')} overall={cand.get('overall')}/3 "
            f"FAILs: {_inline_list(cand.get('material_fails'))}"
        )
        for bar in cand.get("bars") or []:
            if not isinstance(bar, dict):
                continue
            lines.append(
                f"  {bar.get('bar')} {bar.get('result')} {bar.get('evidence') or ''}".rstrip()
            )
    return "\n".join(lines) if lines else "(none)"


def _files_row(candidates: list[Any]) -> str:
    parts = []
    for cand in candidates:
        if isinstance(cand, dict) and cand.get("label"):
            parts.append(f"{cand.get('label')} `{cand.get('path')}`")
    return " / ".join(parts) if parts else "(none)"


def _handover_row(candidates: list[Any]) -> str:
    parts = []
    for cand in candidates:
        if isinstance(cand, dict) and cand.get("label"):
            parts.append(f"{cand.get('label')}: {cand.get('handover')}")
    return "; ".join(parts) if parts else "(none)"


def _is_numbered_init(token: str, tenant: TenantContext) -> bool:
    prefix = tenant.init_prefix.upper()
    body = (token or "").strip().upper()
    if not prefix or not body.startswith(prefix):
        return False
    rest = body[len(prefix) :]
    return bool(rest) and rest.isdigit()


def _coerce_init(proposed: str, slug: str) -> str:
    prefix = f"INIT-{slug.upper()}-"
    token = (proposed or "").strip().upper()
    if not token.startswith("INIT-"):
        return f"{prefix}PENDING"
    rest = token[len("INIT-") :]
    for drop in (f"{slug.upper()}-", "RW-", "ADH-"):
        if rest.startswith(drop):
            rest = rest[len(drop) :]
            break
    rest = re.sub(r"[^A-Z0-9-]", "", rest).strip("-")
    if not rest or rest == "PENDING":
        return f"{prefix}PENDING"
    return f"{prefix}{rest}"


def _numbered(value: Any) -> str:
    if not value:
        return "(none)"
    if not isinstance(value, list):
        return f"1. {value}"
    lines = [f"{index}. {item}" for index, item in enumerate(value, start=1)]
    return "\n".join(lines) if lines else "(none)"


def _inline_list(value: Any) -> str:
    if not value:
        return "(none)"
    if not isinstance(value, list):
        return str(value)
    return "; ".join(str(item) for item in value) if value else "(none)"


def _format_caps(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        journeys = ", ".join(str(j) for j in item.get("journeys") or []) or "none"
        notes = str(item.get("notes") or "").strip()
        extra = f" — {notes}" if notes else ""
        lines.append(
            f"- {item.get('id') or '?'}: {item.get('capability') or ''} " f"(J: {journeys}){extra}"
        )
    return "\n".join(lines)


def _format_reqs(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        lines.append(
            f"- {item.get('id') or '?'}/{item.get('cap') or '?'}: "
            f"{item.get('requirement') or ''} | when {item.get('condition') or 'n/a'} "
            f"→ {item.get('observable') or 'n/a'} "
            f"(evidence: {item.get('evidence') or 'n/a'})"
        )
    return "\n".join(lines)


def _format_journeys(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        caps = ", ".join(str(c) for c in item.get("caps") or []) or "none"
        lines.append(
            f"- {item.get('id') or '?'}: {item.get('actor') or '?'} / "
            f"{item.get('trigger') or '?'} → {item.get('main_flow') or '?'} "
            f"(edge: {item.get('edge') or 'n/a'}; abandon: {item.get('abandon') or 'n/a'}; "
            f"CAP: {caps})"
        )
    return "\n".join(lines)


def _format_oqs(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "- (none)"
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        lines.append(
            f"- {item.get('id') or '?'}: {item.get('question') or ''} "
            f"(owner={item.get('owner') or 'PM'}; blocking={item.get('blocking') or 'yes'}; "
            f"by {item.get('required_by') or 'spec-draft'})"
        )
    return "\n".join(lines)


def _bullets(value: Any) -> str:
    if not value:
        return "- (none)"
    if not isinstance(value, list):
        return f"- {value}"
    lines: list[str] = []
    for item in value:
        if isinstance(item, dict):
            lane = str(item.get("lane") or "").strip()
            text = str(item.get("text") or "").strip()
            lines.append(f"- {lane}: {text}" if lane else f"- {text}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines) if lines else "- (none)"
