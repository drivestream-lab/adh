"""Multi-pass / multi-model self-debate — prompt → platform extract → decide."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.adh_agents.runtime.agentic_extract import extract_allowed, extract_line
from src.adh_agents.settings import DevAgentSettings
from src.configs.hermes_settings import HermesSettings
from src.infra_services.litellm_service import LiteLLMService


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


async def run_dev_debate(
    litellm: LiteLLMService,
    *,
    purpose: str,
    initiative: str,
    context: str,
    reply_tokens: list[str],
    max_runs: int | None = None,
) -> DebateResult:
    """Debate until a recommend ∈ reply_tokens or ceiling."""
    settings = DevAgentSettings.get_instance()
    hermes = HermesSettings.get_instance()
    cap = int(max_runs if max_runs is not None else settings.max_think_runs)
    cap = max(2, min(8, cap))
    tokens = [t.strip() for t in reply_tokens if (t or "").strip()]
    if not tokens:
        raise ValueError("run_dev_debate requires non-empty reply_tokens")
    models = _model_rotation(hermes)

    prior = ""
    result = DebateResult(recommend="", bluf="", example="")
    for i in range(1, cap + 1):
        model = models[(i - 1) % len(models)]
        result.models_used.append(model)
        prompt = _pass_prompt(
            purpose=purpose,
            initiative=initiative,
            context=context,
            reply_tokens=tokens,
            pass_number=i,
            max_passes=cap,
            prior=prior,
        )
        text = await litellm.complete(
            "You are adh.dev. Decide one reply token. Emit labeled lines only.",
            prompt,
            model=model,
            temperature=0.3,
        )
        body = (text or "").strip()
        result.raw_passes.append(body)
        result.passes = i
        prior = body
        parsed = _extract_decision(body, tokens)
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


def _pass_prompt(
    *,
    purpose: str,
    initiative: str,
    context: str,
    reply_tokens: list[str],
    pass_number: int,
    max_passes: int,
    prior: str,
) -> str:
    challenge = (
        "Challenge the prior pass. Prefer a clearer, shorter recommend."
        if prior
        else "First pass: propose a clear recommend."
    )
    return "\n".join(
        [
            f"You are adh.dev debating `{purpose}` for `{initiative}`.",
            f"Pass {pass_number}/{max_passes}. {challenge}",
            "Allowed reply tokens (recommend MUST be exactly one):",
            ", ".join(f"`{t}`" for t in reply_tokens),
            "",
            "Context:",
            context[:12000],
            "",
            "Prior pass:" if prior else "Prior pass: (none)",
            prior[:8000] if prior else "",
            "",
            "Emit ONLY these labeled lines (platform extract contract):",
            "recommend: <exactly one allowed reply token>",
            "example: reply `<same token>` — <one line>",
            "bluf: <one sentence>",
            "locking: <short phrase>",
            "not_locking: <short phrase>",
            "revise_if: <short phrase>",
            "",
            "Converge early when recommend is clear — do not pad to max passes.",
        ]
    )
