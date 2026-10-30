"""Quality file is a team memo for the human PM: table, recommendation, gaps."""

import asyncio
from unittest.mock import MagicMock

from src.business_services.hermes_service import (
    HermesService,
    apply_ask_card,
    apply_quality_card,
)
from src.infra_services.prompt_service import PromptService


_INIT = "INIT-REALWORLD-001"
_PATH = "prd/reports/INIT-REALWORLD-001-prd-quality.md"

_PARSED = {
    "rank": "C4-wins",
    "recommend_promote": "C4",
    "recommendation_why": (
        "C4 lets a visitor see an empty home, then a published article, "
        "and the same article on API and web. Write is publish, so drafts "
        "cannot be lost."
    ),
    "lead_questions": [
        {
            "question": "Is write the same as publish, or is there a draft?",
            "why_it_matters": "C3 keeps drafts that the author cannot open again.",
            "if_unanswered": "The recommend label stays C4 (write = publish).",
        }
    ],
    "notes": "C4 is engineering-ready. C2 score is rank only.",
    "harness_proposal": "Home shows 0 then 1 published article.",
    "candidates": [
        {
            "label": "C1",
            "path": "prd/reports/INIT-REALWORLD-001-prd-think.md",
            "handover": "no",
            "overall": 2.8,
            "why": "Empty home then one article is the job.",
            "why_not": "Home has no defined limit, so engineering would guess.",
            "material_fails": ["B9 pagination threshold undefined"],
            "bars": [
                {"bar": "B1", "result": "PASS", "evidence": "Visitor sees published articles"},
                {
                    "bar": "B9",
                    "result": "FAIL",
                    "evidence": "Home has no defined limit when many articles exist.",
                },
            ],
        },
        {
            "label": "C4",
            "path": "prd/reports/INIT-REALWORLD-001-prd-think-4.md",
            "handover": "yes",
            "overall": 3.0,
            "why": "Write is publish. Unpublish exists. API and web agree.",
            "why_not": "",
            "material_fails": [],
            "bars": [
                {
                    "bar": "B1",
                    "result": "PASS",
                    "evidence": (
                        "A visitor opening the home page sees published articles "
                        "if any exist. A registered user can write an article and "
                        "publish it so visitors see it on home. The same article "
                        "must appear identically via API and web."
                    ),
                },
                {
                    "bar": "B2",
                    "result": "PASS",
                    "evidence": (
                        "Visitor viewing, author publishing and unpublishing, "
                        "and API/web showing the same articles."
                    ),
                },
                {
                    "bar": "B9",
                    "result": "PASS",
                    "evidence": "Open questions have defaults, so spec-draft does not guess.",
                },
            ],
        },
    ],
}


def _hermes() -> HermesService:
    prompts = PromptService(MagicMock())
    asyncio.run(prompts.initialize())
    return HermesService(MagicMock(), MagicMock(), MagicMock(), prompts, MagicMock(), MagicMock())


def test_quality_file_keeps_tables_and_highlights_recommendation() -> None:
    hermes = _hermes()
    body = hermes._render_quality_file(_INIT, _PARSED, _PATH, "sonnet", 2, 2)
    assert body.index("## Our recommendation") < body.index("## Questions for you")
    assert body.index("## Questions for you") < body.index("## Recommendation")
    assert body.index("## Recommendation") < body.index("## Evidence: why C4")
    assert "| Candidate | File | Handover | Overall | Why | Why not |" in body
    assert "**C4 ←**" in body
    assert "Write is publish. Unpublish exists. API and web agree." in body
    assert "Home has no defined limit, so engineering would guess." in body
    assert "| # | Question | Why it matters | If you skip |" in body
    assert "Is write the same as publish" in body
    evidence = body.split("## Evidence")[1].split("## Scorecard")[0]
    assert "| Bar | Result | What this means |" in evidence
    assert "The same article must appear identically via API and web." in evidence
    assert "…" not in evidence
    assert "| B9 | FAIL | PASS |" in body
    hop = hermes._render_quality_hop_body(_INIT, _PARSED, "sonnet", 2, 2, _PATH)
    assert "evaluator for your judgement" in hop
    assert "## Our recommendation" in hop
    assert "Full evidence is in" in hop


def test_apply_quality_card_does_not_change_scores() -> None:
    scored = {
        "rank": "C4-wins",
        "recommend_promote": "C4",
        "candidates": [
            {
                "label": "C4",
                "handover": "yes",
                "overall": 3.0,
                "bars": [
                    {"bar": "B9", "result": "PASS", "evidence": "raw quote"},
                ],
            }
        ],
    }
    merged = apply_quality_card(
        scored,
        {
            "recommendation_why": "Write is publish.",
            "lead_questions": [{"question": "Draft or publish?"}],
            "candidates": [
                {
                    "label": "C4",
                    "why": "The job works end to end.",
                    "why_not": "",
                    "bars": [
                        {
                            "bar": "B9",
                            "result": "FAIL",
                            "evidence": "Open questions have defaults.",
                        }
                    ],
                }
            ],
        },
    )
    assert merged["rank"] == "C4-wins"
    assert merged["recommend_promote"] == "C4"
    assert merged["candidates"][0]["handover"] == "yes"
    assert merged["candidates"][0]["overall"] == 3.0
    assert merged["candidates"][0]["bars"][0]["result"] == "PASS"
    assert merged["candidates"][0]["bars"][0]["evidence"] == "Open questions have defaults."
    assert merged["recommendation_why"] == "Write is publish."
    assert merged["lead_questions"][0]["question"] == "Draft or publish?"


_ASK = {
    "forks": [
        {
            "id": "F1",
            "question": "When an author saves, is it live or a draft?",
            "choices": [
                "Published immediately when saved (write = publish)",
                "Saved as draft by default, requires separate publish action",
            ],
            "why_it_changes_the_pick": "C4 has no draft; C3's draft cannot be opened again.",
            "quote": "OQ-05 dumps",
        }
    ],
    "notes": "Answer F1.",
}


def test_ask_file_is_a_decision_table_not_a_quote_dump() -> None:
    hermes = _hermes()
    enriched = apply_ask_card(
        _ASK,
        {
            "forks": [
                {
                    "id": "F1",
                    "question": "CHANGED",
                    "choices": ["nope"],
                    "example": "You write on the train, hit save, and lose signal.",
                    "recommend": "Published immediately when saved (write = publish)",
                    "recommend_why": (
                        "C4 proves write=publish. A first slice with no draft "
                        "list will lose the work."
                    ),
                    "choice_rows": [
                        {
                            "choice": "Published immediately when saved (write = publish)",
                            "means": "Strangers can already see it. Closing the laptop does not lose it.",
                        },
                        {
                            "choice": "Saved as draft by default, requires separate publish action",
                            "means": "Safe to tinker only if you can find it tomorrow.",
                        },
                    ],
                }
            ]
        },
    )
    assert enriched["forks"][0]["question"] == "When an author saves, is it live or a draft?"
    assert enriched["forks"][0]["choices"][0].startswith("Published immediately")
    body = hermes._render_ask_file(_INIT, enriched, "prd/reports/INIT-REALWORLD-001-prd-ask.md")
    assert "| Fork | Decision | We recommend |" in body
    assert "**In real life.**" in body
    assert "**We recommend.**" in body
    assert "| If you choose | What happens |" in body
    assert "Quote:" not in body
    assert "OQ-05" not in body
    assert "This changes which file" not in body
    assert "C4" not in body
    assert "This proves write=publish" in body
    assert "A first slice with no draft list will lose the work." in body
    hop = hermes._render_ask_hop_body(_INIT, enriched, "sonnet")
    assert "F1: <choice>" in hop
    assert "Quote:" not in hop
