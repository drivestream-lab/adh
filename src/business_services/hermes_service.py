"""Hermes: PM lane + after-PR verify/grade/RCA. Does not merge."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.business_services.hermes.gates import _as_float_map
from src.business_services.hermes.lead_tokens import (
    is_lead_outline_body,
    lock_token as _lock_token,
    outline_fingerprint,
)
from src.business_services.hermes.pending import PendingMixin
from src.business_services.hermes.programmes.authoring_programme import (
    AuthoringProgrammeService,
)
from src.business_services.hermes.programmes.meta_pm_programme import MetaPmProgrammeService
from src.business_services.hermes.render_pm import RenderPmMixin
from src.business_services.hermes.runtime.orchestrator_service import HermesCollaboratorService
from src.configs.hermes_settings import HermesSettings
from src.configs.rubrics import RUBRIC_ENG, RUBRIC_PM, weighted_overall
from src.infra_services.hermes_store_service import HermesStoreService
from src.infra_services.pm_skill_runner_service import PmSkillRunnerService
from src.infra_services.pm_workspace_service import PmWorkspaceService
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
from src.models.tenant_models import (
    GLOBAL_MEMORY_ROOM,
    GLOBAL_REPO,
    MEMORY_SCOPE_GLOBAL,
    TenantContext,
    knowledge_scope_key,
    memory_room_for_repo,
)


class HermesService(
    PendingMixin,
    RenderPmMixin,
    BaseBusinessService,
):
    """Buzz listener: catalogue collaborator + skill-backed authoring + eng grade."""

    @inject
    def __init__(
        self,
        store: HermesStoreService,
        buzz: BuzzService,
        redis: RedisService,
        prompts: PromptService,
        workspace: PmWorkspaceService,
        tenants: TenantRegistryService,
        skill_runner: PmSkillRunnerService,
        collaborator: HermesCollaboratorService,
        meta_pm: MetaPmProgrammeService,
        authoring: AuthoringProgrammeService,
    ) -> None:
        super().__init__()
        self._store = store
        self._buzz = buzz
        self._redis = redis
        self._prompts = prompts
        self._workspace = workspace
        self._tenants = tenants
        self._skill_runner = skill_runner
        self._collaborator = collaborator
        self._meta_pm = meta_pm
        self._authoring = authoring
        self._settings = HermesSettings.get_instance()
        self._boot_task: Optional[asyncio.Task[None]] = None
        self._work_tasks: set[asyncio.Task[None]] = set()
        self._inflight: dict[str, str] = {}
        self._outline_tasks: dict[str, asyncio.Task[None]] = {}
        self._open_initiative: dict[str, str] = {}

    async def initialize(self) -> None:
        await super().initialize()
        self._collaborator.set_programme_runner(self._meta_pm)
        # Ops listen lives on PMAgent (BaseHermesAgent) — Wave 0a Phase1 #3A.
        if self._settings.listen_ops:
            self.logger.info(
                "HermesService listen_ops ignored; PMAgent owns tenant ops listen",
            )
        if self._settings.run_boot_jobs:
            self._boot_task = asyncio.create_task(self._boot_jobs())
            self.logger.info("Hermes boot jobs scheduled")

    async def close(self) -> None:
        tasks = [self._boot_task, *self._work_tasks]
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
        # Wave 0a: post briefs on ops only (Buzz memory rooms retired).
        posted = await self._post(
            self._settings.ops_room,
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

    async def list_ledger(self) -> list[HermesArtifactRead]:
        return await self._store.list_ledger()

    async def on_room_message(self, room: str, message: MessageRead) -> None:
        """Collaborator (meta-pm) → authoring (promote/init) → new outline."""
        tenant = self._tenants.by_ops_room(room)
        if tenant is None:
            return
        if await self._try_lead_stop(tenant, room, message):
            return
        if self._is_lead_text(message) and await self._collaborator.handle_lead_message(
            tenant, room, message
        ):
            return
        if await self._authoring.handle_lead_message(tenant, room, message):
            return
        if not self._is_lead_outline(message):
            return
        fingerprint = outline_fingerprint(message.body)
        # Parallel initiatives allowed: only the same outline fingerprint is a duplicate.
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
        source_id = str(message.id) if message.id else ""
        claimed = await self._claim_outline(tenant.slug, fingerprint, source_id)
        if not claimed:
            await self._status(
                room,
                self._copy("hermes.pm.status.duplicate"),
                EventType.STALL,
                {
                    "status": "duplicate",
                    "outline_fingerprint": fingerprint,
                    "programme_slug": tenant.slug,
                    "source_message_id": source_id,
                },
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

        async def _run() -> None:
            try:
                await self._authoring.start_outline(
                    tenant,
                    room,
                    message.body,
                    fingerprint=fingerprint,
                    source_id=source_id,
                    source_message_id=message.id,
                )
            finally:
                await self._release_outline(tenant.slug, fingerprint)

        self._track_outline_task(tenant.slug, fingerprint, asyncio.create_task(_run()))

    async def catch_up_ops(self, room: str) -> None:
        """Public for PMAgent boot — replay recent unacked Lead outlines.

        Skip when any initiative session is already active so catch-up cannot
        mint INIT-N+1 over an open authoring/meta-pm gate (parallel pressure-test).
        """
        tenant = self._tenants.by_ops_room(room)
        if tenant is not None:
            store = getattr(self._collaborator, "_store", None)
            has_active = getattr(store, "has_active", None) if store is not None else None
            if has_active is not None and await has_active(tenant.slug):
                self.logger.info(
                    "catch_up_ops skipped — active Hermes sessions present",
                    room=room,
                    slug=tenant.slug,
                )
                return
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

    def _is_lead_text(self, message: MessageRead) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        return (message.identity_handle or "") == self._settings.lead_handle

    def _is_lead_outline(self, message: MessageRead) -> bool:
        if not self._is_lead_text(message):
            return False
        return is_lead_outline_body(message.body, min_chars=int(self._settings.outline_min_chars))

    def _track_outline_task(self, slug: str, fingerprint: str, task: asyncio.Task[None]) -> None:
        key = f"{slug}:{fingerprint}"
        prior = self._outline_tasks.pop(key, None)
        if prior is not None and not prior.done():
            prior.cancel()
        self._outline_tasks[key] = task

        def _done(done: asyncio.Task[None]) -> None:
            if self._outline_tasks.get(key) is done:
                self._outline_tasks.pop(key, None)

        task.add_done_callback(_done)

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
        # Mid-lane hops stay local; forge owns authorized remote GitHub writes.
        result = self._workspace.write_local(tenant, path, contents)
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
