"""Hermes: PM lane + after-PR verify/grade/RCA. Does not merge."""

import asyncio
from typing import Any, Optional
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.configs.rubrics import RUBRIC_ENG, RUBRIC_PM, weighted_overall
from src.infra_services.hermes_store_service import HermesStoreService
from src.infra_services.litellm_service import LiteLLMService
from src.models.buzz_models import EventType, HeartbeatIngest, MessageCreate, MessageKind
from src.models.hermes_models import HermesArtifactRead, HermesBriefRequest, HermesGradeRequest

_PRD_STUB = """
INIT-ADH-000 G0. GitHub PRs are delivery. Buzz is the only conversation plane.
Hermes is PO (PM lane) and after-PR verify/grade/RCA. Cursor CLI is the implementer.
Merge = verify green + rubric-eng >= 2.7 + no blockers. Hermes cannot edit X.
Lead nikd10x merges. Agents are GitHub Apps. Proof tenant is forked RealWorld (Phase G).
G0 kill: backend App PR on api only; cannot push web; cannot merge; checkpoint stop;
every step visible on Buzz.
""".strip()

_PM_SYSTEM = """You are Hermes, the programme PO. Return JSON only with keys:
summary (string), journeys (array of strings), reqs_covered (array of strings),
findings (array of {lane, text}), citations (array of strings),
scores (object mapping citation,journeys,req_coverage,findings_quality to 0-3 numbers).
Cite INIT-ADH-000, P-/R- ids, or Buzz rooms. Do not recommend merging code.
"""

_ENG_SYSTEM = """You are Hermes, engineering reviewer after a PR. Return JSON only with keys:
scores (object mapping process_integrity,spec_fidelity,verify,knowledge,harness_hygiene to 0-3),
notes (string), rca (string or null), harness_proposal (string or null).
process_integrity 0 is a hard fail. You do not merge. This fixture has no product tree.
"""


class HermesService(BaseBusinessService):
    """Autonomous LLM brain. Writes Buzz + hermes memory + ledger. Never merges."""

    @inject
    def __init__(
        self,
        litellm: LiteLLMService,
        store: HermesStoreService,
        buzz: BuzzService,
    ) -> None:
        super().__init__()
        self._litellm = litellm
        self._store = store
        self._buzz = buzz
        self._settings = HermesSettings.get_instance()
        self._boot_task: Optional[asyncio.Task[None]] = None

    async def initialize(self) -> None:
        await super().initialize()
        if self._settings.run_boot_jobs:
            self._boot_task = asyncio.create_task(self._boot_jobs())
            self.logger.info("Hermes boot jobs scheduled")

    async def close(self) -> None:
        if self._boot_task is not None:
            self._boot_task.cancel()
            try:
                await self._boot_task
            except asyncio.CancelledError:
                pass
            self._boot_task = None
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
        await self._heartbeat("adh.pm", "PM brief start", EventType.START)
        user = (
            f"Initiative {initiative}. Rubric-pm dimensions {list(RUBRIC_PM['dimensions'])}.\n"
            f"PRD stub:\n{_PRD_STUB}"
        )
        parsed, raw, model = await self._complete(_PM_SYSTEM, user)
        scores = _as_float_map(parsed.get("scores"))
        overall = weighted_overall(scores, RUBRIC_PM)
        body = _format_brief(initiative, parsed, overall, model)
        payload = {
            "lane": "pm",
            "initiative": initiative,
            "rubric": RUBRIC_PM["id"],
            "overall": overall,
            "threshold_x": RUBRIC_PM["threshold_x"],
            "scores": scores,
            "model": model,
            "artifact": parsed,
            "raw": raw[:4000],
        }
        posted = await self._post(
            self._settings.memory_room,
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
        )
        await self._heartbeat("adh.pm", "PM brief done", EventType.DONE)
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
        await self._heartbeat("adh.reviewer", "after-PR grade start", EventType.START)
        user = (
            f"PR {request.pr_ref}. verify_exit={request.verify_exit}. notes={request.notes}. "
            f"Rubric-eng X={self._settings.threshold_x}. Dimensions {list(RUBRIC_ENG['dimensions'])}."
        )
        parsed, raw, model = await self._complete(_ENG_SYSTEM, user)
        scores = _as_float_map(parsed.get("scores"))
        if request.verify_exit != 0:
            scores["verify"] = 0.0
        overall = weighted_overall(scores, RUBRIC_ENG)
        process = scores.get("process_integrity", 0.0)
        recommend = (
            request.verify_exit == 0 and process > 0 and overall >= self._settings.threshold_x
        )
        body = _format_grade(request, parsed, overall, recommend, model)
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
            knowledge_key=key,
        )
        await self._heartbeat("adh.reviewer", "after-PR grade done", EventType.DONE)
        return artifact

    async def list_ledger(self) -> list[HermesArtifactRead]:
        return await self._store.list_ledger()

    async def _complete(self, system: str, user: str) -> tuple[dict[str, Any], str, str]:
        try:
            parsed, raw = await self._litellm.complete_json(system, user)
            return parsed, raw, self._settings.model
        except Exception as exc:
            self.logger.warning("LiteLLM call failed; writing deterministic stub", error=str(exc))
            return (
                {
                    "summary": "LiteLLM unavailable; stub brief/grade for local boot.",
                    "journeys": ["Lead watches Buzz", "Hermes posts artifacts"],
                    "reqs_covered": ["R-2 Buzz plane", "R-9 PM lane", "R-10 after-PR"],
                    "findings": [{"lane": "eng", "text": f"LLM error: {exc}"}],
                    "citations": ["INIT-ADH-000", "#adh-memory"],
                    "scores": {
                        "citation": 2.0,
                        "journeys": 2.0,
                        "req_coverage": 2.0,
                        "findings_quality": 1.0,
                        "process_integrity": 2.0,
                        "spec_fidelity": 1.0,
                        "verify": 1.0,
                        "knowledge": 2.0,
                        "harness_hygiene": 2.0,
                    },
                    "notes": str(exc),
                    "rca": "LiteLLM did not return JSON; stub recorded so Buzz/ledger still land.",
                    "harness_proposal": None,
                },
                str(exc),
                "stub",
            )

    async def _heartbeat(self, handle: str, body: str, event: EventType) -> None:
        try:
            await self._buzz.ingest_heartbeat(
                HeartbeatIngest(
                    identity_handle=handle,
                    room_slug=self._settings.ops_room,
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
    ) -> Any:
        return await self._buzz.post_message(
            room,
            MessageCreate(
                identity_handle=handle,
                body=body,
                kind=MessageKind.EVENT,
                event_type=EventType.DONE,
                payload=payload,
            ),
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
        knowledge_key: Optional[str] = None,
    ) -> HermesArtifactRead:
        await self._store.save_memory(
            kind=kind,
            initiative=initiative,
            body=body,
            payload=payload,
            source_buzz_id=buzz_id,
        )
        await self._store.save_knowledge(
            lane=lane,
            dimension=dimension,
            key=knowledge_key or f"{kind}:{initiative}",
            body=body,
            payload=payload,
            source_buzz_id=buzz_id,
        )
        return await self._store.save_ledger(
            kind=kind,
            initiative=initiative,
            rubric_id=rubric_id,
            overall=overall,
            recommend_merge=recommend_merge,
            body=body,
            payload=payload,
            buzz_message_id=buzz_id,
        )


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


def _format_brief(initiative: str, parsed: dict[str, Any], overall: float, model: str) -> str:
    summary = str(parsed.get("summary") or "PM brief")
    return f"PM brief {initiative} (rubric-pm overall {overall}/3, model={model})\n\n{summary}"


def _format_grade(
    request: HermesGradeRequest,
    parsed: dict[str, Any],
    overall: float,
    recommend: bool,
    model: str,
) -> str:
    notes = str(parsed.get("notes") or parsed.get("rca") or "grade recorded")
    merge = "recommend merge" if recommend else "do not merge"
    return (
        f"ENG grade {request.pr_ref} verify_exit={request.verify_exit} "
        f"overall={overall}/3 X=2.7 {merge} (model={model})\n\n{notes}"
    )
