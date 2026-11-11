"""Multi-pass / multi-model self-debate for Dev judgment hops.

Cap is configurable (default 4). Effectiveness = converge with a clear recommend
**before** hitting the ceiling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.adh_agents.settings import DevAgentSettings
from src.configs.hermes_settings import HermesSettings
from src.infra_services.litellm_service import LiteLLMService

_REC = re.compile(
    r"(?im)^\s*(?:recommend|final\s*recommend|decision)\s*[:\-]\s*[`*]*(.+?)[`*]*\s*$"
)
_EXAMPLE = re.compile(r"(?im)^\s*example\s*[:\-]\s*(.+)$")


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


@dataclass
class _ParsedPass:
    recommend: str
    bluf: str
    example: str
    locking: list[str]
    not_locking: list[str]
    revise_if: list[str]


async def run_dev_debate(
    litellm: LiteLLMService,
    *,
    purpose: str,
    initiative: str,
    context: str,
    reply_tokens: list[str],
    max_runs: int | None = None,
) -> DebateResult:
    """Debate until a recommend ∈ reply_tokens or ceiling.

    Alternates Hermes eng_model / pm_model across passes (multi-model).
    """
    settings = DevAgentSettings.get_instance()
    hermes = HermesSettings.get_instance()
    cap = int(max_runs if max_runs is not None else settings.max_think_runs)
    cap = max(2, min(8, cap))
    tokens = [t.strip() for t in reply_tokens if (t or "").strip()]
    models = _model_rotation(hermes)

    prior = ""
    result = DebateResult(recommend=tokens[0] if tokens else "", bluf="", example="")
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
        try:
            text = await litellm.complete(
                "You are adh.dev. Converge early with one clear recommend token.",
                prompt,
                model=model,
                temperature=0.3,
            )
        except Exception:
            text = (
                f"recommend: {tokens[0] if tokens else 'hold'}\n"
                f"example: reply `{tokens[0] if tokens else 'hold'}`\n"
                "bluf: Debate pass failed — using first reply token.\n"
            )
        body = (text or "").strip()
        result.raw_passes.append(body)
        result.passes = i
        prior = body
        parsed = _parse_pass(body, tokens)
        if parsed is not None:
            result.recommend = parsed.recommend
            result.bluf = parsed.bluf
            result.example = parsed.example
            result.locking = parsed.locking
            result.not_locking = parsed.not_locking
            result.revise_if = parsed.revise_if
            result.converged_at_pass = i
            result.hit_ceiling = False
            return result

    # Ceiling: best-effort last parse or first token.
    last = _parse_pass(result.raw_passes[-1] if result.raw_passes else "", tokens, loose=True)
    if last:
        result.recommend = last.recommend
        result.bluf = last.bluf or "Hit debate ceiling — review carefully."
        result.example = last.example
        result.locking = last.locking
        result.not_locking = last.not_locking
        result.revise_if = last.revise_if
    else:
        result.recommend = tokens[0] if tokens else "hold"
        result.bluf = "Hit debate ceiling without a clear recommend."
        result.example = f"reply `{result.recommend}`"
    result.converged_at_pass = cap
    result.hit_ceiling = True
    return result


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
            f"You are adh.dev engg-think debating `{purpose}` for `{initiative}`.",
            f"Pass {pass_number}/{max_passes}. {challenge}",
            "Reply tokens (recommend MUST be exactly one of these):",
            ", ".join(f"`{t}`" for t in reply_tokens),
            "",
            "Context:",
            context[:12000],
            "",
            "Prior pass:" if prior else "Prior pass: (none)",
            prior[:8000] if prior else "",
            "",
            "Output markdown with these lines (required):",
            "recommend: <one reply token>",
            "example: reply `<same token>` — <one line of what Lead does>",
            "bluf: <one sentence>",
            "locking: <bullet or short phrase>",
            "not_locking: <bullet or short phrase>",
            "revise_if: <bullet or short phrase>",
            "",
            "Converge early when the recommend is clear — do not pad to max passes.",
        ]
    )


def _parse_pass(body: str, tokens: list[str], *, loose: bool = False) -> _ParsedPass | None:
    text = body or ""
    recommend = ""
    m = _REC.search(text)
    if m:
        recommend = m.group(1).strip().strip("`").strip()
    if not recommend:
        lowered = text.lower()
        for tok in tokens:
            if tok.lower() in lowered:
                recommend = tok
                break
    matched = _match_token(recommend, tokens)
    if matched is None and not loose:
        return None
    if matched is None and tokens:
        matched = tokens[0]
    example_m = _EXAMPLE.search(text)
    example = example_m.group(1).strip() if example_m else (f"reply `{matched}`" if matched else "")
    return _ParsedPass(
        recommend=matched or "",
        bluf=_line_after(text, "bluf") or (text.splitlines()[0][:200] if text else ""),
        example=example,
        locking=_bullets_after(text, "locking"),
        not_locking=_bullets_after(text, "not_locking"),
        revise_if=_bullets_after(text, "revise_if"),
    )


def _match_token(candidate: str, tokens: list[str]) -> str | None:
    c = (candidate or "").strip().lower()
    if not c:
        return None
    for tok in tokens:
        if c == tok.lower() or c.startswith(tok.lower()):
            return tok
    return None


def _line_after(text: str, label: str) -> str:
    pat = re.compile(rf"(?im)^\s*{re.escape(label)}\s*[:\-]\s*(.+)$")
    m = pat.search(text or "")
    return m.group(1).strip() if m else ""


def _bullets_after(text: str, label: str) -> list[str]:
    line = _line_after(text, label)
    if line:
        return [line]
    return []
