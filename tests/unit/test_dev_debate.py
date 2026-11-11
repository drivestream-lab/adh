"""Dev multi-pass debate — cap, early converge, ceiling flag."""

from __future__ import annotations

import pytest

from src.adh_agents.programmes.dev.debate import _parse_pass, run_dev_debate
from src.adh_agents.runtime.room_resolve import engg_room_slug_for, task_id_from_engg_room


def test_engg_room_slug() -> None:
    assert engg_room_slug_for("INIT-REALWORLD-001") == "engg-init-realworld-001"
    assert task_id_from_engg_room("engg-init-realworld-001") == "INIT-REALWORLD-001"


def test_parse_pass_matches_token() -> None:
    body = """
recommend: accept deps
example: reply `accept deps` — tiers look right
bluf: API before web
locking: Tier 0 order
not_locking: ticket titles
revise_if: new repo
"""
    parsed = _parse_pass(body, ["accept deps", "another round", "hold"])
    assert parsed is not None
    assert parsed.recommend == "accept deps"
    assert "accept deps" in parsed.example


@pytest.mark.asyncio
async def test_debate_early_converge(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLiteLLM:
        async def complete(self, system: str, user: str, **kwargs: object) -> str:
            return (
                "recommend: accept deps\n"
                "example: reply `accept deps`\n"
                "bluf: clear\n"
                "locking: dag\n"
                "not_locking: titles\n"
                "revise_if: scope\n"
            )

    from src.adh_agents import programmes as prog_pkg  # noqa: F401
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
        purpose="deps-acceptance",
        initiative="INIT-REALWORLD-001",
        context="Tier 0: api",
        reply_tokens=["accept deps", "hold"],
        max_runs=4,
    )
    assert result.converged_at_pass == 1
    assert result.hit_ceiling is False
    assert result.recommend == "accept deps"
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
        purpose="deps-acceptance",
        initiative="INIT-X",
        context="x",
        reply_tokens=["accept deps", "hold"],
        max_runs=2,
    )
    assert result.hit_ceiling is True
    assert result.passes == 2
    assert result.recommend in {"accept deps", "hold"}
