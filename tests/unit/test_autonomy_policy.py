"""F8a — AutonomyPolicy god/human recommend resolution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.adh_agents.runtime.autonomy import AutonomyMode, AutonomyPolicy
from src.adh_agents.settings import AdhAutonomySettings
from src.configs.base_settings import BaseSettings
from src.models.hermes.intent_models import JudgmentRequest


def _reset_autonomy_settings() -> None:
    BaseSettings._instances.pop(AdhAutonomySettings.__name__, None)


def test_human_mode_default(monkeypatch) -> None:
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "human")
    _reset_autonomy_settings()
    redis = MagicMock()
    policy = AutonomyPolicy(redis)
    assert policy.mode == AutonomyMode.HUMAN
    assert policy.is_god is False
    _reset_autonomy_settings()


def test_god_resolves_recommend_in_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "god")
    _reset_autonomy_settings()
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    policy = AutonomyPolicy(redis)
    brief = JudgmentRequest(
        node_id="prd-merge",
        question="merge?",
        recommend="merge the product PR",
        reply_tokens=["merge the product PR", "go ahead", "park"],
    )
    assert policy.resolve_token(brief) == "merge the product PR"
    assert (
        policy.resolve_token(
            JudgmentRequest(
                node_id="x",
                question="q",
                recommend="hold",
                reply_tokens=["go ahead", "hold"],
            )
        )
        is None
    )
    _reset_autonomy_settings()


def test_god_chain_cap(monkeypatch) -> None:
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "god")
    monkeypatch.setenv("ADH_GOD_CHAIN_CAP", "2")
    _reset_autonomy_settings()
    redis = MagicMock()
    state = {"val": None}

    async def _get(_key):
        return state["val"]

    async def _set(_key, value, ttl=None):
        state["val"] = value
        return True

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    policy = AutonomyPolicy(redis)
    assert policy._settings.god_chain_cap == 2

    async def _run() -> None:
        ok1, _ = await policy.record_take(tenant="realworld", initiative="INIT-1", purpose="a")
        ok2, _ = await policy.record_take(tenant="realworld", initiative="INIT-1", purpose="b")
        ok3, reason = await policy.record_take(tenant="realworld", initiative="INIT-1", purpose="c")
        assert ok1 and ok2
        assert ok3 is False
        assert "cap" in reason

    asyncio.run(_run())
    _reset_autonomy_settings()


def test_god_same_purpose_reentry_allowed(monkeypatch) -> None:
    """another round / findings loops must not halt on duplicate purpose."""
    monkeypatch.setenv("ADH_AUTONOMY_MODE", "god")
    monkeypatch.setenv("ADH_GOD_CHAIN_CAP", "5")
    _reset_autonomy_settings()
    redis = MagicMock()
    state = {"val": None}

    async def _get(_key):
        return state["val"]

    async def _set(_key, value, ttl=None):
        state["val"] = value
        return True

    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    policy = AutonomyPolicy(redis)

    async def _run() -> None:
        ok1, _ = await policy.record_take(
            tenant="realworld", initiative="INIT-1", purpose="tdd-adr-acceptance"
        )
        ok2, reason = await policy.record_take(
            tenant="realworld", initiative="INIT-1", purpose="tdd-adr-acceptance"
        )
        assert ok1 and ok2, reason
        assert "duplicate" not in reason

    asyncio.run(_run())
    _reset_autonomy_settings()
