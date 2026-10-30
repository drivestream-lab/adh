"""YAML prompt templates render and validate structured responses."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.configs.base_settings import BaseSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.litellm_service import _parse_json_object
from src.infra_services.prompt_service import PromptService, extract_markdown
from src.models.prompt_models import (
    HermesPmAskResponse,
    HermesPmOutlineResponse,
    HermesPmQualityResponse,
    HermesPmRecommendResponse,
    HermesPmThinkResponse,
    cap_ask_forks,
    quality_from_markdown,
)


def test_packaged_templates_load_and_render() -> None:
    service = PromptService(MagicMock())
    asyncio.run(service.initialize())
    rendered = service.render(
        "hermes.pm.outline",
        {
            "source_message_id": "abc",
            "rubric_dimensions": "citation, journeys",
            "outline": "Home is empty. Publish one article.",
        },
    )
    assert "You are Hermes" in rendered.system
    assert "Home is empty" in rendered.user
    assert "abc" in rendered.user
    assert rendered.response_model == "HermesPmOutlineResponse"
    parsed = service.parse_response(
        "hermes.pm.outline",
        {
            "proposed_init": "INIT-REALWORLD-001",
            "summary": "ok",
            "journeys": ["J-01"],
            "reqs_covered": ["REQ-01"],
            "findings": [],
            "citations": ["#adh-ops"],
            "branch_policy": "feature/*",
            "scores": {"citation": 2},
        },
    )
    assert parsed["proposed_init"] == "INIT-REALWORLD-001"
    HermesPmOutlineResponse.model_validate(parsed)


def test_copy_catalog_renders_without_llm() -> None:
    service = PromptService(MagicMock())
    asyncio.run(service.initialize())
    ack = service.render_copy(
        "hermes.pm.status.outline-ack",
        {"branch": "develop", "meta_repo": "realworld-meta"},
    )
    assert "Received your outline" in ack
    assert "realworld-meta" in ack
    hop = service.render_copy(
        "hermes.pm.hop.think",
        {
            "label": "C1",
            "initiative": "INIT-REALWORLD-HOME-PUBLISH-001",
            "path": "prd/reports/INIT-REALWORLD-HOME-PUBLISH-001-prd-think.md",
            "model": "qwen",
            "short": "empty home",
            "job": "empty home then one article",
            "why_now": "now",
            "if_we_do_nothing": "nothing",
            "kill_assumption": "kill",
            "locked_decisions": "- one",
            "in_scope": "- home",
            "non_goals": "- comments",
            "capabilities": "- CAP-01",
            "requirements": "- REQ-01",
            "journeys": "- J-01",
            "open_questions": "- OQ-01",
            "whole_product_delta": "delta",
            "equivalent_product_notes": "notes",
            "summary": "summary",
        },
    )
    assert hop.startswith("Think C1  INIT-REALWORLD-HOME-PUBLISH-001")
    assert "## Job" in hop


def test_think_and_quality_templates_load() -> None:
    service = PromptService(MagicMock())
    asyncio.run(service.initialize())
    c1 = service.render(
        "hermes.pm.think.c1",
        {
            "source_message_id": "abc",
            "programme_slug": "realworld",
            "meta_repo": "realworld-meta",
            "occupied_inits": "(none)",
            "claimed_path": "prd/reports/INIT-REALWORLD-HOME-prd-think.md",
            "initiative": "INIT-REALWORLD-HOME",
            "outline": "Home is empty. Publish one article.",
        },
    )
    assert "/prd-think C1" in c1.system
    assert "Do not invent an INIT" in c1.system
    assert "job-shaped" in c1.system
    assert "not JSON" in c1.system
    assert "realworld" in c1.user
    assert c1.max_tokens == 20000
    assert c1.response_model == "HermesPmThinkResponse"
    c2 = service.render(
        "hermes.pm.think.c2",
        {
            "initiative": "INIT-REALWORLD-HOME-PUBLISH-001",
            "source_message_id": "abc",
            "outline": "Home is empty.",
            "meta_repo": "realworld-meta",
            "occupied_inits": "(none)",
            "claimed_path": "prd/reports/INIT-REALWORLD-HOME-PUBLISH-001-prd-think-2.md",
            "prior_candidate": {"job": "empty home"},
        },
    )
    assert "/prd-think C2" in c2.system
    assert "empty home" in c2.user
    quality = service.render(
        "hermes.pm.quality",
        {
            "initiative": "INIT-REALWORLD-001",
            "rubric_dimensions": "citation, journeys",
            "threshold_x": 2.7,
            "outline": "Home is empty.",
            "files": "### C1 `prd/reports/INIT-REALWORLD-001-prd-think.md`\nJob text",
            "pass_number": 1,
            "max_passes": 2,
        },
    )
    assert "/prd-quality" in quality.system
    assert "spec-draft" in quality.system
    assert "think JSON" in quality.system
    assert quality.response_model == "HermesPmQualityResponse"
    card = service.render(
        "hermes.pm.quality.card",
        {
            "initiative": "INIT-REALWORLD-001",
            "outline": "Home is empty.",
            "scorecard": '{"rank":"C4-wins"}',
            "files": "### C1\nJob text",
            "max_questions": 3,
        },
    )
    assert "human PM" in card.system
    assert "Do not change them" in card.system
    assert "Never emit the tokens" in card.system
    assert card.response_model == "HermesPmQualityCardResponse"
    parsed = service.parse_response(
        "hermes.pm.think.c1",
        {
            "proposed_init": "INIT-REALWORLD-HOME-PUBLISH-001",
            "candidate_label": "C1",
            "job": "empty home then one article",
        },
    )
    assert parsed["proposed_init"] == "INIT-REALWORLD-HOME-PUBLISH-001"
    ask = service.render(
        "hermes.pm.ask",
        {
            "initiative": "INIT-REALWORLD-001",
            "outline": "Home is empty.",
            "files": "### C1\nJob text",
            "scorecard": "C1 handover=no",
            "answers": "(none)",
            "max_forks": 3,
        },
    )
    assert "/prd-ask" in ask.system
    assert "handover no" in ask.system
    assert "real-life example" in ask.system
    assert ask.response_model == "HermesPmAskResponse"
    ask_card = service.render(
        "hermes.pm.ask.card",
        {
            "initiative": "INIT-REALWORLD-001",
            "outline": "Home is empty.",
            "forks": '[{"id":"F1"}]',
            "files": "### C1\nJob text",
        },
    )
    assert "Do not change id" in ask_card.system
    assert ask_card.response_model == "HermesPmAskCardResponse"
    recommend = service.render(
        "hermes.pm.recommend",
        {
            "initiative": "INIT-REALWORLD-001",
            "outline": "Home is empty.",
            "files": "### C1\nJob text",
            "scorecard": "C2 3.0",
            "answers": "(none)",
            "ask_file": "(none)",
        },
    )
    assert "/prd-recommend" in recommend.system
    assert "not against the 0-3" in recommend.system
    assert recommend.response_model == "HermesPmRecommendResponse"


def test_think_response_coerces_locked_decision_objects() -> None:
    parsed = HermesPmThinkResponse.model_validate(
        {
            "locked_decisions": [
                {"id": "L-01", "decision": "Empty is a product state."},
                "Publish is explicit.",
            ],
            "in_scope": [{"text": "Public home"}],
        }
    )
    assert parsed.locked_decisions == [
        "L-01: Empty is a product state.",
        "Publish is explicit.",
    ]
    assert parsed.in_scope == ["Public home"]


def test_extract_markdown_strips_fence() -> None:
    assert extract_markdown("```markdown\n# INIT-REALWORLD-001\n\nJob.\n```") == (
        "# INIT-REALWORLD-001\n\nJob."
    )


def test_parse_json_object_repairs_unquoted_keys() -> None:
    parsed = _parse_json_object("{candidates: [{label: C1, handover: no}], rank: tie,}")
    assert parsed["candidates"][0]["label"] == "C1"
    assert parsed["candidates"][0]["handover"] == "no"
    assert parsed["rank"] == "tie"


def test_missing_variable_fails_closed() -> None:
    service = PromptService(MagicMock())
    asyncio.run(service.initialize())
    with pytest.raises(ValidationError, match="missing variables"):
        service.render("hermes.pm.outline", {"source_message_id": "x"})


def test_complete_raises_when_llm_fails() -> None:
    litellm = MagicMock()
    litellm.complete = AsyncMock(side_effect=RuntimeError("no model"))
    service = PromptService(litellm)
    asyncio.run(service.initialize())
    with pytest.raises(RuntimeError, match="no model"):
        asyncio.run(
            service.complete(
                "hermes.eng.grade",
                {
                    "pr_ref": "demo/x",
                    "verify_exit": 0,
                    "notes": "n",
                    "threshold_x": 2.7,
                    "rubric_dimensions": "verify",
                },
            )
        )


def test_complete_raises_on_timeout() -> None:
    litellm = MagicMock()
    litellm.complete = AsyncMock(side_effect=TimeoutError())
    service = PromptService(litellm)
    asyncio.run(service.initialize())
    with pytest.raises(TimeoutError):
        asyncio.run(
            service.complete(
                "hermes.pm.outline",
                {
                    "source_message_id": "abc",
                    "rubric_dimensions": "citation",
                    "outline": "Home is empty. Publish one article after register.",
                },
            )
        )


def test_quality_coerces_files_alias_and_markdown_bars() -> None:
    parsed = HermesPmQualityResponse.model_validate(
        {
            "files": [
                {
                    "path": "prd/reports/INIT-REALWORLD-001-prd-think.md",
                    "handover_ready": False,
                    "rubric_pm_scores": {"citation": 3, "journeys": 3},
                    "material_fails": [
                        {
                            "criterion": "B2",
                            "finding": "FAIL",
                            "evidence": "CAP-03 collapses draft and publish.",
                        }
                    ],
                }
            ]
        }
    )
    assert parsed.candidates[0].label == "C1"
    assert parsed.candidates[0].scores["citation"] == 3
    assert parsed.candidates[0].bars[0].bar == "B2"
    md = quality_from_markdown(
        "## C1: `prd/reports/INIT-REALWORLD-001-prd-think.md`\n\n"
        "**B1 (Job-to-be-done):** PASS  \n"
        '*"Visitor sees empty home."*\n'
        "**B9:** FAIL  \n"
        "OQ-03 is contradictory.\n"
    )
    scored = HermesPmQualityResponse.model_validate(md)
    assert scored.candidates[0].label == "C1"
    assert {row.bar: row.result for row in scored.candidates[0].bars}["B1"] == "PASS"
    assert {row.bar: row.result for row in scored.candidates[0].bars}["B9"] == "FAIL"


def test_ask_and_recommend_coerce() -> None:
    asked = HermesPmAskResponse.model_validate(
        {
            "questions": [
                {
                    "prompt": "Home list?",
                    "options": ["all published", "one article"],
                    "why": "C1 vs C2",
                    "quote": "OQ-03",
                },
                {"prompt": "open?", "options": ["essay"]},
            ]
        }
    )
    assert len(asked.forks) == 1
    assert asked.forks[0].id == "F1"
    assert asked.forks[0].choices[0] == "all published"
    assert cap_ask_forks(asked.model_dump()["forks"], max_forks=3)
    picked = HermesPmRecommendResponse.model_validate(
        {
            "pick": "C2-wins",
            "reason": "highest score",
            "rejected": [{"label": "C1", "text": "OQ still open"}],
            "locks": ["multi-article"],
            "engineering_ready": "READY",
        }
    )
    assert picked.recommend == "C2"
    assert picked.engineering_ready == "no"
    assert picked.why_not[0].label == "C1"
    assert picked.residual_locks == ["multi-article"]
    from src.models.prompt_models import recommend_from_markdown

    memo = recommend_from_markdown(
        "# INIT-REALWORLD-001 Recommendation\n\n"
        "## Recommend: **none**\n\n"
        "**Path:** N/A\n\n"
        "## Why\n\n"
        "None of the four candidates are engineering-ready.\n\n"
        "## Why not\n\n"
        "- C1: still has OQ-03\n"
        "- C2: added unpublish\n\n"
        "## Residual locks\n\n"
        "- multi-article home\n"
    )
    scored = HermesPmRecommendResponse.model_validate(memo)
    assert scored.recommend == "none"
    assert scored.engineering_ready == "no"
    assert "engineering-ready" in scored.why
    assert scored.why_not[0].label == "C1"


def test_llm_error_text_survives_empty_timeout() -> None:
    from src.infra_services.prompt_service import _llm_error_text

    assert _llm_error_text(TimeoutError()) == "TimeoutError: TimeoutError"
    assert "ReadTimeout after 90s" in _llm_error_text(
        TimeoutError("ReadTimeout after 90s calling qwen")
    )


def test_custom_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "demo.yaml").write_text(
        "\n".join(
            [
                "id: demo.ping",
                'version: "1"',
                "system: Ping.",
                "user: Hello {{ name }}.",
                "response:",
                "  model: HermesPmBriefResponse",
                "stub:",
                "  summary: hi",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROMPT_ROOT", str(tmp_path))
    BaseSettings._instances.pop("PromptSettings", None)
    service = PromptService(MagicMock())
    asyncio.run(service.initialize())
    rendered = service.render("demo.ping", {"name": "Lead"})
    assert rendered.user == "Hello Lead."
    BaseSettings._instances.pop("PromptSettings", None)
