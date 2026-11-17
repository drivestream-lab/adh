"""Verify Hermes recommend normalization (god GateOpener needs exact reply tokens)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.adh_agents.collaboration.human_replies import HOLD, WAVE_ACCEPTED
from src.adh_agents.programmes.verify.hermes_packs import run_substantiate


@pytest.mark.asyncio
async def test_substantiate_normalizes_wave_accepted_alias() -> None:
    prompts = AsyncMock()
    prompts.complete = AsyncMock(
        return_value=SimpleNamespace(
            parsed={
                "recommend": "wave-accepted",  # alias — must become canonical token
                "bluf": "Blackbox green; DB realworld healthy.",
                "example": "reply `wave accepted`",
                "locking": ["make verify exit 0"],
                "not_locking": ["merge"],
                "revise_if": ["lab down"],
            },
            raw="{}",
        )
    )
    result = await run_substantiate(
        prompts,
        initiative="INIT-REALWORLD-001",
        wave_id="W0",
        repo="realworld-api",
        evidence_excerpt="trigger ok=True\ndb: reachable",
    )
    assert result.recommend == WAVE_ACCEPTED
    assert result.used_fallback is False
    assert "Blackbox green" in result.bluf


@pytest.mark.asyncio
async def test_substantiate_fallback_on_complete_failure() -> None:
    prompts = AsyncMock()
    prompts.complete = AsyncMock(side_effect=RuntimeError("litellm down"))
    result = await run_substantiate(
        prompts,
        initiative="INIT-REALWORLD-001",
        wave_id="W0",
        repo="realworld-api",
        evidence_excerpt="ok",
    )
    assert result.recommend == WAVE_ACCEPTED
    assert result.used_fallback is True
    assert HOLD not in result.recommend


@pytest.mark.asyncio
async def test_substantiate_fallback_when_recommend_not_allowed() -> None:
    prompts = AsyncMock()
    prompts.complete = AsyncMock(
        return_value=SimpleNamespace(
            parsed={
                "recommend": "ship it",
                "bluf": "looks fine",
                "example": "",
                "locking": [],
                "not_locking": [],
                "revise_if": [],
            },
            raw="{}",
        )
    )
    result = await run_substantiate(
        prompts,
        initiative="INIT-X",
        wave_id="W0",
        repo="r",
        evidence_excerpt="ok",
    )
    assert result.recommend == WAVE_ACCEPTED
    assert result.used_fallback is True
