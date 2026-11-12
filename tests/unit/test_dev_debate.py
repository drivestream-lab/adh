"""Dev multi-pass debate — Hermes pack → extract → decide (no inline prompts)."""

from __future__ import annotations

from typing import Any

import pytest

from src.adh_agents.programmes.dev.debate import _extract_decision, run_dev_debate
from src.adh_agents.runtime.room_resolve import engg_room_slug_for, task_id_from_engg_room
from src.models.prompt_models import PromptRunResult


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


class _FakePrompts:
    def __init__(self, parsed: dict[str, Any] | None = None, raw: str = "") -> None:
        self.parsed = parsed
        self.raw = raw
        self.calls: list[str] = []

    async def complete(
        self, template_id: str, variables: dict[str, Any], **kwargs: object
    ) -> PromptRunResult:
        self.calls.append(template_id)
        return PromptRunResult(
            template_id=template_id,
            version="1",
            parsed=self.parsed or {},
            raw=self.raw,
            model=str(kwargs.get("model") or "qwen"),
            stub=False,
        )


@pytest.mark.asyncio
async def test_debate_early_converge(monkeypatch: pytest.MonkeyPatch) -> None:
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
    fake = _FakePrompts(
        parsed={
            "recommend": "accept tdd-adr",
            "bluf": "clear",
            "example": "reply `accept tdd-adr`",
            "locking": ["adr"],
            "not_locking": ["titles"],
            "revise_if": ["scope"],
        },
        raw="recommend: accept tdd-adr",
    )
    result = await run_dev_debate(
        fake,  # type: ignore[arg-type]
        purpose="tdd-adr-acceptance",
        initiative="INIT-ACME-001",
        context="ADR draft",
        reply_tokens=["accept tdd-adr", "hold"],
        max_runs=4,
    )
    assert fake.calls == ["hermes.dev.debate.pass"]
    assert result.converged_at_pass == 1
    assert result.hit_ceiling is False
    assert result.recommend == "accept tdd-adr"
    assert result.passes == 1
    assert result.template_id == "hermes.dev.debate.pass"


@pytest.mark.asyncio
async def test_debate_hit_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
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
    fake = _FakePrompts(parsed={"recommend": "mush"}, raw="no recommend token here")
    result = await run_dev_debate(
        fake,  # type: ignore[arg-type]
        purpose="coding-readiness",
        initiative="INIT-X",
        context="x",
        reply_tokens=["coding ready", "hold"],
        max_runs=2,
    )
    assert result.hit_ceiling is True
    assert result.passes == 2
    assert result.recommend == "hold"
