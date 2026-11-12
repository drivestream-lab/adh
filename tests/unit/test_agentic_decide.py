"""Platform decide — PromptService template ids only (no inline prompt bodies)."""

from __future__ import annotations

from typing import Any

import pytest

from src.adh_agents.runtime.agentic_decide import decide_catalogue_outcome, decide_reply_token
from src.models.prompt_models import PromptRunResult


class _FakePrompts:
    def __init__(self, parsed: dict[str, Any], raw: str = "") -> None:
        self.parsed = parsed
        self.raw = raw
        self.last_id = ""

    async def complete(
        self, template_id: str, variables: dict[str, Any], **kwargs: object
    ) -> PromptRunResult:
        del kwargs
        self.last_id = template_id
        return PromptRunResult(
            template_id=template_id,
            version="1",
            parsed=self.parsed,
            raw=self.raw,
            model="qwen",
            stub=False,
        )


@pytest.mark.asyncio
async def test_decide_catalogue_outcome_uses_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.adh_agents.runtime import agentic_decide as mod

    monkeypatch.setattr(
        mod.HermesSettings,
        "get_instance",
        classmethod(
            lambda cls: type("H", (), {"eng_model": "qwen", "pm_model": "qwen", "model": "qwen"})()
        ),
    )
    fake = _FakePrompts({"outcome": "pass", "why": "ok"})
    out = await decide_catalogue_outcome(
        fake,  # type: ignore[arg-type]
        role_id="adh.dev",
        node_id="spec-draft",
        initiative="INIT-X",
        allowed_outcomes=["pass", "failed"],
        evidence="skill ok",
    )
    assert out == "pass"
    assert fake.last_id == "hermes.dev.decide.outcome"


@pytest.mark.asyncio
async def test_decide_reply_token_uses_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.adh_agents.runtime import agentic_decide as mod

    monkeypatch.setattr(
        mod.HermesSettings,
        "get_instance",
        classmethod(
            lambda cls: type("H", (), {"eng_model": "qwen", "pm_model": "qwen", "model": "qwen"})()
        ),
    )
    fake = _FakePrompts(
        {
            "recommend": "coding ready",
            "bluf": "plan ok",
            "example": "reply `coding ready`",
            "locking": ["wm"],
            "not_locking": ["tickets"],
            "revise_if": ["scope"],
        }
    )
    out = await decide_reply_token(
        fake,  # type: ignore[arg-type]
        role_id="adh.dev",
        purpose="coding-readiness",
        initiative="INIT-X",
        reply_tokens=["coding ready", "hold"],
        context="plan",
    )
    assert out["recommend"] == "coding ready"
    assert fake.last_id == "hermes.dev.decide.reply"
    assert out["template_id"] == "hermes.dev.decide.reply"
