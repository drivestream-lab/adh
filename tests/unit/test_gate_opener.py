"""F8 — GateOpener opens + god take / halt."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.gate_opener import CoachSpec, GateOpener
from src.adh_agents.runtime.work_models import AWAITING_JUDGMENT, AgentWorkSession
from src.adh_agents.settings import AdhAutonomySettings
from src.configs.base_settings import BaseSettings
from src.models.hermes.intent_models import JudgmentRequest


def _reset_autonomy_settings() -> None:
    BaseSettings._instances.pop(AdhAutonomySettings.__name__, None)


def _session() -> AgentWorkSession:
    return AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="task-init-realworld-001",
        initiative="INIT-REALWORLD-001",
        programme="authoring",
        stage="authoring-promote",
    )


def test_gate_opener_human_waits(monkeypatch) -> None:
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "human")
    _reset_autonomy_settings()
    store = MagicMock()
    store.save = AsyncMock()
    poster = MagicMock()
    poster.post_human_next = AsyncMock()
    buzz = MagicMock()
    buzz.append_task_event = AsyncMock()
    redis = MagicMock()
    autonomy = AutonomyPolicy(redis)
    opener = GateOpener(store, poster, buzz, autonomy)
    brief = JudgmentRequest(
        node_id="authoring-promote",
        purpose="authoring-promote",
        question="pick?",
        recommend="C1",
        reply_tokens=["C1", "skip"],
    )

    async def _run():
        return await opener.open(
            _session(),
            brief=brief,
            coach=CoachSpec(
                i_did="did",
                recommend="C1",
                outside_adh="read",
                tokens=[TokenAction("C1", "promote")],
            ),
        )

    assert asyncio.run(_run()) is None
    assert store.save.await_count >= 1
    poster.post_human_next.assert_awaited()
    _reset_autonomy_settings()


def test_gate_opener_god_takes(monkeypatch) -> None:
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "god")
    _reset_autonomy_settings()
    store = MagicMock()
    store.save = AsyncMock()
    poster = MagicMock()
    poster.post_human_next = AsyncMock()
    poster.post_status = AsyncMock()
    buzz = MagicMock()
    buzz.append_task_event = AsyncMock()
    buzz.post_message = AsyncMock()
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    autonomy = AutonomyPolicy(redis)
    opener = GateOpener(store, poster, buzz, autonomy)
    brief = JudgmentRequest(
        node_id="prd-merge",
        purpose="prd-merge",
        question="merge?",
        recommend="go ahead",
        reply_tokens=["go ahead", "park"],
    )

    async def _run():
        return await opener.open(
            _session(),
            brief=brief,
            coach=CoachSpec(
                i_did="settled",
                recommend="go ahead",
                outside_adh="review",
                tokens=[TokenAction("go ahead", "merge")],
            ),
            awaiting=AWAITING_JUDGMENT,
        )

    token = asyncio.run(_run())
    assert token == "go ahead"
    buzz.post_message.assert_awaited()
    _reset_autonomy_settings()


def test_gate_opener_god_falls_back_to_coach_recommend(monkeypatch) -> None:
    """Forge briefs used to recommend ``authorize`` while tokens said ``go ahead``."""
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "god")
    _reset_autonomy_settings()
    store = MagicMock()
    store.save = AsyncMock()
    poster = MagicMock()
    poster.post_human_next = AsyncMock()
    poster.post_status = AsyncMock()
    buzz = MagicMock()
    buzz.append_task_event = AsyncMock()
    buzz.post_message = AsyncMock()
    buzz.set_task_state = AsyncMock()
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    autonomy = AutonomyPolicy(redis)
    opener = GateOpener(store, poster, buzz, autonomy)
    brief = JudgmentRequest(
        node_id="prd-pr-action",
        purpose="prd-pr-action",
        question="Authorize open_draft_pr?",
        recommend="authorize",  # not in reply_tokens
        reply_tokens=["go ahead", "authorize open_draft_pr"],
    )

    async def _run():
        return await opener.open(
            _session(),
            brief=brief,
            coach=CoachSpec(
                i_did="Impact-Map ready",
                recommend="go ahead",
                outside_adh="skim",
                tokens=[TokenAction("go ahead", "open draft PR")],
            ),
            awaiting=AWAITING_JUDGMENT,
        )

    token = asyncio.run(_run())
    assert token == "go ahead"
    _reset_autonomy_settings()
