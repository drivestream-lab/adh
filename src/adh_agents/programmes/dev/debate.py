"""Multi-pass self-debate — Hermes prompt pack → extract → allow-list decide."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.adh_agents.runtime.agentic_extract import extract_allowed, extract_line, match_allowed
from src.adh_agents.settings import DevAgentSettings
from src.configs.hermes_settings import HermesSettings
from src.infra_services.prompt_service import PromptService

_TEMPLATE = "hermes.dev.debate.pass"


@dataclass
class DebateResult:
    recommend: str
    bluf: str
    example: str
    locking: list[str] = field(default_factory=list)
    not_locking: list[str] = field(default_factory=list)
    revise_if: list[str] = field(default_factory=list)
    passes: int = 0
    converged_at_pass: int = 0
    hit_ceiling: bool = False
    models_used: list[str] = field(default_factory=list)
    raw_passes: list[str] = field(default_factory=list)
    template_id: str = _TEMPLATE


async def run_dev_debate(
    prompts: PromptService,
    *,
    purpose: str,
    initiative: str,
    context: str,
    reply_tokens: list[str],
    max_runs: int | None = None,
    kb_excerpt: str = "",
) -> DebateResult:
    """Debate until a recommend ∈ reply_tokens or ceiling — PromptService only."""
    settings = DevAgentSettings.get_instance()
    hermes = HermesSettings.get_instance()
    cap = int(max_runs if max_runs is not None else settings.max_think_runs)
    cap = max(2, min(8, cap))
    tokens = [t.strip() for t in reply_tokens if (t or "").strip()]
    if not tokens:
        raise ValueError("run_dev_debate requires non-empty reply_tokens")
    models = _model_rotation(hermes)

    prior = "(none)"
    result = DebateResult(recommend="", bluf="", example="")
    for i in range(1, cap + 1):
        model = models[(i - 1) % len(models)]
        result.models_used.append(model)
        challenge = (
            "Challenge the prior pass. Prefer a clearer, shorter recommend."
            if prior != "(none)"
            else "First pass: propose a clear recommend."
        )
        run = await prompts.complete(
            _TEMPLATE,
            {
                "purpose": purpose,
                "initiative": initiative,
                "context": (context or "")[:12000] or "(none)",
                "reply_tokens": ", ".join(f"`{t}`" for t in tokens),
                "pass_number": str(i),
                "max_passes": str(cap),
                "prior": (prior or "(none)")[:8000],
                "challenge": challenge,
                "kb_excerpt": (kb_excerpt or "").strip()[:6000] or "(none)",
            },
            model=model,
        )
        body = (run.raw or "").strip()
        result.raw_passes.append(body)
        result.passes = i
        prior = body or "(none)"
        parsed = _decision_from_parsed(run.parsed, tokens) or _extract_decision(body, tokens)
        if parsed is None:
            continue
        result.recommend = parsed["recommend"]
        result.bluf = parsed["bluf"]
        result.example = parsed["example"]
        result.locking = parsed["locking"]
        result.not_locking = parsed["not_locking"]
        result.revise_if = parsed["revise_if"]
        result.converged_at_pass = i
        result.hit_ceiling = False
        return result

    last = _extract_decision(result.raw_passes[-1] if result.raw_passes else "", tokens)
    if last:
        result.recommend = last["recommend"]
        result.bluf = last["bluf"] or "Hit debate ceiling — review carefully."
        result.example = last["example"]
        result.locking = last["locking"]
        result.not_locking = last["not_locking"]
        result.revise_if = last["revise_if"]
    else:
        hold = next((t for t in tokens if t.lower() == "hold"), tokens[0])
        result.recommend = hold
        result.bluf = "Hit debate ceiling without an extractable recommend ∈ reply_tokens."
        result.example = f"reply `{hold}`"
    result.converged_at_pass = cap
    result.hit_ceiling = True
    return result


def _decision_from_parsed(parsed: dict[str, Any] | None, tokens: list[str]) -> dict | None:
    if not isinstance(parsed, dict):
        return None
    raw_rec = str(parsed.get("recommend") or "").strip()
    recommend = match_allowed(raw_rec, tokens)
    if recommend is None:
        return None
    locking = parsed.get("locking") or []
    not_locking = parsed.get("not_locking") or []
    revise_if = parsed.get("revise_if") or []
    if isinstance(locking, str):
        locking = [locking] if locking else []
    if isinstance(not_locking, str):
        not_locking = [not_locking] if not_locking else []
    if isinstance(revise_if, str):
        revise_if = [revise_if] if revise_if else []
    example = str(parsed.get("example") or "").strip() or f"reply `{recommend}`"
    return {
        "recommend": recommend,
        "bluf": str(parsed.get("bluf") or "").strip(),
        "example": example,
        "locking": [str(x) for x in locking if str(x).strip()],
        "not_locking": [str(x) for x in not_locking if str(x).strip()],
        "revise_if": [str(x) for x in revise_if if str(x).strip()],
    }


def _extract_decision(body: str, tokens: list[str]) -> dict | None:
    recommend = extract_allowed(body, field="recommend", allowed=tokens)
    if recommend is None:
        recommend = extract_allowed(body, field="decision", allowed=tokens)
    if recommend is None:
        return None
    bluf = extract_line(body, "bluf")
    example = extract_line(body, "example") or f"reply `{recommend}`"
    locking = extract_line(body, "locking")
    not_locking = extract_line(body, "not_locking")
    revise_if = extract_line(body, "revise_if")
    return {
        "recommend": recommend,
        "bluf": bluf,
        "example": example,
        "locking": [locking] if locking else [],
        "not_locking": [not_locking] if not_locking else [],
        "revise_if": [revise_if] if revise_if else [],
    }


def _model_rotation(hermes: HermesSettings) -> list[str]:
    eng = (hermes.eng_model or hermes.model or "qwen").strip()
    pm = (hermes.pm_model or hermes.model or eng).strip()
    if eng == pm:
        return [eng]
    return [eng, pm]
