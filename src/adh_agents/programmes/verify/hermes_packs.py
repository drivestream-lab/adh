"""Hermes substantiate / RCA for Verify (PromptService-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.adh_agents.collaboration.human_replies import ANOTHER_ROUND, HOLD, WAVE_ACCEPTED
from src.configs.hermes_settings import HermesSettings
from src.infra_services.prompt_service import PromptService
from src.models.prompt_models import HermesBehaviourRecommendResponse


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
    try:
        run = await prompts.complete(
            template_id,
            {
                "role_id": role_id,
                "initiative": initiative,
                "wave_id": wave_id,
                "repo": repo,
                "reply_tokens": ", ".join(reply_tokens),
                "evidence_excerpt": evidence_excerpt or "(none)",
                "coverage_excerpt": coverage_excerpt or "(none)",
            },
            model=model,
        )
        parsed = HermesBehaviourRecommendResponse.model_validate(run.parsed or {})
    except Exception:
        return VerifyHermesResult(
            recommend=HOLD if "substantiate" in template_id else fallback_recommend,
            bluf="Hermes verify pack failed schema — parking for Lead.",
            example=f"reply `{HOLD}`",
            template_id=template_id,
        )
    rec = (parsed.recommend or "").strip() or fallback_recommend
    return VerifyHermesResult(
        recommend=rec,
        bluf=(parsed.bluf or "").strip(),
        example=(parsed.example or "").strip(),
        locking=list(parsed.locking or []),
        not_locking=list(parsed.not_locking or []),
        revise_if=list(parsed.revise_if or []),
        template_id=template_id,
        raw=parsed,
    )
