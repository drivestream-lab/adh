"""Hermes collaborator — session store, navigator, briefs, and Lead message flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.runtime.navigator_service import HermesNavigatorService
from src.business_services.hermes.runtime.orchestrator_service import (
    HermesCollaboratorService,
    match_reply_token,
)
from src.business_services.hermes.runtime.session_store import (
    HermesSessionStoreService,
    session_key,
)
from src.business_services.hermes.understanding.understand_service import (
    HermesUnderstandService,
)
from src.exceptions.app_exceptions import ValidationError
from src.models.buzz_models import EventType, MessageRead
from src.models.hermes.catalogue_models import CatalogueSnapshot
from src.models.hermes.execution_models import ForgeActionResult
from src.models.hermes.session_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_CLARIFY,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    HermesProgrammeType,
    HermesSession,
)
from src.models.tenant_models import TenantContext
from tests.unit.test_workflow_catalogue import _mini_snapshot


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, Optional[int]] = {}

    async def get(self, key: str, as_json: bool = False) -> Any:
        raw = self.data.get(key)
        if raw is not None and as_json:
            return json.loads(raw)
        return raw

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        self.data[key] = value if isinstance(value, str) else json.dumps(value)
        self.ttls[key] = ttl
        return True

    async def delete(self, key: str) -> int:
        self.ttls.pop(key, None)
        return 1 if self.data.pop(key, None) is not None else 0


class _FakeCatalogue:
    def __init__(self, snap: CatalogueSnapshot) -> None:
        self._snap = snap

    def snapshot(self) -> CatalogueSnapshot:
        return self._snap


class _FakePoster:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def post_status(
        self,
        room: str,
        body: str,
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self.posts.append(body)


class _FakeDispatch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_external_action(self, tenant: Any, node: Any, initiative: str, **kw: Any):
        assert kw["authorized"] is True
        self.calls.append(node.node_id)
        return ForgeActionResult(
            action=node.forge.action, repo="meta", pr_number=7, url="https://x/pull/7"
        )


class _FakeRunner:
    def __init__(self) -> None:
        self.started: list[HermesSession] = []
        self.judgments: list[str] = []

    async def start_programme(self, tenant: Any, room: str, session: HermesSession) -> None:
        self.started.append(session.model_copy())

    async def after_judgment(
        self, tenant: Any, room: str, session: HermesSession, token: str
    ) -> None:
        self.judgments.append(token)


_TENANT = TenantContext(
    slug="rw",
    org="drivestream-lab",
    meta_repo="rw-meta",
    meta_root="/tmp/rw-meta",
)
_ROOM = "rw-ops"


def _msg(body: str) -> MessageRead:
    return MessageRead.model_construct(body=body)


def _finding() -> dict[str, Any]:
    return {
        "id": "VF-01",
        "severity": "high",
        "question": "Should guests see drafts?",
        "example": "A guest opens a draft link.",
        "options": [
            {"choice": "fix", "means": "Change the PRD."},
            {"choice": "defer", "means": "Park it."},
        ],
        "recommend": "fix",
        "recommend_why": "Avoid guessing in spec-draft.",
    }


class _Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.snap = _mini_snapshot(tmp_path)
        cat = _FakeCatalogue(self.snap)
        self.redis = _FakeRedis()
        self.store = HermesSessionStoreService(redis=self.redis)  # type: ignore[arg-type]
        self.briefs = HermesBriefService()
        self.nav = HermesNavigatorService(catalogue=cat)  # type: ignore[arg-type]
        self.poster = _FakePoster()
        self.dispatch = _FakeDispatch()
        self.runner = _FakeRunner()
        self.collab = HermesCollaboratorService(
            store=self.store,
            understand=HermesUnderstandService(catalogue=cat),  # type: ignore[arg-type]
            briefs=self.briefs,
            navigator=self.nav,
            dispatch=self.dispatch,  # type: ignore[arg-type]
            poster=self.poster,  # type: ignore[arg-type]
        )
        self.collab.set_programme_runner(self.runner)


async def test_session_roundtrip_and_clear() -> None:
    redis = _FakeRedis()
    store = HermesSessionStoreService(redis=redis)  # type: ignore[arg-type]
    assert await store.load("rw") is None
    session = HermesSession(
        tenant_slug="rw", room=_ROOM, stage="validate-requirements", slots={"a": "b"}
    )
    await store.save(session)
    assert session_key("rw") == "adh:hermes:session:rw"
    assert redis.ttls[session_key("rw")] == 3600
    loaded = await store.load("rw")
    assert loaded is not None
    assert loaded.stage == "validate-requirements"
    assert loaded.slots == {"a": "b"}
    await store.clear("rw")
    assert await store.load("rw") is None


def test_session_awaiting_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        HermesSession(tenant_slug="rw", room=_ROOM, awaiting="bogus")


def test_navigator_advance_sets_awaiting(tmp_path: Path) -> None:
    nav = HermesNavigatorService(catalogue=_FakeCatalogue(_mini_snapshot(tmp_path)))  # type: ignore[arg-type]
    session = HermesSession(tenant_slug="rw", room=_ROOM, stage="validate-requirements")
    nxt = nav.advance(session, "pass")
    assert nxt.node_id == "prd-impact-map"
    assert session.stage == "prd-impact-map"
    assert session.awaiting == AWAITING_NONE

    nxt = nav.advance(session, "pass")
    assert nxt.node_id == "prd-pr-action"
    assert session.awaiting == AWAITING_AUTHORIZATION

    gate = HermesSession(tenant_slug="rw", room=_ROOM, stage="validate-requirements")
    nxt = nav.advance(gate, "needs-input")
    assert nxt.is_human_checkpoint()
    assert gate.awaiting == AWAITING_JUDGMENT
    assert nav.entrypoint_for("validate-requirements") == "meta-pm"
    assert nav.entrypoint_for("prd-impact-map") is None
    with pytest.raises(ValidationError):
        nav.advance(gate, "not-an-outcome")


def test_brief_reply_tokens_from_finding() -> None:
    briefs = HermesBriefService()
    brief = briefs.brief_from_validate_finding(_finding(), node_id="requirements-human-decision")
    assert brief.reply_tokens == ["VF-01: fix", "VF-01: defer"]
    assert brief.recommend == "fix"
    card = briefs.format_brief_markdown(brief)
    assert "`VF-01: fix`" in card
    assert "| `fix` ←" in card
    with pytest.raises(ValidationError):
        briefs.brief_from_validate_finding({"id": "VF-02"}, node_id="x")


def test_brief_authorization_uses_forge_action(tmp_path: Path) -> None:
    snap = _mini_snapshot(tmp_path)
    brief = HermesBriefService().brief_authorization(snap.node("prd-pr-action"), "INIT-RW-001")
    assert "open_draft_pr" in brief.question
    assert "go ahead" in brief.reply_tokens
    with pytest.raises(ValidationError):
        HermesBriefService().brief_authorization(snap.node("validate-requirements"), None)


def test_match_reply_token_exact_and_line_prefix() -> None:
    tokens = ["VF-01: fix", "VF-01: defer"]
    assert match_reply_token("vf-01: FIX", tokens) == "VF-01: fix"
    assert match_reply_token("thanks\nVF-01: defer because later", tokens) == "VF-01: defer"
    assert match_reply_token("fix it", tokens) is None


async def test_collaborator_defers_authoring_programme_sessions(tmp_path: Path) -> None:
    """Authoring owns promote briefs; collaborator must not record C-labels for them."""
    h = _Harness(tmp_path)
    brief = h.briefs.build_brief(
        purpose="authoring-promote",
        node_id="authoring-promote",
        question="Promote which think?",
        example="C2",
        options=["C1", "C2"],
        recommend="C2",
        recommend_why="quality",
        reply_tokens=["C1", "C2", "skip"],
        artefact_path="prd/reports/x-prd-quality.md",
    )
    await h.store.save(
        HermesSession(
            tenant_slug="rw",
            room=_ROOM,
            initiative="INIT-RW-001",
            programme=HermesProgrammeType.AUTHORING,
            stage="authoring-promote",
            awaiting=AWAITING_JUDGMENT,
            open_brief=brief,
            slots={"authoring_promote_paths": '{"C1":"a","C2":"b"}'},
        )
    )
    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("C2")) is False
    session = await h.store.load("rw")
    assert session is not None
    assert session.awaiting == AWAITING_JUDGMENT
    assert session.open_brief is not None


async def test_collaborator_stop_clears_session(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    await h.store.save(HermesSession(tenant_slug="rw", room=_ROOM, awaiting=AWAITING_CLARIFY))
    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg(" Stop ")) is True
    assert await h.store.load("rw") is None


async def test_collaborator_clarify_then_init_starts_programme(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("start validate-requirements"))
    session = await h.store.load("rw")
    assert session is not None
    assert session.awaiting == AWAITING_CLARIFY
    assert "INIT-" in h.poster.posts[-1]

    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("it's init-rw-001"))
    session = await h.store.load("rw")
    assert session is not None
    assert session.awaiting == AWAITING_NONE
    assert session.initiative == "INIT-RW-001"
    assert session.stage == "validate-requirements"
    assert session.programme == "meta-pm"
    assert len(h.runner.started) == 1


async def test_collaborator_post_pm_without_initiative_digs(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("let's do post-pm now"))
    session = await h.store.load("rw")
    assert session is not None
    assert session.awaiting == AWAITING_CLARIFY
    assert session.slots["pending_node"] == "validate-requirements"


async def test_collaborator_ignores_unrelated_message(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("hello there")) is False


async def test_collaborator_matches_judgment_token(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    brief = h.briefs.brief_from_validate_finding(_finding(), node_id="requirements-human-decision")
    await h.store.save(
        HermesSession(
            tenant_slug="rw",
            room=_ROOM,
            stage="requirements-human-decision",
            awaiting=AWAITING_JUDGMENT,
            open_brief=brief,
        )
    )
    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("what?")) is True
    session = await h.store.load("rw")
    assert session is not None and session.awaiting == AWAITING_JUDGMENT

    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("VF-01: fix"))
    session = await h.store.load("rw")
    assert session is not None
    assert session.awaiting == AWAITING_NONE
    assert session.open_brief is None
    assert session.handoff_outcome == "VF-01: fix"


async def test_collaborator_authorization_dispatches_forge(tmp_path: Path) -> None:
    h = _Harness(tmp_path)
    brief = h.briefs.brief_authorization(h.snap.node("prd-pr-action"), "INIT-RW-001")
    await h.store.save(
        HermesSession(
            tenant_slug="rw",
            room=_ROOM,
            initiative="INIT-RW-001",
            stage="prd-pr-action",
            awaiting=AWAITING_AUTHORIZATION,
            open_brief=brief,
        )
    )
    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("maybe")) is True
    assert h.dispatch.calls == []

    assert await h.collab.handle_lead_message(_TENANT, _ROOM, _msg("Go ahead please"))
    assert h.dispatch.calls == ["prd-pr-action"]
    session = await h.store.load("rw")
    assert session is not None
    assert session.stage == "prd-impact-acceptance"
    assert session.awaiting == AWAITING_JUDGMENT
