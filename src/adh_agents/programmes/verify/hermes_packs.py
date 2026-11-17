"""Hermes substantiate / RCA for Verify (PromptService-only).

Purpose: after deploy + ``make verify`` + DB look-ats, the Verify Hermes agent
turns the evidence rollup into a Lead-facing recommend card (same shape as Dev
debate / PE judgment). GateOpener then:

- **god** — auto-plays ``brief.recommend`` when it is an exact reply token
- **human** — Lead reads the brief and posts the token (``wave accepted`` / ``hold``)

Recommend MUST be normalized onto the allowed reply_token list (aliases like
``wave-accepted`` → ``wave accepted``) or god cannot auto-play.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.adh_agents.collaboration.human_replies import (
    ANOTHER_ROUND,
    HOLD,
    WAVE_ACCEPTED,
    normalize_reply,
)
from src.adh_agents.runtime.agentic_extract import match_allowed
from src.configs.hermes_settings import HermesSettings
from src.infra_services.prompt_service import PromptService
from src.logging import get_logger
from src.models.prompt_models import HermesBehaviourRecommendResponse

logger = get_logger()


@dataclass
class VerifyHermesResult:
    recommend: str
    bluf: str
    example: str
    locking: list[str] = field(default_factory=list)
    not_locking: list[str] = field(default_factory=list)
    revise_if: list[str] = field(default_factory=list)
    template_id: str = ""
    raw: Optional[HermesBehaviourRecommendResponse] = None
    used_fallback: bool = False


async def run_substantiate(
    prompts: PromptService,
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    evidence_excerpt: str,
    coverage_excerpt: str = "",
    role_id: str = "adh.verify",
) -> VerifyHermesResult:
    """Green-path pack: evidence → recommend ∈ {wave accepted, hold}."""
    return await _run(
        prompts,
        template_id="hermes.verify.substantiate",
        initiative=initiative,
        wave_id=wave_id,
        repo=repo,
        evidence_excerpt=evidence_excerpt,
        coverage_excerpt=coverage_excerpt,
        reply_tokens=[WAVE_ACCEPTED, HOLD],
        role_id=role_id,
        fallback_recommend=WAVE_ACCEPTED,
    )


async def run_rca(
    prompts: PromptService,
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    evidence_excerpt: str,
    coverage_excerpt: str = "",
    role_id: str = "adh.verify",
) -> VerifyHermesResult:
    """Fail-path pack: evidence → recommend ∈ {another round, hold}."""
    return await _run(
        prompts,
        template_id="hermes.verify.rca",
        initiative=initiative,
        wave_id=wave_id,
        repo=repo,
        evidence_excerpt=evidence_excerpt,
        coverage_excerpt=coverage_excerpt,
        reply_tokens=[ANOTHER_ROUND, HOLD],
        role_id=role_id,
        fallback_recommend=ANOTHER_ROUND,
    )


async def _run(
    prompts: PromptService,
    *,
    template_id: str,
    initiative: str,
    wave_id: str,
    repo: str,
    evidence_excerpt: str,
    coverage_excerpt: str,
    reply_tokens: list[str],
    role_id: str,
    fallback_recommend: str,
) -> VerifyHermesResult:
    hermes = HermesSettings.get_instance()
    model = (hermes.eng_model or hermes.pm_model or hermes.model or "qwen").strip()
    tokens = [t for t in reply_tokens if (t or "").strip()]
    try:
        run = await prompts.complete(
            template_id,
            {
                "role_id": role_id,
                "initiative": initiative,
                "wave_id": wave_id,
                "repo": repo,
                "reply_tokens": ", ".join(f"`{t}`" for t in tokens),
                "evidence_excerpt": evidence_excerpt or "(none)",
                "coverage_excerpt": coverage_excerpt or "(none)",
            },
            model=model,
        )
    except Exception as exc:
        logger.exception(
            "verify hermes complete failed; using fallback recommend",
            template_id=template_id,
            error=str(exc)[:300],
        )
        return _fallback(
            template_id=template_id,
            fallback_recommend=fallback_recommend,
            reason=f"complete/schema failed: {str(exc)[:180]}",
        )

    parsed_dict: dict[str, Any] = dict(run.parsed or {})
    try:
        parsed = HermesBehaviourRecommendResponse.model_validate(parsed_dict)
    except Exception as exc:
        logger.exception(
            "verify hermes parse failed; using fallback recommend",
            template_id=template_id,
            error=str(exc)[:300],
        )
        return _fallback(
            template_id=template_id,
            fallback_recommend=fallback_recommend,
            reason=f"response schema failed: {str(exc)[:180]}",
        )

    raw_rec = (parsed.recommend or "").strip()
    # Same extraction path as Dev debate — recommend must be an allowed token.
    recommend = match_allowed(raw_rec, tokens) or normalize_reply(raw_rec, tokens)
    if recommend is None:
        logger.warning(
            "verify hermes recommend not in reply_tokens; using fallback",
            template_id=template_id,
            raw_recommend=raw_rec[:80],
            tokens=tokens,
        )
        return _fallback(
            template_id=template_id,
            fallback_recommend=fallback_recommend,
            reason=f"recommend {raw_rec!r} not in {tokens}",
            locking=list(parsed.locking or []),
            not_locking=list(parsed.not_locking or []),
            revise_if=list(parsed.revise_if or []),
            bluf_prefix=(parsed.bluf or "").strip(),
        )

    bluf = (parsed.bluf or "").strip() or (
        f"Verify Hermes `{template_id}` recommends `{recommend}` for "
        f"**{initiative}** `{wave_id}` on `{repo}`."
    )
    example = (parsed.example or "").strip() or f"reply `{recommend}`"
    return VerifyHermesResult(
        recommend=recommend,
        bluf=bluf,
        example=example,
        locking=list(parsed.locking or []),
        not_locking=list(parsed.not_locking or []),
        revise_if=list(parsed.revise_if or []),
        template_id=template_id,
        raw=parsed,
        used_fallback=False,
    )


def _fallback(
    *,
    template_id: str,
    fallback_recommend: str,
    reason: str,
    locking: Optional[list[str]] = None,
    not_locking: Optional[list[str]] = None,
    revise_if: Optional[list[str]] = None,
    bluf_prefix: str = "",
) -> VerifyHermesResult:
    prefix = (bluf_prefix or "").strip()
    bluf = (
        f"{prefix} — fallback `{fallback_recommend}` ({reason})."
        if prefix
        else (
            f"Hermes `{template_id}` unavailable — fallback `{fallback_recommend}` "
            f"({reason}). Lead may still override."
        )
    )
    return VerifyHermesResult(
        recommend=fallback_recommend,
        bluf=bluf[:2000],
        example=f"reply `{fallback_recommend}`",
        locking=list(locking or []),
        not_locking=list(not_locking or []),
        revise_if=list(revise_if or []),
        template_id=template_id,
        used_fallback=True,
    )
