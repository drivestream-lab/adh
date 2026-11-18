"""Verify GateOpener coaches — wave-acceptance (pass) + hold-at-cap."""

from __future__ import annotations

from typing import Optional

from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import HOLD, WAVE_ACCEPTED
from src.adh_agents.runtime.gate_opener import CoachSpec
from src.models.hermes.intent_models import JudgmentRequest


def wave_acceptance_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    pr_url: str = "",
    recommend: str = WAVE_ACCEPTED,
    bluf: str = "",
    example: str = "",
    locking: Optional[list[str]] = None,
    not_locking: Optional[list[str]] = None,
    revise_if: Optional[list[str]] = None,
) -> JudgmentRequest:
    why = bluf or (
        f"Verify substantiated tip for **{initiative}** wave `{wave_id}` on `{repo}` "
        "(blackbox + IAC DB evidence)."
    )
    return briefs.build_brief(
        purpose="wave-acceptance",
        node_id="wave-acceptance",
        question=f"Accept verified wave **{wave_id}** for **{initiative}** (`{repo}`)?",
        recommend=recommend or WAVE_ACCEPTED,
        recommend_why=why,
        bluf=why,
        example=example or f"reply `{WAVE_ACCEPTED}`",
        locking=list(locking or ["Blackbox exit green", "DB evidence substantiates CAP/J"]),
        not_locking=list(not_locking or ["Merge to integration (wave-signoff)"]),
        revise_if=list(revise_if or ["Thin evidence", "Lab/overlay not healthy"]),
        reply_tokens=[WAVE_ACCEPTED, HOLD],
        artefact_path=pr_url or "",
        card_kind="wave-acceptance",
    )


def wave_acceptance_coach(
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    pr_url: str = "",
    recommend: str = WAVE_ACCEPTED,
    bluf: str = "",
    example: str = "",
) -> CoachSpec:
    return CoachSpec(
        i_did=(
            f"Verify proved wave `{wave_id}` for **{initiative}** on `{repo}`"
            + (f" ({pr_url})" if pr_url else "")
            + "."
        ),
        recommend=recommend or WAVE_ACCEPTED,
        recommend_why=bluf or "Evidence rollup green; god plays the same recommend.",
        evidence=pr_url or f"wave `{wave_id}` / `{repo}`",
        outside_adh="Lab + product overlay already exercised by Verify.",
        example=example or f"reply `{WAVE_ACCEPTED}`",
        tokens=[
            TokenAction(WAVE_ACCEPTED, "tip accepted — hand Coder Pass-2 closeout"),
            TokenAction(HOLD, "park"),
        ],
        hop="wave-acceptance",
        payload={
            "status": "wave_acceptance",
            "initiative": initiative,
            "wave_id": wave_id,
            "repo": repo,
            "pr_url": pr_url,
        },
        identity_handle="adh.verify",
    )


def hold_cap_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    rounds: int,
    max_rounds: int,
    bluf: str = "",
) -> JudgmentRequest:
    why = bluf or (
        f"Verify↔Coder collaboration hit cap **{rounds}/{max_rounds}** for "
        f"**{initiative}** `{wave_id}` on `{repo}`."
    )
    return briefs.build_brief(
        purpose="wave-acceptance",
        node_id="wave-acceptance",
        question=f"Hold **{initiative}** `{wave_id}` after collab cap?",
        recommend=HOLD,
        recommend_why=why,
        bluf=why,
        example=f"reply `{HOLD}`",
        locking=["Collab round cap exhausted"],
        not_locking=["Silent re-verify without Lead"],
        revise_if=["Raise ADH_VERIFY_MAX_COLLAB_ROUNDS", "Manual tip fix then hire verify"],
        reply_tokens=[HOLD],
        artefact_path="",
        card_kind="verify-collab-cap",
    )


def hold_cap_coach(
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    rounds: int,
    max_rounds: int,
    bluf: str = "",
) -> CoachSpec:
    return CoachSpec(
        i_did=f"Verify collab cap {rounds}/{max_rounds} for `{wave_id}` on `{repo}`.",
        recommend=HOLD,
        recommend_why=bluf or "Hard collaboration cap — Lead decision required.",
        evidence=f"rounds={rounds}/{max_rounds}",
        outside_adh="",
        example=f"reply `{HOLD}`",
        tokens=[TokenAction(HOLD, "park until Lead resets or tip fixed")],
        hop="wave-acceptance",
        payload={
            "status": "verify_collab_cap",
            "initiative": initiative,
            "wave_id": wave_id,
            "repo": repo,
            "rounds": rounds,
            "max_rounds": max_rounds,
        },
        identity_handle="adh.verify",
    )
