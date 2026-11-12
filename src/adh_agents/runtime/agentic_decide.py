"""Platform agentic decide — Hermes prompt pack → extract → allow-list.

Used by every hired role programme for catalogue outcomes and brief recommends.
Prompt bodies live only under ``src/prompts/hermes.*.yaml`` (PromptService).
"""

from __future__ import annotations

from typing import Sequence

from src.adh_agents.runtime.agentic_extract import extract_allowed, extract_line, match_allowed
from src.configs.hermes_settings import HermesSettings
from src.infra_services.prompt_service import PromptService

_OUTCOME = "hermes.dev.decide.outcome"
_REPLY = "hermes.dev.decide.reply"


async def decide_catalogue_outcome(
    prompts: PromptService,
    *,
    role_id: str,
    node_id: str,
    initiative: str,
    allowed_outcomes: Sequence[str],
    evidence: str,
    kb_excerpt: str = "",
) -> str:
    """Prompt pack → extract ``outcome`` ∈ allowed. Fail closed to failed/blocked if listed."""
    allowed = [o.strip() for o in allowed_outcomes if (o or "").strip()]
    if not allowed:
        raise ValueError(f"node {node_id!r} has no outcomes to decide")

    hermes = HermesSettings.get_instance()
    model = (hermes.eng_model or hermes.pm_model or hermes.model or "qwen").strip()
    run = await prompts.complete(
        _OUTCOME,
        {
            "role_id": role_id,
            "node_id": node_id,
            "initiative": initiative,
            "allowed_outcomes": ", ".join(f"`{o}`" for o in allowed),
            "evidence": (evidence or "")[:12000] or "(none)",
            "kb_excerpt": (kb_excerpt or "").strip()[:6000] or "(none)",
        },
        model=model,
    )
    picked = match_allowed(str((run.parsed or {}).get("outcome") or ""), allowed)
    if picked is None:
        picked = extract_allowed(run.raw or "", field="outcome", allowed=allowed)
    if picked:
        return picked
    if "failed" in allowed:
        return "failed"
    if "blocked" in allowed:
        return "blocked"
    return allowed[0]


async def decide_reply_token(
    prompts: PromptService,
    *,
    role_id: str,
    purpose: str,
    initiative: str,
    reply_tokens: Sequence[str],
    context: str,
    kb_excerpt: str = "",
) -> dict[str, str | list[str]]:
    """Single-shot recommend decide (non-debate). Returns recommend/bluf/example/…"""
    tokens = [t.strip() for t in reply_tokens if (t or "").strip()]
    if not tokens:
        raise ValueError("decide_reply_token requires reply_tokens")
    hermes = HermesSettings.get_instance()
    model = (hermes.eng_model or hermes.pm_model or hermes.model or "qwen").strip()
    run = await prompts.complete(
        _REPLY,
        {
            "role_id": role_id,
            "purpose": purpose,
            "initiative": initiative,
            "reply_tokens": ", ".join(f"`{t}`" for t in tokens),
            "context": (context or "")[:12000] or "(none)",
            "kb_excerpt": (kb_excerpt or "").strip()[:6000] or "(none)",
        },
        model=model,
    )
    parsed = run.parsed or {}
    recommend = match_allowed(str(parsed.get("recommend") or ""), tokens)
    if recommend is None:
        recommend = extract_allowed(run.raw or "", field="recommend", allowed=tokens)
    if recommend is None:
        recommend = extract_allowed(run.raw or "", field="decision", allowed=tokens)
    if recommend is None:
        hold = next((t for t in tokens if t.lower() == "hold"), tokens[0])
        recommend = hold

    def _list(key: str) -> list[str]:
        raw = parsed.get(key)
        if isinstance(raw, list):
            return [str(x) for x in raw if str(x).strip()]
        line = extract_line(run.raw or "", key)
        return [line] if line else []

    return {
        "recommend": recommend,
        "bluf": str(parsed.get("bluf") or extract_line(run.raw or "", "bluf") or ""),
        "example": str(
            parsed.get("example")
            or extract_line(run.raw or "", "example")
            or f"reply `{recommend}`"
        ),
        "locking": _list("locking"),
        "not_locking": _list("not_locking"),
        "revise_if": _list("revise_if"),
        "raw": run.raw or "",
        "template_id": run.template_id,
    }


def recommend_from_body(body: str, allowed: Sequence[str]) -> str | None:
    """Extract recommend/decision from an already-produced Hermes body."""
    return extract_allowed(body, field="recommend", allowed=allowed) or extract_allowed(
        body, field="decision", allowed=allowed
    )


def assert_allowed_or_none(raw: str, allowed: Sequence[str]) -> str | None:
    return match_allowed(raw, allowed)
