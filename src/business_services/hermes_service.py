"""Hermes: PM lane + after-PR verify/grade/RCA. Does not merge."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.business_services.hermes.cards import (  # noqa: F401
    apply_ask_card,
    apply_quality_card,
)
from src.business_services.hermes.gates import (  # noqa: F401
    _as_float_map,
    apply_ready_gate,
    apply_recommend_gate,
)
from src.business_services.hermes.lead_tokens import (  # noqa: F401
    _coerce_init,
    lock_token as _lock_token,
    outline_fingerprint,
    parse_ask_answers,
    parse_promote_pick,
)
from src.business_services.hermes.pending import PendingMixin
from src.business_services.hermes.pre_promote_walk import PrePromoteWalkMixin
from src.business_services.hermes.render_pm import (
    RenderPmMixin,
    _format_ready_files,
)
from src.configs.hermes_settings import HermesSettings
from src.configs.rubrics import RUBRIC_ENG, RUBRIC_PM, weighted_overall
from src.infra_services.hermes_store_service import HermesStoreService
from src.infra_services.pm_workspace_service import (
    PmWorkspaceService,
    ask_path,
    quality_path,
    recommend_path,
    think_path,
)
from src.infra_services.prompt_service import PromptService
from src.infra_services.redis_service import RedisService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import (
    EventType,
    HeartbeatIngest,
    MessageCreate,
    MessageKind,
    MessageRead,
)
from src.models.hermes_models import HermesArtifactRead, HermesBriefRequest, HermesGradeRequest
from src.models.prompt_models import (
    cap_ask_forks,
    quality_has_signal,
)
from src.models.tenant_models import (
    GLOBAL_MEMORY_ROOM,
    GLOBAL_REPO,
    MEMORY_SCOPE_GLOBAL,
    MEMORY_SCOPE_REPO,
    TenantContext,
    knowledge_scope_key,
    memory_room_for_repo,
)


class HermesService(PrePromoteWalkMixin, PendingMixin, RenderPmMixin, BaseBusinessService):
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
