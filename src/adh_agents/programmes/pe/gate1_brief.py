"""Gate‑1 decision paper — same recommend / Buying / Not buying shape as PM promote."""

from __future__ import annotations

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
) -> DecisionCard:
    """Product skim card for Lead/PE after a Gate‑1 question round."""
    locking = [f"{q.qid}: {q.recommendation}" for q in questions[:3] if q.recommendation] or [
        "Product questions posted — PM stance still open."
    ]
    not_locking = [
        "Merge authorize (separate PM/Lead forge gate)",
        "App-repo mutate (later hire)",
    ]
    revise_if = [
        "PM rejects or adjusts a PQ stance",
        "Impact-Map CAP/CTR tables drift from PRD",
        f"Question budget exhausted ({max_rounds} rounds)",
    ]
    return decision_card(
        recommend=recommend,
        bluf=(
            f"Gate‑1 round {round_number}/{max_rounds} for {initiative}: "
            "wait for PM answers before attesting this meta PR head."
        ),
        example=(
            "PM answers on the PR thread / Buzz; PE attests only when product stance "
            "is clear. Merge stays a separate authorize."
        ),
        locking=locking,
        not_locking=not_locking,
        revise_if=revise_if,
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

    Buzz stays BLUF + path only — this file is the SSOT for the decision card.
    """
    lines = [
        f"# Gate‑1 decision brief — {initiative}",
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
            "| `attest` | Approve this meta PR head when satisfied |",
            "| `hold` | Park Gate‑1 |",
            "",
            "## artefacts",
            "",
            f"- Questions: `{questions_path}`",
            f"- Meta PR: {pr_url or '(unknown)'}",
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
    """Buzz light — paper carries the full recommendation."""
    return "\n".join(
        [
            f"Gate‑1 round {round_number}/{max_rounds} for **{initiative}** "
            f"({question_count} Q) — decision paper ready.",
            f"Artefact: `{brief_path}`",
            f"Questions: `{questions_path}`",
            "**Next:** waiting on PM answers (`adh.pm`) — reply `attest` / `new_round` / "
            "`hold` when you want to fork.",
        ]
    )
