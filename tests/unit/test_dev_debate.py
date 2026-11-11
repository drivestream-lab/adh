"""Dev multi-pass debate — prompt → labeled extract → decide (no regex)."""

from __future__ import annotations

import pytest

from src.adh_agents.programmes.dev.debate import _extract_decision, run_dev_debate
from src.adh_agents.runtime.room_resolve import engg_room_slug_for, task_id_from_engg_room


def test_engg_room_slug() -> None:
    assert engg_room_slug_for("INIT-ACME-001") == "engg-init-acme-001"
    assert task_id_from_engg_room("engg-init-acme-001") == "INIT-ACME-001"


def test_extract_decision_matches_token() -> None:
    body = """
recommend: accept tdd-adr
example: reply `accept tdd-adr` — ADR looks right
bluf: API before web
locking: ADR boundaries
not_locking: ticket titles
revise_if: new CAP
"""
    parsed = _extract_decision(body, ["accept tdd-adr", "another round", "hold"])
    assert parsed is not None
    assert parsed["recommend"] == "accept tdd-adr"
    assert "accept tdd-adr" in parsed["example"]


@pytest.mark.asyncio
async def test_debate_early_converge(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLiteLLM:
        async def complete(self, system: str, user: str, **kwargs: object) -> str:
            return (
                "recommend: accept tdd-adr\n"
                "example: reply `accept tdd-adr`\n"
                "bluf: clear\n"
                "locking: adr\n"
                "not_locking: titles\n"
                "revise_if: scope\n"
            )

    from src.adh_agents.programmes.dev import debate as debate_mod
    from src.adh_agents.settings import DevAgentSettings

    monkeypatch.setattr(
        debate_mod.DevAgentSettings,
        "get_instance",
        classmethod(lambda cls: DevAgentSettings(max_think_runs=4)),
    )
    monkeypatch.setattr(
        debate_mod.HermesSettings,
        "get_instance",
        classmethod(
            lambda cls: type(
                "H",
                (),
                {"eng_model": "qwen", "pm_model": "sonnet", "model": "qwen"},
            )()
        ),
    )

    result = await run_dev_debate(
        FakeLiteLLM(),  # type: ignore[arg-type]
        purpose="tdd-adr-acceptance",
        initiative="INIT-ACME-001",
        context="ADR draft",
        reply_tokens=["accept tdd-adr", "hold"],
        max_runs=4,
    )
    assert result.converged_at_pass == 1
    assert result.hit_ceiling is False
    assert result.recommend == "accept tdd-adr"
    assert result.passes == 1


@pytest.mark.asyncio
async def test_debate_hit_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLiteLLM:
        async def complete(self, system: str, user: str, **kwargs: object) -> str:
            return "no recommend token here, just mush"

    from src.adh_agents.programmes.dev import debate as debate_mod
    from src.adh_agents.settings import DevAgentSettings

    monkeypatch.setattr(
        debate_mod.DevAgentSettings,
        "get_instance",
        classmethod(lambda cls: DevAgentSettings(max_think_runs=2)),
    )
    monkeypatch.setattr(
        debate_mod.HermesSettings,
        "get_instance",
        classmethod(
            lambda cls: type(
                "H",
                (),
                {"eng_model": "qwen", "pm_model": "qwen", "model": "qwen"},
            )()
        ),
    )

    result = await run_dev_debate(
        FakeLiteLLM(),  # type: ignore[arg-type]
        purpose="coding-readiness",
        initiative="INIT-X",
        context="x",
        reply_tokens=["coding ready", "hold"],
        max_runs=2,
    )
    assert result.hit_ceiling is True
    assert result.passes == 2
    assert result.recommend == "hold"
