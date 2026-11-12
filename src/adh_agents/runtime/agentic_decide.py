"""Platform agentic decide — prompt Hermes → extract → allow-list.

Used by every hired role programme for catalogue outcomes and brief recommends.
"""

from __future__ import annotations

from typing import Sequence

from src.adh_agents.runtime.agentic_extract import extract_allowed, extract_line, match_allowed
from src.configs.hermes_settings import HermesSettings
from src.infra_services.litellm_service import LiteLLMService


async def decide_catalogue_outcome(
    litellm: LiteLLMService,
    *,
    role_id: str,
    node_id: str,
    initiative: str,
    allowed_outcomes: Sequence[str],
    evidence: str,
) -> str:
    """Prompt → extract ``outcome:`` ∈ allowed. Fail closed to ``failed``/``blocked`` if listed."""
    allowed = [o.strip() for o in allowed_outcomes if (o or "").strip()]
    if not allowed:
        raise ValueError(f"node {node_id!r} has no outcomes to decide")

    hermes = HermesSettings.get_instance()
    model = (hermes.eng_model or hermes.pm_model or hermes.model or "qwen").strip()
    prompt = "\n".join(
        [
            f"You are `{role_id}` deciding the workflow.yaml outcome for node `{node_id}`",
            f"on initiative `{initiative}`.",
            "Allowed outcomes (pick exactly one):",
            ", ".join(f"`{o}`" for o in allowed),
            "",
            "Evidence (skill/forge/Hermes output excerpt):",
            (evidence or "")[:12000] or "(none)",
            "",
            "Emit ONLY labeled lines:",
            "outcome: <exactly one allowed outcome>",
            "why: <one sentence>",
        ]
    )
    text = await litellm.complete(
        "Decide one catalogue outcome. Emit labeled lines only.",
        prompt,
        model=model,
        temperature=0.2,
    )
    picked = extract_allowed(text or "", field="outcome", allowed=allowed)
    if picked:
        return picked
    if "failed" in allowed:
        return "failed"
    if "blocked" in allowed:
        return "blocked"
    # Last resort: do not invent mid-hop pass — return first only when nothing else.
    return allowed[0]


async def decide_reply_token(
    litellm: LiteLLMService,
    *,
    role_id: str,
    purpose: str,
    initiative: str,
    reply_tokens: Sequence[str],
    context: str,
    system: str = "",
) -> dict[str, str | list[str]]:
    """Single-shot recommend decide (non-debate). Returns recommend/bluf/example/…"""
    tokens = [t.strip() for t in reply_tokens if (t or "").strip()]
    if not tokens:
        raise ValueError("decide_reply_token requires reply_tokens")
    hermes = HermesSettings.get_instance()
    model = (hermes.eng_model or hermes.pm_model or hermes.model or "qwen").strip()
    prompt = "\n".join(
        [
            f"You are `{role_id}` deciding `{purpose}` for `{initiative}`.",
            "Allowed reply tokens (recommend MUST be exactly one):",
            ", ".join(f"`{t}`" for t in tokens),
            "",
            "Context:",
            (context or "")[:12000],
            "",
            "Emit ONLY labeled lines:",
            "recommend: <exactly one allowed reply token>",
            "example: reply `<same token>` — <one line>",
            "bluf: <one sentence>",
            "locking: <short phrase>",
            "not_locking: <short phrase>",
            "revise_if: <short phrase>",
        ]
    )
    text = await litellm.complete(
        system or "Decide one reply token. Emit labeled lines only.",
        prompt,
        model=model,
        temperature=0.3,
    )
    recommend = extract_allowed(text or "", field="recommend", allowed=tokens)
    if recommend is None:
        recommend = extract_allowed(text or "", field="decision", allowed=tokens)
    if recommend is None:
        hold = next((t for t in tokens if t.lower() == "hold"), tokens[0])
        recommend = hold
    return {
        "recommend": recommend,
        "bluf": extract_line(text or "", "bluf"),
        "example": extract_line(text or "", "example") or f"reply `{recommend}`",
        "locking": (
            [extract_line(text or "", "locking")] if extract_line(text or "", "locking") else []
        ),
        "not_locking": (
            [extract_line(text or "", "not_locking")]
            if extract_line(text or "", "not_locking")
            else []
        ),
        "revise_if": (
            [extract_line(text or "", "revise_if")] if extract_line(text or "", "revise_if") else []
        ),
        "raw": text or "",
    }


def recommend_from_body(body: str, allowed: Sequence[str]) -> str | None:
    """Extract recommend/decision from an already-produced Hermes body."""
    return extract_allowed(body, field="recommend", allowed=allowed) or extract_allowed(
        body, field="decision", allowed=allowed
    )


def assert_allowed_or_none(raw: str, allowed: Sequence[str]) -> str | None:
    return match_allowed(raw, allowed)
