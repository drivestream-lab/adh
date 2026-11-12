"""Hermes behaviour packs load via PromptService (greenfield inventory)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from src.infra_services.prompt_service import PromptService
from src.models.prompt_models import RESPONSE_MODELS

REQUIRED = (
    "hermes.dev.debate.pass",
    "hermes.dev.decide.reply",
    "hermes.dev.decide.outcome",
    "hermes.pe.gate1.recommend",
    "hermes.pe.impact.challenge",
    "hermes.kb.learning.harvest",
    "hermes.kb.head.fill",
)


def test_behaviour_packs_load_and_render() -> None:
    service = PromptService(MagicMock())
    asyncio.run(service.initialize())
    for tid in REQUIRED:
        spec = service.get(tid)
        assert spec.id == tid
        assert spec.response.model in RESPONSE_MODELS
    rendered = service.render(
        "hermes.dev.debate.pass",
        {
            "initiative": "INIT-REALWORLD-003",
            "purpose": "coding-readiness",
            "pass_number": "1",
            "max_passes": "4",
            "reply_tokens": "`coding ready`, `hold`",
            "context": "plan excerpt",
            "prior": "(none)",
            "challenge": "First pass",
            "kb_excerpt": "(none)",
        },
    )
    assert "adh.dev" in rendered.system
    assert "INIT-REALWORLD-003" in rendered.user
    asyncio.run(service.close())
