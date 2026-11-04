"""Quality/ask card helpers remain for meta-pm VF briefs; authoring file renders retired."""

from src.business_services.hermes.cards import apply_ask_card, apply_quality_card


def test_apply_quality_card_does_not_change_scores() -> None:
    frozen = {
        "candidates": [
            {
                "label": "C1",
                "overall": 2.1,
                "handover": "no",
                "bars": [{"bar": "B1", "result": "FAIL"}],
            }
        ],
        "rank": "none",
        "recommend_promote": "none",
    }
    card = {
        "recommendation_why": "Needs a clearer job.",
        "lead_questions": [{"q": "Who is the visitor?", "why": "Scope", "if_skip": "Guess"}],
    }
    out = apply_quality_card(dict(frozen), card)
    assert out["candidates"][0]["overall"] == 2.1
    assert out["recommend_promote"] == "none"
    assert out.get("recommendation_why") == "Needs a clearer job." or "recommendation_why" in out
    # Card may attach lead_questions or leave frozen shape — scores must stay frozen.
    assert out["candidates"][0]["bars"][0]["result"] == "FAIL"


def test_apply_ask_card_keeps_fork_ids() -> None:
    frozen = {
        "forks": [
            {"id": "F1", "decision": "Home empty?", "choices": ["yes", "no"], "recommend": "yes"}
        ]
    }
    card = {
        "forks": [
            {
                "id": "F1",
                "example": "Visitor lands.",
                "options": [{"choice": "yes", "means": "Keep"}],
                "recommend_why": "Matches brief",
            }
        ]
    }
    out = apply_ask_card(dict(frozen), card)
    assert out["forks"][0]["id"] == "F1"
    assert out["forks"][0]["decision"] == "Home empty?"
    assert out["forks"][0]["example"] == "Visitor lands."
