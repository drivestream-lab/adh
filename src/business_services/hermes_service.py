"""Hermes: PM lane + after-PR verify/grade/RCA. Does not merge."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.configs.rubrics import RUBRIC_ENG, RUBRIC_PM, weighted_overall
from src.infra_services.hermes_store_service import HermesStoreService
from src.business_services.hermes.cards import (
    _scorecard_for_card,
    apply_ask_card,
    apply_quality_card,
)
from src.business_services.hermes.gates import (
    _any_handover,
    _as_float_map,
    apply_ready_gate,
    apply_recommend_gate,
)
from src.business_services.hermes.lead_tokens import (
    _coerce_init,
    _is_numbered_init,
    is_lead_outline_body,
    lock_token as _lock_token,
    outline_fingerprint,
    parse_ask_answers,
    parse_promote_pick,
    validate_ask_answers,
)
from src.business_services.hermes import pending as pm_pending
from src.business_services.hermes.render_pm import (
    _bullets,
    _fail_list_from_quality,
    _format_answers,
    _format_caps,
    _format_fork_block,
    _format_journeys,
    _format_oqs,
    _format_ready_files,
    _format_reqs,
    _format_why_not,
    _numbered,
    _prior_candidate_text,
    _quality_copy_vars,
    _think_file_ref,
)
from src.infra_services.pm_workspace_service import (
    PmWorkspaceService,
    ask_path,
    next_free_think_runs,
    next_programme_init,
    prd_path,
    quality_path,
    recommend_path,
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
from src.models.prompt_models import (
    ask_card_has_signal,
    cap_ask_forks,
    quality_card_has_signal,
    quality_has_signal,
)


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
        self._awaiting_ask: dict[str, dict[str, Any]] = {}
        self._awaiting_recommend: dict[str, dict[str, Any]] = {}
        self._ask_events: dict[str, asyncio.Event] = {}
        self._ask_answers: dict[str, dict[str, str]] = {}
        self._outline_tasks: dict[str, asyncio.Task[None]] = {}
        self._open_initiative: dict[str, str] = {}

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
            "raw": raw[:32000],
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
            "raw": raw[:32000],
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
            "raw": result.raw[:32000],
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
        if not quality_has_signal(parsed):
            raise TimeoutError(
                self._copy(
                    "hermes.pm.error.ready-no-bars",
                    {"pass_number": pass_number, "initiative": initiative},
                )
            )
        parsed = await self._apply_quality_card(
            initiative, parsed, files, outline or "", result.model
        )
        overall = max(
            (float(cand.get("overall") or 0) for cand in parsed["candidates"]),
            default=0.0,
        )
        path = f"prd/reports/{initiative}-prd-quality.md"
        body = self._render_quality_hop_body(
            initiative, parsed, result.model, pass_number, max_passes, path
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
            "raw": result.raw[:32000],
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

    async def run_pm_ask(
        self,
        *,
        initiative: str,
        files: list[dict[str, str]],
        tenant: TenantContext,
        outline: str = "",
        scorecard: str = "",
        answers: str = "(none)",
        source_message_id: Optional[UUID] = None,
    ) -> HermesArtifactRead:
        """Pose closed forks that change the pick. Does not recommend or promote."""
        max_forks = int(self._settings.pm_max_ask_forks)
        result = await self._prompts.complete(
            "hermes.pm.ask",
            {
                "initiative": initiative,
                "source_message_id": str(source_message_id or "none"),
                "outline": (outline or "").strip() or "(none)",
                "files": _format_ready_files(files),
                "scorecard": (scorecard or "").strip() or "(none)",
                "answers": answers,
                "max_forks": max_forks,
            },
        )
        parsed = dict(result.parsed)
        parsed["forks"] = cap_ask_forks(parsed.get("forks"), max_forks=max_forks)
        parsed = await self._apply_ask_card(initiative, parsed, files, outline or "", result.model)
        path = ask_path(initiative)
        body = self._render_ask_hop_body(initiative, parsed, result.model)
        file_body = self._render_ask_file(initiative, parsed, path)
        payload = {
            "lane": "pm",
            "hop": "ask",
            "initiative": initiative,
            "programme_slug": tenant.slug,
            "path": path,
            "model": result.model,
            "stub": result.stub,
            "artifact": parsed,
            "file_body": file_body,
            "raw": result.raw[:32000],
        }
        posted = await self._post(tenant.memory_room, "adh.pm", body, payload)
        artifact = await self._persist(
            kind="pm_ask",
            lane="pm",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            overall=None,
            recommend_merge=None,
            body=body,
            payload=payload,
            buzz_id=posted.id,
            dimension="findings_quality",
            repo=tenant.meta_repo,
            scope=MEMORY_SCOPE_REPO,
        )
        self.logger.info(
            "Hermes ask hop persisted",
            initiative=initiative,
            forks=len(parsed.get("forks") or []),
            stub=result.stub,
        )
        return artifact

    async def run_pm_recommend(
        self,
        *,
        initiative: str,
        files: list[dict[str, str]],
        tenant: TenantContext,
        quality: HermesArtifactRead,
        outline: str = "",
        scorecard: str = "",
        answers: str = "(none)",
        ask_file: str = "(none)",
        source_message_id: Optional[UUID] = None,
    ) -> HermesArtifactRead:
        """Recommend a think file vs the brief. Does not promote, draft, or merge."""
        result = await self._prompts.complete(
            "hermes.pm.recommend",
            {
                "initiative": initiative,
                "source_message_id": str(source_message_id or "none"),
                "outline": (outline or "").strip() or "(none)",
                "files": _format_ready_files(files),
                "scorecard": (scorecard or "").strip() or "(none)",
                "answers": answers,
                "ask_file": ask_file,
            },
        )
        parsed = apply_recommend_gate(dict(result.parsed), files, quality)
        path = recommend_path(initiative)
        body = self._render_recommend_hop_body(initiative, parsed, result.model)
        file_body = str(parsed.get("file_body") or "").strip()
        if not file_body.startswith("#"):
            file_body = self._render_recommend_file(initiative, parsed, path)
        parsed["file_body"] = file_body
        payload = {
            "lane": "pm",
            "hop": "recommend",
            "initiative": initiative,
            "programme_slug": tenant.slug,
            "path": path,
            "model": result.model,
            "stub": result.stub,
            "artifact": parsed,
            "file_body": file_body,
            "raw": result.raw[:32000],
        }
        posted = await self._post(tenant.memory_room, "adh.pm", body, payload)
        artifact = await self._persist(
            kind="pm_recommend",
            lane="pm",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            overall=None,
            recommend_merge=None,
            body=body,
            payload=payload,
            buzz_id=posted.id,
            dimension="findings_quality",
            repo=tenant.meta_repo,
            scope=MEMORY_SCOPE_REPO,
        )
        self.logger.info(
            "Hermes recommend hop persisted",
            initiative=initiative,
            recommend=parsed.get("recommend"),
            stub=result.stub,
        )
        return artifact

    async def replay_pm_ask_recommend(
        self,
        tenant: TenantContext,
        initiative: str,
        outline: str,
        *,
        wait_seconds: Optional[float] = 0,
    ) -> None:
        """Run ask then recommend on existing think/quality files. Does not allocate INIT."""
        thinks: list[HermesArtifactRead] = []
        for run in range(1, 9):
            path = think_path(initiative, run)
            body = self._workspace.read_local(tenant, path)
            if not body.strip():
                continue
            thinks.append(
                HermesArtifactRead(
                    kind=f"pm_think_c{run}",
                    initiative=initiative,
                    rubric_id=RUBRIC_PM["id"],
                    body=body[:500],
                    payload={
                        "path": path,
                        "file_body": body,
                        "artifact": {"candidate_label": f"C{run}"},
                        "hop": f"think-c{run}",
                    },
                )
            )
        qpath = quality_path(initiative)
        qbody = self._workspace.read_local(tenant, qpath)
        if not thinks or not qbody.strip():
            raise TimeoutError("replay needs think and quality files on the meta repo")
        quality = HermesArtifactRead(
            kind="pm_quality",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            body=qbody,
            payload={"path": qpath, "file_body": qbody, "artifact": {}, "hop": "quality"},
        )
        meta = {
            "initiative": initiative,
            "programme_slug": tenant.slug,
            "status": "in_progress",
            "hop": "ask",
        }
        previous = float(self._settings.pm_ask_wait_seconds)
        if wait_seconds is not None:
            self._settings = self._settings.model_copy(
                update={"pm_ask_wait_seconds": float(wait_seconds)}
            )
        try:
            await self._ask_then_recommend(
                tenant,
                tenant.ops_room,
                outline,
                initiative,
                None,
                meta,
                thinks,
                quality,
            )
        finally:
            self._settings = self._settings.model_copy(update={"pm_ask_wait_seconds": previous})

    async def list_ledger(self) -> list[HermesArtifactRead]:
        return await self._store.list_ledger()

    async def on_room_message(self, room: str, message: MessageRead) -> None:
        """Ack Lead outlines, reject duplicates while in progress, post status."""
        tenant = self._tenants.by_ops_room(room)
        if tenant is None:
            return
        if await self._try_lead_stop(tenant, room, message):
            return
        if await self._try_ask_answer(tenant, room, message):
            return
        if await self._try_promote_pick(tenant, room, message):
            return
        if self._is_lead_init_name(message, tenant):
            await self._on_named_init(tenant, room, message)
            return
        if not self._is_lead_outline(message):
            return
        fingerprint = outline_fingerprint(message.body)
        if self._tenant_has_open_work(tenant.slug):
            token = _lock_token(tenant.slug, fingerprint)
            if token in self._inflight:
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
                        "source_message_id": str(message.id) if message.id else "",
                        "in_progress_source": owner,
                    },
                )
                return
            await self._status(
                room,
                self._copy("hermes.pm.status.busy"),
                EventType.STALL,
                {
                    "status": "busy",
                    "outline_fingerprint": fingerprint,
                    "programme_slug": tenant.slug,
                    "source_message_id": str(message.id) if message.id else "",
                },
            )
            self.logger.info(
                "Ignored Lead outline while programme work is open",
                slug=tenant.slug,
                fingerprint=fingerprint,
            )
            return
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
        self._track_outline_task(
            tenant.slug,
            asyncio.create_task(
                self._run_outline_work(
                    tenant, room, message.body, fingerprint, source_id, message.id
                )
            ),
        )

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
            self._open_initiative[tenant.slug] = resolved
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
            self._open_initiative.pop(tenant.slug, None)
            if self._outline_tasks.get(tenant.slug) is asyncio.current_task():
                self._outline_tasks.pop(tenant.slug, None)
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
        await self._ask_then_recommend(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            {**meta, "stop_reason": stop_reason, "overall": quality.overall},
            thinks,
            quality,
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

    async def _ask_then_recommend(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
    ) -> None:
        ask, answers = await self._ask_pass(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            meta,
            thinks,
            quality,
        )
        if answers.get("_skip") == "stop":
            await self._clear_pending_ask(tenant.slug)
            await self._status(
                room,
                self._copy("hermes.pm.status.ask-stopped", {"initiative": initiative}),
                EventType.STALL,
                {**meta, "status": "stopped", "hop": "ask"},
            )
            await self._status(
                room,
                self._copy("hermes.pm.status.promote-is-you", {"initiative": initiative}),
                EventType.DONE,
                {**meta, "status": "done", "hop": "ask"},
            )
            return
        if not answers or answers.get("_skip"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-timeout-provisional",
                    {"initiative": initiative},
                ),
                EventType.PROGRESS,
                {**meta, "hop": "ask", "status": "provisional"},
            )
        await self._recommend_pass(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            meta,
            thinks,
            quality,
            ask,
            answers,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.promote-is-you", {"initiative": initiative}),
            EventType.DONE,
            {
                **meta,
                "status": "done",
                "hop": "recommend",
                "overall": quality.overall,
            },
        )

    async def _ask_pass(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
    ) -> tuple[HermesArtifactRead, dict[str, str]]:
        meta = {**meta, "hop": "ask"}
        files = [_think_file_ref(item) for item in thinks]
        qpath = str(quality.payload.get("path") or quality_path(initiative))
        files.append(
            {
                "label": "quality",
                "path": qpath,
                "file_body": str(quality.payload.get("file_body") or quality.body),
            }
        )
        scorecard = self._render_quality_hop(quality)
        max_forks = int(self._settings.pm_max_ask_forks)
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.ask"),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-next",
                {"initiative": initiative, "max_forks": max_forks},
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": "ask"}),
            EventType.PROGRESS,
            meta,
        )
        artifact = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_ask(
                initiative=initiative,
                files=files,
                tenant=tenant,
                outline=outline,
                scorecard=scorecard,
                source_message_id=source_message_id,
            ),
        )
        self._raise_if_stub(artifact, "ask")
        await self._publish_hop(
            tenant,
            room,
            artifact,
            f"docs({initiative}): prd-ask",
            meta,
        )
        forks = list((artifact.payload.get("artifact") or {}).get("forks") or [])
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-returned",
                {"initiative": initiative, "fork_count": len(forks)},
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._post_logical(room, self._render_ask_hop(artifact), {**meta, "hop": "ask"})
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-card",
                {
                    "initiative": initiative,
                    "fork_block": _format_fork_block(forks),
                },
            ),
            EventType.PROGRESS,
            {**meta, "hop": "ask", "status": "need_ask", "choices": forks},
        )
        timeout = float(self._settings.pm_ask_wait_seconds)
        if not forks or timeout <= 0:
            return artifact, {}
        await self._store_pending_ask(
            tenant,
            room,
            outline,
            initiative,
            thinks,
            quality,
            forks,
        )
        answers = await self._wait_ask_answers(tenant.slug, timeout)
        await self._clear_pending_ask(tenant.slug)
        return artifact, answers

    async def _recommend_pass(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
        ask: HermesArtifactRead,
        answers: dict[str, str],
    ) -> HermesArtifactRead:
        meta = {**meta, "hop": "recommend"}
        files = [_think_file_ref(item) for item in thinks]
        scorecard = self._render_quality_hop(quality)
        ask_file = str(ask.payload.get("file_body") or ask.body)
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.recommend"),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.recommend-next", {"initiative": initiative}),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": "recommend"}),
            EventType.PROGRESS,
            meta,
        )
        artifact = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_recommend(
                initiative=initiative,
                files=files,
                tenant=tenant,
                quality=quality,
                outline=outline,
                scorecard=scorecard,
                answers=_format_answers(answers),
                ask_file=ask_file,
                source_message_id=source_message_id,
            ),
        )
        self._raise_if_stub(artifact, "recommend")
        await self._publish_hop(
            tenant,
            room,
            artifact,
            f"docs({initiative}): prd-recommend",
            meta,
        )
        parsed = dict(artifact.payload.get("artifact") or {})
        pick = str(parsed.get("recommend") or "none")
        path = str(parsed.get("path") or artifact.payload.get("path") or "")
        ready = str(parsed.get("engineering_ready") or "no")
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.recommend-returned",
                {
                    "initiative": initiative,
                    "recommend": pick,
                    "engineering_ready": ready,
                },
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._post_logical(
            room,
            self._render_recommend_hop(artifact),
            {**meta, "hop": "recommend"},
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.recommend-card",
                {
                    "initiative": initiative,
                    "recommend": pick,
                    "path": path or "(none)",
                    "engineering_ready": ready,
                    "why": str(parsed.get("why") or "(none)"),
                },
            ),
            EventType.PROGRESS,
            {
                **meta,
                "hop": "recommend",
                "status": "need_promote",
                "choices": [pick, "none", "iterate"],
            },
        )
        await self._store_pending_recommend(
            tenant,
            room,
            initiative,
            pick,
            path,
            think_paths=[str(item.get("path") or "") for item in files],
        )
        return artifact

    async def _listen_ops(self, room: str) -> None:
        delay = 1.0
        while True:
            stream = self._buzz.stream_room(room)
            try:
                await anext(stream)
                delay = 1.0
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
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
            finally:
                try:
                    await stream.aclose()
                except Exception:
                    self.logger.exception("PM outline listener stream close failed", room=room)

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
            await self._resume_pending_ask(tenant)

    def _is_lead_text(self, message: MessageRead) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        return (message.identity_handle or "") == self._settings.lead_handle

    def _is_lead_stop(self, message: MessageRead) -> bool:
        return self._is_lead_text(message) and (message.body or "").strip().lower() == "stop"

    async def _try_lead_stop(self, tenant: TenantContext, room: str, message: MessageRead) -> bool:
        """Lead `stop` cancels think/quality/ask, not only an open /prd-ask wait."""
        if not self._is_lead_stop(message):
            return False
        if not self._tenant_has_open_work(tenant.slug) and tenant.slug not in self._outline_tasks:
            return False
        await self._halt_programme(tenant, room)
        return True

    async def _halt_programme(self, tenant: TenantContext, room: str) -> None:
        initiative = self._open_initiative.get(tenant.slug) or "(none)"
        task = self._outline_tasks.pop(tenant.slug, None)
        if task is not None and not task.done():
            task.cancel()
        event = self._ask_events.get(tenant.slug)
        if event is not None:
            self._ask_answers[tenant.slug] = {"_skip": "stop"}
            event.set()
        prefix = f"{tenant.slug}:"
        for token in list(self._inflight):
            if token.startswith(prefix):
                fingerprint = token[len(prefix) :]
                await self._release_outline(tenant.slug, fingerprint)
        await self._clear_pending_init(tenant.slug)
        await self._clear_pending_ask(tenant.slug)
        await self._clear_pending_recommend(tenant.slug)
        await self._status(
            room,
            self._copy("hermes.pm.status.lead-stopped", {"initiative": initiative}),
            EventType.STALL,
            {
                "lane": "pm",
                "hop": "loop",
                "status": "stopped",
                "initiative": initiative,
                "programme_slug": tenant.slug,
            },
        )
        self.logger.info("PM walk stopped by Lead", slug=tenant.slug, initiative=initiative)

    def _tenant_has_open_work(self, slug: str) -> bool:
        if any(token.startswith(f"{slug}:") for token in self._inflight):
            return True
        return (
            slug in self._awaiting_init
            or slug in self._awaiting_ask
            or slug in self._awaiting_recommend
        )

    def _pending_ask_key(self, slug: str) -> str:
        return pm_pending.pending_ask_key(slug)

    def _pending_recommend_key(self, slug: str) -> str:
        return pm_pending.pending_recommend_key(slug)

    def _ask_pending_ttl(self) -> int:
        return pm_pending.ask_pending_ttl_seconds(
            ask_wait_seconds=float(self._settings.pm_ask_wait_seconds),
            outline_lock_seconds=int(self._settings.outline_lock_seconds),
            grace_seconds=int(self._settings.pm_ask_grace_seconds),
        )

    async def _store_pending_ask(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
        forks: list[Any],
    ) -> None:
        pending = {
            "room": room,
            "outline": outline,
            "initiative": initiative,
            "forks": forks,
            "think_paths": [str(_think_file_ref(item)["path"]) for item in thinks],
            "quality_path": str(quality.payload.get("path") or quality_path(initiative)),
        }
        self._awaiting_ask[tenant.slug] = pending
        try:
            await self._redis.set(
                self._pending_ask_key(tenant.slug),
                pending,
                self._ask_pending_ttl(),
            )
        except Exception:
            self.logger.exception("PM pending ask store failed", slug=tenant.slug)

    async def _load_pending_ask(self, slug: str) -> Optional[dict[str, Any]]:
        local = self._awaiting_ask.get(slug)
        if local:
            return local
        try:
            raw = await self._redis.get(self._pending_ask_key(slug), as_json=True)
        except Exception:
            self.logger.exception("PM pending ask load failed", slug=slug)
            return None
        if isinstance(raw, dict):
            self._awaiting_ask[slug] = raw
            return raw
        return None

    async def _clear_pending_ask(self, slug: str) -> None:
        self._awaiting_ask.pop(slug, None)
        self._ask_answers.pop(slug, None)
        try:
            await self._redis.delete(self._pending_ask_key(slug))
        except Exception:
            self.logger.exception("PM pending ask clear failed", slug=slug)

    async def _store_pending_recommend(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        pick: str,
        path: str,
        think_paths: Optional[list[str]] = None,
    ) -> None:
        pending = {
            "room": room,
            "initiative": initiative,
            "recommend": pick,
            "path": path,
            "think_paths": list(think_paths or []),
        }
        self._awaiting_recommend[tenant.slug] = pending
        try:
            await self._redis.set(
                self._pending_recommend_key(tenant.slug),
                pending,
                int(self._settings.outline_lock_seconds),
            )
        except Exception:
            self.logger.exception("PM pending recommend store failed", slug=tenant.slug)

    async def _load_pending_recommend(self, slug: str) -> Optional[dict[str, Any]]:
        local = self._awaiting_recommend.get(slug)
        if local:
            return local
        try:
            raw = await self._redis.get(self._pending_recommend_key(slug), as_json=True)
        except Exception:
            self.logger.exception("PM pending recommend load failed", slug=slug)
            return None
        if isinstance(raw, dict):
            self._awaiting_recommend[slug] = raw
            return raw
        return None

    async def _clear_pending_recommend(self, slug: str) -> None:
        self._awaiting_recommend.pop(slug, None)
        try:
            await self._redis.delete(self._pending_recommend_key(slug))
        except Exception:
            self.logger.exception("PM pending recommend clear failed", slug=slug)

    async def _wait_ask_answers(self, slug: str, timeout: float) -> dict[str, str]:
        event = asyncio.Event()
        self._ask_events[slug] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return dict(self._ask_answers.get(slug) or {})
        except asyncio.TimeoutError:
            return {}
        finally:
            self._ask_events.pop(slug, None)

    async def _try_ask_answer(self, tenant: TenantContext, room: str, message: MessageRead) -> bool:
        if not self._is_lead_text(message):
            return False
        pending = await self._load_pending_ask(tenant.slug)
        if pending is None:
            return False
        if str(pending.get("room") or room) != room:
            return False
        answers = parse_ask_answers(message.body)
        if answers is None:
            self.logger.info(
                "Ignored Lead chatter while /prd-ask is open",
                slug=tenant.slug,
            )
            return True
        if answers.get("_invalid"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-invalid",
                    {
                        "initiative": str(pending.get("initiative") or ""),
                        "reason": str(answers.get("_invalid")),
                    },
                ),
                EventType.STALL,
                {
                    "status": "ask_invalid",
                    "hop": "ask",
                    "reason": answers.get("_invalid"),
                    "initiative": pending.get("initiative"),
                    "programme_slug": tenant.slug,
                },
            )
            return True
        mismatch = validate_ask_answers(answers, list(pending.get("forks") or []))
        if mismatch:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-invalid",
                    {
                        "initiative": str(pending.get("initiative") or ""),
                        "reason": mismatch,
                    },
                ),
                EventType.STALL,
                {
                    "status": "ask_invalid",
                    "hop": "ask",
                    "reason": mismatch,
                    "initiative": pending.get("initiative"),
                    "programme_slug": tenant.slug,
                },
            )
            return True
        self._ask_answers[tenant.slug] = answers
        event = self._ask_events.get(tenant.slug)
        if event is not None:
            event.set()
            return True
        task = asyncio.create_task(self._continue_from_pending_ask(tenant, pending, answers))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)
        return True

    async def _try_promote_pick(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        if not self._is_lead_text(message):
            return False
        # A6: while ask is open, promote tokens are chatter (ask handler already claimed).
        if await self._load_pending_ask(tenant.slug) is not None:
            return False
        pick = parse_promote_pick(message.body)
        pending = await self._load_pending_recommend(tenant.slug)
        if pending is None:
            if pick is None or pick in {"none", "iterate", "skip"}:
                return False
            return await self._promote_recovery(tenant, room, pick)
        if str(pending.get("room") or room) != room:
            return False
        if pick is None:
            self.logger.info(
                "Ignored Lead chatter while /prd-recommend is open",
                slug=tenant.slug,
            )
            return True
        initiative = str(pending.get("initiative") or "")
        if pick in {"none", "iterate", "skip"}:
            await self._clear_pending_recommend(tenant.slug)
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.promote-skip",
                    {"initiative": initiative, "pick": pick},
                ),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_skip",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return True
        await self._promote_copy(
            tenant,
            room,
            initiative=initiative,
            pick=pick,
            preferred_path=str(pending.get("path") or ""),
            think_paths=list(pending.get("think_paths") or []),
        )
        await self._clear_pending_recommend(tenant.slug)
        return True

    async def _promote_recovery(self, tenant: TenantContext, room: str, pick: str) -> bool:
        """A7: promote when quality exists, PRD missing, even without awaiting-recommend."""
        listing = self._workspace.inventory(tenant)
        initiative = self._open_initiative.get(tenant.slug) or ""
        if not initiative and "prd/reports/" in pick.replace("\\", "/"):
            stem = Path(pick.replace("\\", "/")).name
            if stem.upper().endswith("-PRD-THINK.MD"):
                initiative = stem[: -len("-prd-think.md")]
            else:
                match = re.match(r"^(INIT-.+)-prd-think-\d+\.md$", stem, re.I)
                if match:
                    initiative = match.group(1)
        if not initiative and re.fullmatch(r"C\d+", pick, re.I):
            candidates: list[str] = []
            for init in listing.inits:
                qbody = self._workspace.read_local(tenant, quality_path(init))
                if not qbody.strip():
                    continue
                if self._workspace.read_local(tenant, prd_path(init)).strip():
                    continue
                candidates.append(init)
            if len(candidates) == 1:
                initiative = candidates[0]
        if not initiative:
            return False
        qpath = quality_path(initiative)
        if not self._workspace.read_local(tenant, qpath).strip():
            return False
        dest = prd_path(initiative)
        if self._workspace.read_local(tenant, dest).strip():
            await self._status(
                room,
                self._copy("hermes.pm.status.promote-already", {"initiative": initiative}),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_already",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return True
        think_paths = [
            path
            for path in listing.think_paths
            if path.startswith(f"prd/reports/{initiative}-prd-think")
        ]
        await self._promote_copy(
            tenant,
            room,
            initiative=initiative,
            pick=pick,
            preferred_path="",
            think_paths=think_paths,
        )
        return True

    async def _promote_copy(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        pick: str,
        preferred_path: str,
        think_paths: list[Any],
    ) -> None:
        dest = prd_path(initiative)
        if self._workspace.read_local(tenant, dest).strip():
            await self._status(
                room,
                self._copy("hermes.pm.status.promote-already", {"initiative": initiative}),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_already",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return
        source = self._resolve_promote_source(pick, preferred_path, think_paths)
        if not source:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.promote-unknown",
                    {"initiative": initiative, "pick": pick},
                ),
                EventType.STALL,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_unknown",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return
        body = self._workspace.read_local(tenant, source)
        if not body.strip():
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.promote-unknown",
                    {"initiative": initiative, "pick": pick},
                ),
                EventType.STALL,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_unknown",
                    "pick": pick,
                    "path": source,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return
        result = await self._workspace.publish(
            tenant,
            dest,
            body,
            f"docs({initiative}): promote {pick} → prd",
        )
        local = result.get("local_path") or "skipped"
        github = result.get("github") or {}
        sha = ""
        if isinstance(github, dict):
            sha = str(github.get("commit_sha") or github.get("sha") or "")
        github_state = f"committed {sha[:7]}" if sha else "skipped"
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.promote-noted",
                {
                    "initiative": initiative,
                    "pick": pick,
                    "path": source,
                    "local": local,
                    "github_state": github_state,
                },
            ),
            EventType.PROGRESS,
            {
                "lane": "pm",
                "hop": "promote",
                "status": "promote_copied",
                "pick": pick,
                "source_path": source,
                "path": dest,
                "initiative": initiative,
                "programme_slug": tenant.slug,
                "publish": result,
            },
        )
        self.logger.info(
            "Promoted think file to PRD; Forge is not drafting; validate not started",
            slug=tenant.slug,
            pick=pick,
            initiative=initiative,
            source=source,
            dest=dest,
        )

    def _resolve_promote_source(
        self,
        pick: str,
        preferred_path: str,
        think_paths: list[Any],
    ) -> str:
        paths = [str(item) for item in think_paths if str(item or "").strip()]
        normalized = pick.replace("\\", "/")
        if "prd/reports/" in normalized and normalized.lower().endswith(".md"):
            return pick
        if re.fullmatch(r"C\d+", pick, re.I):
            index = int(pick[1:])
            if 1 <= index <= len(paths):
                return paths[index - 1]
            if preferred_path:
                return preferred_path
            return ""
        return preferred_path or ""

    async def _resume_pending_ask(self, tenant: TenantContext) -> None:
        pending = await self._load_pending_ask(tenant.slug)
        if pending is None:
            return
        if tenant.slug in self._ask_events:
            return
        room = str(pending.get("room") or tenant.ops_room)
        initiative = str(pending.get("initiative") or "")
        forks = list(pending.get("forks") or [])
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-resume",
                {"initiative": initiative},
            ),
            EventType.PROGRESS,
            {
                "lane": "pm",
                "hop": "ask",
                "status": "need_ask",
                "initiative": initiative,
                "programme_slug": tenant.slug,
                "choices": forks,
            },
        )
        if forks:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-card",
                    {
                        "initiative": initiative,
                        "fork_block": _format_fork_block(forks),
                    },
                ),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "ask",
                    "status": "need_ask",
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                    "choices": forks,
                },
            )
        task = asyncio.create_task(self._wait_then_continue_ask(tenant, pending))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    async def _wait_then_continue_ask(self, tenant: TenantContext, pending: dict[str, Any]) -> None:
        timeout = float(self._settings.pm_ask_wait_seconds)
        if timeout <= 0:
            answers: dict[str, str] = {}
        else:
            answers = await self._wait_ask_answers(tenant.slug, timeout)
        await self._continue_from_pending_ask(tenant, pending, answers)

    async def _continue_from_pending_ask(
        self,
        tenant: TenantContext,
        pending: dict[str, Any],
        answers: dict[str, str],
    ) -> None:
        await self._clear_pending_ask(tenant.slug)
        room = str(pending.get("room") or tenant.ops_room)
        initiative = str(pending.get("initiative") or "")
        outline = str(pending.get("outline") or "")
        if answers.get("_skip") == "stop":
            await self._status(
                room,
                self._copy("hermes.pm.status.ask-stopped", {"initiative": initiative}),
                EventType.STALL,
                {"status": "stopped", "hop": "ask", "initiative": initiative},
            )
            return
        thinks = self._thinks_from_paths(tenant, initiative, pending.get("think_paths") or [])
        qpath = str(pending.get("quality_path") or quality_path(initiative))
        qbody = self._workspace.read_local(tenant, qpath)
        quality = HermesArtifactRead(
            kind="pm_quality",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            body=qbody,
            payload={"path": qpath, "file_body": qbody, "artifact": {}, "hop": "quality"},
        )
        ask_body = self._workspace.read_local(tenant, ask_path(initiative))
        ask = HermesArtifactRead(
            kind="pm_ask",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            body=ask_body,
            payload={
                "path": ask_path(initiative),
                "file_body": ask_body,
                "artifact": {"forks": pending.get("forks") or []},
                "hop": "ask",
            },
        )
        meta = {
            "initiative": initiative,
            "programme_slug": tenant.slug,
            "hop": "recommend",
            "status": "in_progress",
        }
        if not answers or answers.get("_skip"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-timeout-provisional",
                    {"initiative": initiative},
                ),
                EventType.PROGRESS,
                {**meta, "hop": "ask", "status": "provisional"},
            )
        await self._recommend_pass(
            tenant,
            room,
            outline,
            initiative,
            None,
            meta,
            thinks,
            quality,
            ask,
            answers,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.promote-is-you", {"initiative": initiative}),
            EventType.DONE,
            {**meta, "status": "done", "hop": "recommend"},
        )

    def _thinks_from_paths(
        self, tenant: TenantContext, initiative: str, paths: list[Any]
    ) -> list[HermesArtifactRead]:
        thinks: list[HermesArtifactRead] = []
        for index, raw in enumerate(paths, start=1):
            path = str(raw or "")
            if not path:
                continue
            body = self._workspace.read_local(tenant, path)
            if not body.strip():
                continue
            label = f"C{index}"
            thinks.append(
                HermesArtifactRead(
                    kind=f"pm_think_{label.lower()}",
                    initiative=initiative,
                    rubric_id=RUBRIC_PM["id"],
                    body=body[:500],
                    payload={
                        "path": path,
                        "file_body": body,
                        "artifact": {"candidate_label": label},
                        "hop": f"think-{label.lower()}",
                    },
                )
            )
        return thinks

    def _is_lead_outline(self, message: MessageRead) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        handle = message.identity_handle or ""
        if handle != self._settings.lead_handle:
            return False
        return is_lead_outline_body(
            message.body or "",
            min_chars=int(self._settings.outline_min_chars),
        )

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
        return pm_pending.pending_init_key(slug)

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
        self._track_outline_task(
            tenant.slug,
            asyncio.create_task(
                self._run_outline_work(
                    tenant,
                    room,
                    outline,
                    fingerprint,
                    source_id,
                    source_uuid,
                    initiative=initiative,
                )
            ),
        )

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

    def _track_outline_task(self, slug: str, task: asyncio.Task[None]) -> None:
        self._outline_tasks[slug] = task
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

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

    async def _apply_quality_card(
        self,
        initiative: str,
        parsed: dict[str, Any],
        files: list[dict[str, str]],
        outline: str,
        model: str,
    ) -> dict[str, Any]:
        """LLM memo for the human PM. Frozen scores. No programme-specific rewrite."""
        card = await self._prompts.complete(
            "hermes.pm.quality.card",
            {
                "initiative": initiative,
                "outline": (outline or "").strip() or "(none)",
                "scorecard": json.dumps(_scorecard_for_card(parsed), ensure_ascii=False),
                "files": _format_ready_files(files),
                "max_questions": 3,
            },
            model=model,
        )
        if not quality_card_has_signal(card.parsed):
            raise TimeoutError(
                self._copy("hermes.pm.error.quality-card", {"initiative": initiative})
            )
        merged = apply_quality_card(parsed, dict(card.parsed))
        self.logger.info(
            "Hermes quality card applied",
            initiative=initiative,
            questions=len(merged.get("lead_questions") or []),
            model=card.model,
        )
        return merged

    async def _apply_ask_card(
        self,
        initiative: str,
        parsed: dict[str, Any],
        files: list[dict[str, str]],
        outline: str,
        model: str,
    ) -> dict[str, Any]:
        """LLM decision aid on frozen forks. Does not change questions or choice strings."""
        try:
            card = await self._prompts.complete(
                "hermes.pm.ask.card",
                {
                    "initiative": initiative,
                    "outline": (outline or "").strip() or "(none)",
                    "forks": json.dumps(
                        [
                            {
                                "id": fork.get("id"),
                                "question": fork.get("question"),
                                "choices": fork.get("choices") or [],
                            }
                            for fork in parsed.get("forks") or []
                            if isinstance(fork, dict)
                        ],
                        ensure_ascii=False,
                    ),
                    "files": _format_ready_files(files),
                },
                model=model,
            )
        except Exception:
            self.logger.exception("Hermes ask card failed", initiative=initiative)
            return parsed
        if not ask_card_has_signal(card.parsed):
            self.logger.warning("Hermes ask card returned no examples", initiative=initiative)
            return parsed
        merged = apply_ask_card(parsed, dict(card.parsed))
        self.logger.info(
            "Hermes ask card applied",
            initiative=initiative,
            forks=len(merged.get("forks") or []),
            model=card.model,
        )
        return merged

    def _render_quality_hop_body(
        self,
        initiative: str,
        parsed: dict[str, Any],
        model: str,
        pass_number: int = 1,
        max_passes: int = 2,
        path: str = "",
    ) -> str:
        return self._copy(
            "hermes.pm.hop.quality",
            _quality_copy_vars(
                initiative, parsed, path or quality_path(initiative), model, pass_number, max_passes
            ),
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
            str(artifact.payload.get("path") or quality_path(artifact.initiative)),
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
        return self._copy(
            "hermes.pm.file.quality",
            _quality_copy_vars(initiative, parsed, path, model, pass_number, max_passes),
        )

    def _render_ask_hop_body(self, initiative: str, parsed: dict[str, Any], model: str) -> str:
        forks = parsed.get("forks") or []
        return self._copy(
            "hermes.pm.hop.ask",
            {
                "initiative": initiative,
                "model": model,
                "fork_count": len(forks),
                "fork_block": _format_fork_block(forks),
                "notes": parsed.get("notes") or "(none)",
            },
        )

    def _render_ask_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        return self._render_ask_hop_body(artifact.initiative, parsed, model)

    def _render_ask_file(self, initiative: str, parsed: dict[str, Any], path: str) -> str:
        forks = parsed.get("forks") or []
        return self._copy(
            "hermes.pm.file.ask",
            {
                "initiative": initiative,
                "path": path,
                "fork_count": len(forks),
                "fork_block": _format_fork_block(forks),
                "notes": parsed.get("notes") or "(none)",
            },
        )

    def _render_recommend_hop_body(
        self, initiative: str, parsed: dict[str, Any], model: str
    ) -> str:
        return self._copy(
            "hermes.pm.hop.recommend",
            {
                "initiative": initiative,
                "model": model,
                "recommend": parsed.get("recommend") or "none",
                "engineering_ready": parsed.get("engineering_ready") or "no",
                "path": parsed.get("path") or "(none)",
                "why": parsed.get("why") or "(none)",
                "why_not": _format_why_not(parsed.get("why_not") or []),
                "residual_locks": _bullets(parsed.get("residual_locks")),
                "notes": parsed.get("notes") or "(none)",
            },
        )

    def _render_recommend_hop(self, artifact: HermesArtifactRead) -> str:
        parsed = dict(artifact.payload.get("artifact") or {})
        model = str(artifact.payload.get("model") or artifact.model or "unresolved")
        return self._render_recommend_hop_body(artifact.initiative, parsed, model)

    def _render_recommend_file(self, initiative: str, parsed: dict[str, Any], path: str) -> str:
        return self._copy(
            "hermes.pm.file.recommend",
            {
                "initiative": initiative,
                "recommend": parsed.get("recommend") or "none",
                "path": parsed.get("path") or "(none)",
                "engineering_ready": parsed.get("engineering_ready") or "no",
                "file_path": path,
                "why": parsed.get("why") or "(none)",
                "why_not": _format_why_not(parsed.get("why_not") or []),
                "residual_locks": _bullets(parsed.get("residual_locks")),
                "notes": parsed.get("notes") or "(none)",
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
