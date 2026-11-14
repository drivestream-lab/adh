"""Outer Hermes review for Coder wave gates (PromptService-only — C.8 / C.18)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.adh_agents.collaboration.human_replies import WAVE_ACCEPTED
from src.configs.hermes_settings import HermesSettings
from src.infra_services.prompt_service import PromptService
from src.models.prompt_models import HermesCoderWaveReviewResponse


@dataclass
class CoderReviewResult:
    recommend: str
    bluf: str
    example: str
    locking: list[str] = field(default_factory=list)
    not_locking: list[str] = field(default_factory=list)
    revise_if: list[str] = field(default_factory=list)
    mdc_findings: list[dict[str, str]] = field(default_factory=list)
    coverage: list[dict[str, str]] = field(default_factory=list)
    template_id: str = "hermes.coder.wave.review"
    raw: Optional[HermesCoderWaveReviewResponse] = None


async def run_wave_review(
    prompts: PromptService,
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    purpose: str,
    reply_tokens: list[str],
    tip_excerpt: str = "",
    spec_excerpt: str = "",
    fixture_index: str = "",
    kb_excerpt: str = "",
    role_id: str = "adh.coder",
) -> CoderReviewResult:
    """Always produce a brief — human awaits; god plays recommend."""
    hermes = HermesSettings.get_instance()
    model = (hermes.eng_model or hermes.pm_model or hermes.model or "qwen").strip()
    try:
        run = await prompts.complete(
            "hermes.coder.wave.review",
            {
                "role_id": role_id,
                "initiative": initiative,
                "wave_id": wave_id,
                "repo": repo,
                "purpose": purpose,
                "reply_tokens": ", ".join(reply_tokens),
                "tip_excerpt": tip_excerpt or "(none)",
                "spec_excerpt": spec_excerpt or "(none)",
                "fixture_index": fixture_index or "(none)",
                "kb_excerpt": kb_excerpt or "(none)",
            },
            model=model,
        )
        parsed = HermesCoderWaveReviewResponse.model_validate(run.parsed or {})
    except Exception:
        return CoderReviewResult(
            recommend="hold",
            bluf="Hermes wave review failed schema — parking for Lead.",
            example="reply `hold`",
        )

    rec = (parsed.recommend or "").strip() or WAVE_ACCEPTED
    blocking = [
        f
        for f in parsed.mdc_findings
        if (f.severity or "").upper() in {"P0", "P1"} and (f.note or "").strip()
    ]
    if blocking and rec.lower() in {WAVE_ACCEPTED, "wave-accepted", "accept wave"}:
        rec = "another round"
    return CoderReviewResult(
        recommend=rec,
        bluf=(parsed.bluf or "").strip(),
        example=(parsed.example or "").strip(),
        locking=list(parsed.locking or []),
        not_locking=list(parsed.not_locking or []),
        revise_if=list(parsed.revise_if or []),
        mdc_findings=[
            {"severity": f.severity, "note": f.note, "defer_why": f.defer_why}
            for f in parsed.mdc_findings
        ],
        coverage=[
            {
                "id": c.id,
                "human_title": c.human_title,
                "fixture_path": c.fixture_path,
                "covers": c.covers,
                "prove_status": c.prove_status,
            }
            for c in parsed.coverage
        ],
        raw=parsed,
    )
