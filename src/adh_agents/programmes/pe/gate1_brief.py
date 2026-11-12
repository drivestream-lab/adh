"""Product brief (Gate‑1 lane) — same recommend / Buying / Not buying shape as PM promote.

Buzz uses delivery voice via ``format_gate1_buzz_bluf`` / ``post_human_next``.
Artefact markdown may keep Gate‑1 in the title for path continuity; Buzz bodies do not.
"""

from __future__ import annotations

from src.adh_agents.collaboration.gate_coach import TokenAction, format_human_next
from src.adh_agents.programmes.pe.questions import ProductQuestion
from src.adh_agents.programmes.pm.decision_card import (
    CARD_PROMOTE,
    DecisionCard,
    decision_card,
)
from src.infra_services.pm_workspace_service import hermes_gate1_brief_path

# Re-export for callers that already import from this module.
__all__ = [
    "build_gate1_decision_card",
    "format_gate1_brief_markdown",
    "format_gate1_buzz_bluf",
    "hermes_gate1_brief_path",
]


def build_gate1_decision_card(
    *,
    initiative: str,
    round_number: int,
    max_rounds: int,
    questions: list[ProductQuestion],
    recommend: str = "await_pm",
    bluf: str = "",
    example: str = "",
    locking: list[str] | None = None,
    not_locking: list[str] | None = None,
    revise_if: list[str] | None = None,
) -> DecisionCard:
    """Product skim card for Lead/PE after a product-question round.

    Behaviour pack (``hermes.pe.gate1.recommend``) supplies recommend/bluf/locking
    when present; deterministic fallbacks fill any empty fields.
    """
    lock = (
        locking
        or [f"{q.qid}: {q.recommendation}" for q in questions[:3] if q.recommendation]
        or ["Product questions posted — PM stance still open."]
    )
    not_lock = not_locking or [
        "Merge authorize (separate PM/Lead forge gate)",
        "App-repo mutate (later hire)",
    ]
    revise = revise_if or [
        "PM rejects or adjusts a PQ stance",
        "Impact-Map CAP/CTR tables drift from PRD",
        f"Question budget exhausted ({max_rounds} rounds)",
    ]
    return decision_card(
        recommend=recommend or "await_pm",
        bluf=bluf
        or (
            f"Product brief round {round_number}/{max_rounds} for {initiative}: "
            "wait for PM answers before attesting this product PR head."
        ),
        example=example
        or (
            "PM answers on the PR thread / Buzz; PE attests only when product stance "
            "is clear. Merge stays a separate authorize."
        ),
        locking=lock,
        not_locking=not_lock,
        revise_if=revise,
        card_kind=CARD_PROMOTE,
    )


def format_gate1_brief_markdown(
    card: DecisionCard,
    *,
    initiative: str,
    round_number: int,
    max_rounds: int,
    questions_path: str,
    pr_url: str,
    questions: list[ProductQuestion],
) -> str:
    """Full recommendation paper (artefact). Mirrors PM promote Buying / Not buying.

    Buzz stays coach-only — this file is the SSOT for the decision card.
    """
    lines = [
        f"# Product brief — {initiative}",
        "",
        f"> Round **{round_number}/{max_rounds}**. Posted by **adh.pe**. "
        "Same shape as PM promote / post-pm papers: recommend + Buying / Not buying.",
        "",
        f"recommend: {card.recommend}",
        "",
        "## bluf",
        "",
        card.bluf,
        "",
        "**Recommendation.** " f"`{card.recommend}` — {card.bluf}",
        "",
        "**Buying.**",
    ]
    for item in card.locking:
        lines.append(f"- {item}")
    lines.extend(["", "**Not buying.**"])
    for item in card.not_locking:
        lines.append(f"- {item}")
    lines.extend(["", "**Choose another if.**"])
    for item in card.revise_if:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            f"**In real life.** {card.example}",
            "",
            "## locking",
            "",
        ]
    )
    for item in card.locking:
        lines.append(f"- {item}")
    lines.extend(["", "## not_locking", ""])
    for item in card.not_locking:
        lines.append(f"- {item}")
    lines.extend(["", "## revise_if", ""])
    for item in card.revise_if:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## example",
            "",
            card.example,
            "",
            "## options",
            "",
            "| If you choose | What happens |",
            "|---------------|--------------|",
            "| `await_pm` ← | Default after posting Qs — wait for PM (auto) |",
            "| `new_round` | Another capped question pass (Lead/PE) |",
            "| `attest` | Approve this product PR head when satisfied |",
            "| `hold` | Park product brief |",
            "",
            "## artefacts",
            "",
            f"- Questions: `{questions_path}`",
            f"- Product PR: {pr_url or '(unknown)'}",
            "",
            "## questions_index",
            "",
        ]
    )
    for q in questions:
        lines.append(f"- **{q.qid}** — {q.title}: {q.recommendation}")
    lines.append("")
    lines.append(
        "Reply with `attest` / `new_round` / `hold` when you want to fork "
        "(or wait for PM answers)."
    )
    lines.append("")
    return "\n".join(lines)


def format_gate1_buzz_bluf(
    *,
    initiative: str,
    round_number: int,
    max_rounds: int,
    question_count: int,
    brief_path: str,
    questions_path: str,
) -> str:
    """Buzz coach — delivery voice; paper carries the full recommendation."""
    return format_human_next(
        i_did=(
            f"Posted product questions for **{initiative}** "
            f"(round {round_number}/{max_rounds}, {question_count} Q) "
            "and wrote the product brief. PM agent will answer next."
        ),
        recommend="await_pm",
        recommend_why=(
            "Agent↔agent rally in progress — no human ack needed. "
            "You will be asked to merge after clarifications settle."
        ),
        evidence=f"`{brief_path}` · `{questions_path}`",
        outside_adh=(
            "Optional skim of the product brief + questions in Cursor / the product PR. "
            "No Buzz reply required unless you want to `park` or force `need another round`."
        ),
        tokens=[
            TokenAction("park", "park the product brief — stop the rally"),
            TokenAction("need another round", "force another capped question pass (escape hatch)"),
        ],
        hop="product_brief",
        human_role="Lead",
    )
