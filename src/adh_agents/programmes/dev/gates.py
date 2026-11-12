"""Dev GateOpener coaches — YAML human-checkpoints + explicit forge authorizes."""

from __future__ import annotations

from typing import Optional

from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import (
    ACCEPT_TDD_ADR,
    ANOTHER_ROUND,
    AUTHORIZE_BOARD,
    CODING_READY,
    HOLD,
    MERGE_SPEC_PR,
)
from src.adh_agents.programmes.dev.debate import DebateResult
from src.adh_agents.runtime.gate_opener import CoachSpec
from src.adh_agents.runtime.work_models import AgentWorkSession
from src.models.hermes.intent_models import JudgmentRequest


def _debate_payload(debate: Optional[DebateResult]) -> dict:
    if debate is None:
        return {}
    return {
        "dev_think_passes": debate.passes,
        "converged_at_pass": debate.converged_at_pass,
        "hit_ceiling": debate.hit_ceiling,
        "models_used": list(debate.models_used),
    }


def tdd_adr_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    artefact: str,
    debate: Optional[DebateResult] = None,
) -> JudgmentRequest:
    recommend = (debate.recommend if debate else "") or ACCEPT_TDD_ADR
    bluf = (debate.bluf if debate else "") or (
        "Architecture + test intent lock before implementation plan."
    )
    return briefs.build_brief(
        purpose="tdd-adr-acceptance",
        node_id="technical-review-approval",
        question=f"Accept TDD/ADR technical review for **{initiative}**?",
        recommend=recommend,
        recommend_why=bluf,
        bluf=bluf,
        example=(debate.example if debate else "") or f"reply `{ACCEPT_TDD_ADR}`",
        locking=list(debate.locking) if debate else ["ADR boundaries / TDD intent"],
        not_locking=list(debate.not_locking) if debate else ["Exact ticket wording"],
        revise_if=list(debate.revise_if) if debate else ["PRD scope change"],
        reply_tokens=[ACCEPT_TDD_ADR, ANOTHER_ROUND, HOLD],
        artefact_path=artefact,
        card_kind="tdd-adr",
    )


def tdd_adr_coach(
    *, initiative: str, artefact: str, debate: Optional[DebateResult] = None
) -> CoachSpec:
    recommend = (debate.recommend if debate else "") or ACCEPT_TDD_ADR
    return CoachSpec(
        i_did=f"Technical review ready for **{initiative}** (`{artefact}`).",
        recommend=recommend,
        recommend_why=(debate.bluf if debate else "")
        or "Accept ADR/TDD before plan (YAML technical-review-approval).",
        evidence=f"`{artefact}`",
        outside_adh="Read ADR/API why cards; do not invent architecture on the board.",
        example=(debate.example if debate else "") or f"reply `{ACCEPT_TDD_ADR}`",
        tokens=[
            TokenAction(ACCEPT_TDD_ADR, "accept TDD/ADR — advance to implementation plan"),
            TokenAction(ANOTHER_ROUND, "findings → re-run spec-technical-review"),
            TokenAction(HOLD, "park"),
        ],
        hop="tdd-adr-acceptance",
        payload={
            "status": "tdd_adr_acceptance",
            "initiative": initiative,
            **_debate_payload(debate),
        },
    )


def coding_ready_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    plan_path: str,
    debate: Optional[DebateResult] = None,
) -> JudgmentRequest:
    recommend = (debate.recommend if debate else "") or CODING_READY
    bluf = (debate.bluf if debate else "") or (
        "Accepts implementation plan + WorkManifest readiness — not that proofs already ran."
    )
    return briefs.build_brief(
        purpose="coding-readiness",
        node_id="coding-readiness",
        question=f"Coding-ready for **{initiative}**? (plan + WorkManifest)",
        recommend=recommend,
        recommend_why=bluf,
        bluf=bluf,
        example=(debate.example if debate else "") or f"reply `{CODING_READY}`",
        locking=list(debate.locking) if debate else ["WorkManifest honesty"],
        not_locking=list(debate.not_locking) if debate else ["CI green (run later)"],
        revise_if=list(debate.revise_if) if debate else ["Missing plan / WM"],
        reply_tokens=[CODING_READY, ANOTHER_ROUND, HOLD],
        artefact_path=plan_path,
        card_kind="coding-readiness",
    )


def coding_ready_coach(
    *,
    initiative: str,
    plan_path: str,
    debate: Optional[DebateResult] = None,
) -> CoachSpec:
    recommend = (debate.recommend if debate else "") or CODING_READY
    return CoachSpec(
        i_did=(f"Implementation plan ready for **{initiative}** (`{plan_path}`)."),
        recommend=recommend,
        recommend_why=(debate.bluf if debate else "")
        or "Unlocks YAML spec-merge → board authorize.",
        evidence=f"`{plan_path}`",
        outside_adh="Confirm plan + WorkManifest; Dev does not run full verify yet.",
        example=(debate.example if debate else "") or f"reply `{CODING_READY}`",
        tokens=[
            TokenAction(CODING_READY, "mark coding-ready — proceed to spec-merge"),
            TokenAction(ANOTHER_ROUND, "findings → re-run technical review / plan"),
            TokenAction(HOLD, "park"),
        ],
        hop="coding-readiness",
        payload={"status": "coding_readiness", "initiative": initiative, **_debate_payload(debate)},
    )


def spec_merge_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    pr_urls: str,
    debate: Optional[DebateResult] = None,
) -> JudgmentRequest:
    recommend = (debate.recommend if debate else "") or MERGE_SPEC_PR
    bluf = (debate.bluf if debate else "") or (
        "Land draft spec PRs on impacted repos before board seed."
    )
    return briefs.build_brief(
        purpose="spec-merge",
        node_id="spec-merge",
        question=f"Merge spec PR(s) for **{initiative}**?",
        recommend=recommend,
        recommend_why=bluf,
        bluf=bluf,
        example=(debate.example if debate else "") or f"reply `{MERGE_SPEC_PR}`",
        locking=list(debate.locking) if debate else ["Spec tip on develop"],
        not_locking=list(debate.not_locking) if debate else ["Board ticket titles"],
        revise_if=list(debate.revise_if) if debate else ["Spec still draft-wrong"],
        reply_tokens=[MERGE_SPEC_PR, "go ahead", HOLD],
        artefact_path=pr_urls,
        card_kind="spec-merge",
    )


def spec_merge_coach(
    *, initiative: str, pr_urls: str, debate: Optional[DebateResult] = None
) -> CoachSpec:
    recommend = (debate.recommend if debate else "") or MERGE_SPEC_PR
    return CoachSpec(
        i_did=f"Spec draft PR(s) ready to land for **{initiative}**: {pr_urls or '(none)'}",
        recommend=recommend,
        recommend_why=(debate.bluf if debate else "")
        or "YAML spec-merge is explicit — then board-tickets-action.",
        evidence=pr_urls or "(no PR urls yet)",
        outside_adh="Skim the draft spec PRs on GitHub before authorizing merge.",
        example=(debate.example if debate else "") or f"reply `{MERGE_SPEC_PR}`",
        tokens=[
            TokenAction(MERGE_SPEC_PR, "undraft + merge spec PR(s)"),
            TokenAction("go ahead", "same as merge the spec PR"),
            TokenAction(HOLD, "park — no merge yet"),
        ],
        hop="spec-merge",
        payload={
            "status": "spec_merge_authorize",
            "initiative": initiative,
            **_debate_payload(debate),
        },
    )


def board_authorize_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    debate: Optional[DebateResult] = None,
) -> JudgmentRequest:
    recommend = (debate.recommend if debate else "") or AUTHORIZE_BOARD
    bluf = (debate.bluf if debate else "") or (
        "Dev E1 fence = board tickets seeded from WorkManifest after spec-merge."
    )
    return briefs.build_brief(
        purpose="board-tickets-action",
        node_id="board-tickets-action",
        question=f"Authorize board ticket seed for **{initiative}**?",
        recommend=recommend,
        recommend_why=bluf,
        bluf=bluf,
        example=(debate.example if debate else "") or f"reply `{AUTHORIZE_BOARD}`",
        locking=list(debate.locking) if debate else ["WorkManifest → tickets"],
        not_locking=list(debate.not_locking) if debate else ["Coder assignment"],
        revise_if=list(debate.revise_if) if debate else ["Plan superseded"],
        reply_tokens=[AUTHORIZE_BOARD, HOLD],
        card_kind="board",
    )


def board_authorize_coach(*, initiative: str, debate: Optional[DebateResult] = None) -> CoachSpec:
    recommend = (debate.recommend if debate else "") or AUTHORIZE_BOARD
    return CoachSpec(
        i_did=f"Coding-ready + spec merged for **{initiative}** — ready to seed board tickets.",
        recommend=recommend,
        recommend_why=(debate.bluf if debate else "")
        or "Seeds board from plan/WorkManifest; coder hire is later.",
        outside_adh=(
            "Do not hand-create board tickets; authorize here so Dev seeds them. "
            "After a false or superseded seed, reply `reseed board` (tickets only) "
            "or `revise engg` (full spine from spec-draft)."
        ),
        example=(debate.example if debate else "") or f"reply `{AUTHORIZE_BOARD}`",
        tokens=[
            TokenAction(AUTHORIZE_BOARD, "run create-board-tickets"),
            TokenAction(HOLD, "park — no board seed yet"),
        ],
        hop="board-tickets-action",
        payload={"status": "board_authorize", "initiative": initiative, **_debate_payload(debate)},
    )


def stage_of(session: AgentWorkSession) -> str:
    return (session.stage or "").strip()
