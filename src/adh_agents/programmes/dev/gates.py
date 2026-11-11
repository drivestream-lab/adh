"""Dev GateOpener coaches — god-safe recommends ∈ reply_tokens."""

from __future__ import annotations

from typing import Optional

from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import (
    ACCEPT_DEPS,
    ACCEPT_TDD_ADR,
    ANOTHER_ROUND,
    AUTHORIZE_BOARD,
    CODING_READY,
    HOLD,
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


def deps_acceptance_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    artefact: str,
    debate: Optional[DebateResult] = None,
) -> JudgmentRequest:
    recommend = (debate.recommend if debate else "") or ACCEPT_DEPS
    bluf = (debate.bluf if debate else "") or (
        "Accept only when tiers + repos look right for board wave order."
    )
    example = (debate.example if debate else "") or f"reply `{ACCEPT_DEPS}`"
    return briefs.build_brief(
        purpose="deps-acceptance",
        node_id="deps-acceptance",
        question=f"Accept Engg-Deps DAG for **{initiative}**?",
        recommend=recommend,
        recommend_why=bluf,
        bluf=bluf,
        example=example,
        locking=list(debate.locking) if debate else ["Tier mutate order / DAG"],
        not_locking=list(debate.not_locking) if debate else ["Board ticket titles"],
        revise_if=list(debate.revise_if) if debate else ["New repo appears in Impact-Map"],
        reply_tokens=[ACCEPT_DEPS, ANOTHER_ROUND, HOLD],
        artefact_path=artefact,
        card_kind="deps",
    )


def deps_acceptance_coach(
    *,
    initiative: str,
    artefact: str,
    debate: Optional[DebateResult] = None,
) -> CoachSpec:
    recommend = (debate.recommend if debate else "") or ACCEPT_DEPS
    why = (debate.bluf if debate else "") or (
        "Locks multi-repo mutate order before ADR/TDD + plan."
    )
    example = (debate.example if debate else "") or f"reply `{ACCEPT_DEPS}`"
    passes = debate.passes if debate else 0
    return CoachSpec(
        i_did=(
            f"Wrote/updated Engg-Deps for **{initiative}** at `{artefact}`"
            + (f" (debate {passes} pass{'es' if passes != 1 else ''})." if passes else ".")
        ),
        recommend=recommend,
        recommend_why=why,
        evidence=f"`{artefact}`",
        outside_adh="Skim tiers in Cursor; edit the file if a repo/tier is wrong.",
        example=example,
        tokens=[
            TokenAction(ACCEPT_DEPS, "accept deps DAG for this INIT"),
            TokenAction(ANOTHER_ROUND, "ask Dev to revise Engg-Deps"),
            TokenAction(HOLD, "park — no ADR/plan yet"),
        ],
        hop="deps-acceptance",
        payload={
            "status": "deps_acceptance",
            "initiative": initiative,
            "artefact": artefact,
            **_debate_payload(debate),
        },
    )


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
        or "Accept ADR/TDD before plan + verification plan.",
        evidence=f"`{artefact}`",
        outside_adh="Read ADR/API why cards; do not invent architecture on the board.",
        example=(debate.example if debate else "") or f"reply `{ACCEPT_TDD_ADR}`",
        tokens=[
            TokenAction(ACCEPT_TDD_ADR, "accept TDD/ADR for this INIT"),
            TokenAction(ANOTHER_ROUND, "another technical-review pass"),
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
    verification_path: str,
    debate: Optional[DebateResult] = None,
) -> JudgmentRequest:
    recommend = (debate.recommend if debate else "") or CODING_READY
    bluf = (debate.bluf if debate else "") or (
        "This accepts the verification **plan**, not that proofs already ran."
    )
    return briefs.build_brief(
        purpose="coding-readiness",
        node_id="coding-readiness",
        question=f"Coding-ready for **{initiative}**? (plan + verification **plan**)",
        recommend=recommend,
        recommend_why=bluf,
        bluf=bluf,
        example=(debate.example if debate else "") or f"reply `{CODING_READY}`",
        locking=list(debate.locking) if debate else ["Coverage table honesty"],
        not_locking=list(debate.not_locking) if debate else ["CI green (run later)"],
        revise_if=list(debate.revise_if) if debate else ["Missing proof layer"],
        reply_tokens=[CODING_READY, ANOTHER_ROUND, HOLD],
        artefact_path=plan_path,
        card_kind="coding-readiness",
    )


def coding_ready_coach(
    *,
    initiative: str,
    plan_path: str,
    verification_path: str,
    debate: Optional[DebateResult] = None,
) -> CoachSpec:
    recommend = (debate.recommend if debate else "") or CODING_READY
    return CoachSpec(
        i_did=(
            f"Implementation plan + verification plan ready for **{initiative}** "
            f"(`{plan_path}`, `{verification_path}`)."
        ),
        recommend=recommend,
        recommend_why=(debate.bluf if debate else "")
        or "Unlocks board seed — proofs still run in CI/human later.",
        evidence=f"`{plan_path}` · `{verification_path}`",
        outside_adh="Confirm coverage table is honest; Dev does not run full verify yet.",
        example=(debate.example if debate else "") or f"reply `{CODING_READY}`",
        tokens=[
            TokenAction(CODING_READY, "mark coding-ready — proceed to board authorize"),
            TokenAction(ANOTHER_ROUND, "revise plan / verification plan"),
            TokenAction(HOLD, "park"),
        ],
        hop="coding-readiness",
        payload={"status": "coding_readiness", "initiative": initiative, **_debate_payload(debate)},
    )


def board_authorize_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    debate: Optional[DebateResult] = None,
) -> JudgmentRequest:
    recommend = (debate.recommend if debate else "") or AUTHORIZE_BOARD
    bluf = (debate.bluf if debate else "") or (
        "Dev v1 fence = board tickets seeded from WorkManifest."
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
        i_did=f"Coding-ready for **{initiative}** — ready to seed GitHub board tickets.",
        recommend=recommend,
        recommend_why=(debate.bluf if debate else "")
        or "Seeds board from plan/WorkManifest; coder hire is later.",
        outside_adh="Do not hand-create board tickets; authorize here so Dev seeds them.",
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
