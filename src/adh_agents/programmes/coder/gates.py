"""Coder GateOpener coaches — wave-acceptance + wave-signoff (human + god)."""

from __future__ import annotations

from typing import Optional

from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import (
    ANOTHER_ROUND,
    ENTER_CLOSEOUT,
    HOLD,
    MERGE_WAVE_PR,
    WAVE_ACCEPTED,
)
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
        f"Prove Draft PR tip for **{initiative}** wave `{wave_id}` on `{repo}` "
        "(fixtures + CAP/J vs PRD/spec; MDC P0/P1 clean)."
    )
    return briefs.build_brief(
        purpose="wave-acceptance",
        node_id="wave-acceptance",
        question=f"Accept wave **{wave_id}** tip for **{initiative}** (`{repo}`)?",
        recommend=recommend or WAVE_ACCEPTED,
        recommend_why=why,
        bluf=why,
        example=example or f"reply `{WAVE_ACCEPTED}`",
        locking=list(locking or ["Named CAP/J coverage vs PRD/spec", "MDC P0/P1 resolved"]),
        not_locking=list(not_locking or ["Merge to integration (that is wave-signoff)"]),
        revise_if=list(revise_if or ["P0/P1 MDC findings", "Missing fixture proof"]),
        reply_tokens=[WAVE_ACCEPTED, ANOTHER_ROUND, HOLD],
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
            f"Wave `{wave_id}` Draft PR ready for **{initiative}** on `{repo}`"
            + (f" ({pr_url})" if pr_url else "")
            + "."
        ),
        recommend=recommend or WAVE_ACCEPTED,
        recommend_why=bluf or "Human proves tip (smoke/fixtures); god plays the same recommend.",
        evidence=pr_url or f"wave `{wave_id}` / `{repo}`",
        outside_adh="Run co-shipped prove scripts / live smoke when P15 applies.",
        example=example or f"reply `{WAVE_ACCEPTED}`",
        tokens=[
            TokenAction(WAVE_ACCEPTED, "human approved tip — park for Pass-2 closeout"),
            TokenAction(ANOTHER_ROUND, "findings → loop-spec again"),
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
        identity_handle="adh.coder",
    )


def wave_signoff_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    pr_url: str = "",
    recommend: str = MERGE_WAVE_PR,
    bluf: str = "",
) -> JudgmentRequest:
    why = bluf or (
        f"Merge/publish wave `{wave_id}` for **{initiative}** on `{repo}` "
        "(approval already happened at wave-acceptance)."
    )
    return briefs.build_brief(
        purpose="wave-signoff",
        node_id="wave-signoff",
        question=f"Merge wave PR for **{initiative}** `{wave_id}` (`{repo}`)?",
        recommend=recommend or MERGE_WAVE_PR,
        recommend_why=why,
        bluf=why,
        example=f"reply `{MERGE_WAVE_PR}`",
        locking=["Accepted tip SHA", "Board Done already recorded"],
        not_locking=["Re-proving acceptance (already gated)"],
        revise_if=["Tip moved after acceptance", "CI red on tip"],
        reply_tokens=[MERGE_WAVE_PR, HOLD],
        artefact_path=pr_url or "",
        card_kind="wave-signoff",
    )


def wave_signoff_coach(
    *,
    initiative: str,
    wave_id: str,
    repo: str,
    pr_url: str = "",
    recommend: str = MERGE_WAVE_PR,
    bluf: str = "",
) -> CoachSpec:
    return CoachSpec(
        i_did=f"Wave `{wave_id}` board Done — merge/publish for **{initiative}** (`{repo}`).",
        recommend=recommend or MERGE_WAVE_PR,
        recommend_why=bluf or "Signoff is merge only — not a second approval.",
        evidence=pr_url or f"wave `{wave_id}`",
        outside_adh="Merge on GitHub if desktop forge is unavailable; record SHA in Buzz.",
        example=f"reply `{MERGE_WAVE_PR}`",
        tokens=[
            TokenAction(MERGE_WAVE_PR, "merge wave PR + sync integration_branch"),
            TokenAction(HOLD, "park — do not merge"),
        ],
        hop="wave-signoff",
        payload={
            "status": "wave_signoff",
            "initiative": initiative,
            "wave_id": wave_id,
            "repo": repo,
            "pr_url": pr_url,
        },
        identity_handle="adh.coder",
    )


def closeout_enter_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    wave_id: str,
    repo: str,
) -> JudgmentRequest:
    return briefs.build_brief(
        purpose="wave-awaiting-closeout",
        node_id="wave-awaiting-closeout",
        question=f"Enter Pass-2 closeout for **{initiative}** wave `{wave_id}`?",
        recommend=ENTER_CLOSEOUT,
        recommend_why="learning-extract → ground-spec → board Done → signoff.",
        bluf="Wave tip accepted — closeout extracts learning then grounds spec.",
        example=f"reply `{ENTER_CLOSEOUT}`",
        locking=["wave-accepted tip"],
        not_locking=["Merge yet"],
        revise_if=["Need another coding round first"],
        reply_tokens=[ENTER_CLOSEOUT, ANOTHER_ROUND, HOLD],
        card_kind="wave-closeout",
    )


def closeout_enter_coach(*, initiative: str, wave_id: str, repo: str) -> CoachSpec:
    return CoachSpec(
        i_did=f"Wave `{wave_id}` accepted for **{initiative}** (`{repo}`) — awaiting closeout.",
        recommend=ENTER_CLOSEOUT,
        recommend_why="Pass-2: learning-extract → ground-spec → Done → signoff.",
        evidence=f"`{wave_id}` / `{repo}`",
        outside_adh="Optional: skim Wave-Execution report before closeout.",
        example=f"reply `{ENTER_CLOSEOUT}`",
        tokens=[
            TokenAction(ENTER_CLOSEOUT, "start learning-extract closeout"),
            TokenAction(ANOTHER_ROUND, "back to loop-spec"),
            TokenAction(HOLD, "park"),
        ],
        hop="wave-awaiting-closeout",
        payload={
            "status": "wave_awaiting_closeout",
            "initiative": initiative,
            "wave_id": wave_id,
            "repo": repo,
        },
        identity_handle="adh.coder",
    )
