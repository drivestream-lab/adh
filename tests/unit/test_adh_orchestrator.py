"""Orchestrator control plane — ask-back / stop / role-scoped work."""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import uuid4

import pytest

from src.adh_agents.runtime.orchestrator import Orchestrator, match_reply_token
from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    PROGRAMME_META_PM,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.models.buzz_models import EventType, MessageKind, MessageRead
from src.models.hermes.intent_models import JudgmentRequest
from src.models.tenant_models import TenantContext


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, as_json: bool = False) -> Any:
        raw = self.data.get(key)
        if raw is not None and as_json:
            return json.loads(raw)
        return raw

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        self.data[key] = value if isinstance(value, str) else json.dumps(value)
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0


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


class _FakeUnderstand:
    def extract_initiative(self, text: str, init_prefix: str = "") -> str | None:
        t = text.strip().upper()
        if t.startswith(init_prefix.upper()):
            return t
        return None

    def candidates_for_node_mention(self, body: str, *, init_prefix: str = ""):
        return []

    def clarify_for(self, candidates, *, init_prefix: str = ""):
        return None

    def entrypoint_node(self, programme: str):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_ask_back_on_ambiguous_confirm() -> None:
    redis = _FakeRedis()
    store = AgentWorkStore(redis)  # type: ignore[arg-type]
    poster = _FakePoster()
    orch = Orchestrator(
        store=store,
        understand=_FakeUnderstand(),  # type: ignore[arg-type]
        briefs=None,  # type: ignore[arg-type]
        navigator=None,  # type: ignore[arg-type]
        dispatch=None,  # type: ignore[arg-type]
        poster=poster,  # type: ignore[arg-type]
    )
    orch.bind_role("adh.pm")
    tenant = TenantContext(
        slug="realworld",
        org="drivestream-lab",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
        ops_room="realworld-ops",
        integration_branch="main",
        init_prefix="INIT-REALWORLD-",
    )
    brief = JudgmentRequest(
        node_id="prd-impact-acceptance",
        question="confirm?",
        reply_tokens=["confirm", "revise"],
    )
    for init in ("INIT-REALWORLD-001", "INIT-REALWORLD-002"):
        await store.save(
            AgentWorkSession(
                tenant_slug="realworld",
                role_id="adh.pm",
                room="realworld-ops",
                work_id=init,
                initiative=init,
                programme=PROGRAMME_META_PM,
                stage="prd-impact-acceptance",
                awaiting=AWAITING_JUDGMENT,
                open_brief=brief,
            )
        )
    msg = MessageRead(
        id=uuid4(),
        room_id=uuid4(),
        identity_id=uuid4(),
        identity_handle="nikd10x",
        body="confirm",
        kind=MessageKind.MESSAGE,
    )
    consumed = await orch.handle_lead_message(tenant, "realworld-ops", msg)
    assert consumed is True
    assert any("more than one" in p.lower() or "which" in p.lower() for p in poster.posts)


def test_match_reply_token() -> None:
    assert match_reply_token("confirm\nthanks", ["confirm", "revise"]) == "confirm"
    assert match_reply_token("nope", ["confirm"]) is None


class _MergedRunner:
    """Programme runner stub — should not be called for merged INIT go-ahead."""

    programme_id = PROGRAMME_META_PM

    def list_resumable(self, tenant):  # noqa: ANN001
        del tenant
        return [
            {
                "initiative": "INIT-REALWORLD-001",
                "gate": "authorize",
                "hint": "should be filtered — already merged",
            }
        ]

    async def resume_programme(self, tenant, room, work_id):  # noqa: ANN001
        raise AssertionError(f"must not resume merged INIT {work_id}")

    async def start_programme(self, tenant, room, session):  # noqa: ANN001
        raise AssertionError("must not start")

    async def after_judgment(self, tenant, room, session, token):  # noqa: ANN001
        raise AssertionError("must not judge")


@pytest.mark.asyncio
async def test_post_merge_go_ahead_does_not_reopen_product_draft() -> None:
    """U2/U5: bare go ahead after prd-merged must not reopen draft-PR authorize."""
    redis = _FakeRedis()
    store = AgentWorkStore(redis)  # type: ignore[arg-type]
    poster = _FakePoster()
    orch = Orchestrator(
        store=store,
        understand=_FakeUnderstand(),  # type: ignore[arg-type]
        briefs=None,  # type: ignore[arg-type]
        navigator=None,  # type: ignore[arg-type]
        dispatch=None,  # type: ignore[arg-type]
        poster=poster,  # type: ignore[arg-type]
    )
    orch.bind_role("adh.pm")
    orch.set_programme_runner(_MergedRunner())  # type: ignore[arg-type]
    tenant = TenantContext(
        slug="realworld",
        org="drivestream-lab",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
        ops_room="realworld-ops",
        integration_branch="develop",
        init_prefix="INIT-REALWORLD-",
    )
    await store.save(
        AgentWorkSession(
            tenant_slug="realworld",
            role_id="adh.pm",
            room="realworld-ops",
            work_id="INIT-REALWORLD-001",
            initiative="INIT-REALWORLD-001",
            programme=PROGRAMME_META_PM,
            stage="prd-merged",
            awaiting="none",
            slots={"merge_sha": "abc123"},
        )
    )
    msg = MessageRead(
        id=uuid4(),
        room_id=uuid4(),
        identity_id=uuid4(),
        identity_handle="nikd10x",
        body="go ahead",
        kind=MessageKind.MESSAGE,
    )
    consumed = await orch.handle_lead_message(tenant, "realworld-ops", msg)
    assert consumed is True
    assert any("already merged" in p.lower() for p in poster.posts)
