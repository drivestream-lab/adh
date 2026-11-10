"""Helpful-army coach skeleton for Buzz human gates (delivery voice only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from src.adh_agents.collaboration.delivery_voice import delivery_phrase


@dataclass(frozen=True)
class TokenAction:
    """Exact Buzz reply token + what the posting agent will do."""

    token: str
    agent_will: str


def format_human_next(
    *,
    i_did: str,
    recommend: str,
    outside_adh: str,
    tokens: Sequence[TokenAction],
    recommend_why: str = "",
    evidence: str = "",
    human_role: str = "Lead",
    hop: str = "",
    example: str = "",
) -> str:
    """Build the mandatory Buzz coach body for one open human gate.

    DecisionCard depth (Buying / Not buying) lives in the artefact — Buzz stays
    the coach skeleton: I did / recommend / evidence / outside ADH / exact tokens.
    """
    did = (i_did or "").strip()
    if hop and not did:
        did = f"Prepared the {delivery_phrase(hop)}."
    if not did:
        did = "Finished this hop."

    lines: list[str] = [
        f"**I did.** {did}",
        "",
    ]
    rec = (recommend or "").strip()
    why = (recommend_why or "").strip()
    if rec:
        suffix = f" — {why}" if why else ""
        lines += [f"**Recommend.** `{rec}`{suffix}", ""]
    elif why:
        lines += [f"**Recommend.** {why}", ""]

    ev = (evidence or "").strip()
    if ev:
        lines += [f"**Evidence.** {ev}", ""]

    ex = (example or "").strip()
    if ex:
        lines += [f"**In real life.** {ex}", ""]

    lines += [
        f"**You are the human {human_role}.** Review outside ADH, then decide here.",
        "",
        f"**Before you post.** {outside_adh.strip()}",
        "",
        "**On Buzz.**",
    ]
    if not tokens:
        lines.append("- (no reply tokens — agent will continue without a Lead gate)")
    else:
        for action in tokens:
            tok = (action.token or "").strip()
            will = (action.agent_will or "").strip() or "continue"
            lines.append(f"- `{tok}` → I will {will}")
    return "\n".join(lines).rstrip()


def tokens_from_means(
    options: Sequence[str],
    *,
    means_sep: str = " — ",
    default_will: str = "continue",
) -> list[TokenAction]:
    """Turn brief option lines (``token — means``) into TokenActions."""
    out: list[TokenAction] = []
    for raw in options:
        choice, _sep, means = (raw or "").partition(means_sep)
        tok = choice.strip()
        if not tok:
            continue
        will = (means or default_will).strip() or default_will
        out.append(TokenAction(token=tok, agent_will=will))
    return out


def tokens_from_reply(
    reply_tokens: Sequence[str],
    *,
    wills: Optional[dict[str, str]] = None,
    default_will: str = "continue",
) -> list[TokenAction]:
    """Map bare reply tokens to TokenActions (optional per-token wills)."""
    mapping = {k.lower(): v for k, v in (wills or {}).items()}
    out: list[TokenAction] = []
    for raw in reply_tokens:
        tok = (raw or "").strip()
        if not tok:
            continue
        will = mapping.get(tok.lower(), default_will)
        out.append(TokenAction(token=tok, agent_will=will))
    return out
