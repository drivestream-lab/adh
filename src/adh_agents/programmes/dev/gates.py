"""Dev GateOpener coaches — god-safe recommends ∈ reply_tokens."""

from __future__ import annotations

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
from src.adh_agents.runtime.gate_opener import CoachSpec
from src.adh_agents.runtime.work_models import AgentWorkSession
from src.models.hermes.intent_models import JudgmentRequest


def deps_acceptance_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    artefact: str,
) -> JudgmentRequest:
    return briefs.build_brief(
        purpose="deps-acceptance",
        node_id="deps-acceptance",
        question=f"Accept Engg-Deps DAG for **{initiative}**?",
        recommend=ACCEPT_DEPS,
        recommend_why="DAG/tiers must be visible before ADR/plan accept.",
        bluf="Accept only when tiers + repos look right for board wave order.",
        reply_tokens=[ACCEPT_DEPS, ANOTHER_ROUND, HOLD],
        artefact_path=artefact,
        card_kind="deps",
    )


def deps_acceptance_coach(*, initiative: str, artefact: str) -> CoachSpec:
    return CoachSpec(
        i_did=f"Wrote/updated Engg-Deps for **{initiative}** at `{artefact}`.",
        recommend=ACCEPT_DEPS,
        recommend_why="Locks multi-repo mutate order before ADR/TDD + plan.",
        evidence=f"`{artefact}`",
        outside_adh="Skim tiers in Cursor; edit the file if a repo/tier is wrong.",
        tokens=[
            TokenAction(ACCEPT_DEPS, "accept deps DAG for this INIT"),
            TokenAction(ANOTHER_ROUND, "ask Dev to revise Engg-Deps"),
            TokenAction(HOLD, "park — no ADR/plan yet"),
        ],
        hop="deps-acceptance",
        payload={"status": "deps_acceptance", "initiative": initiative, "artefact": artefact},
    )


def tdd_adr_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    artefact: str,
) -> JudgmentRequest:
    return briefs.build_brief(
        purpose="tdd-adr-acceptance",
        node_id="technical-review-approval",
        question=f"Accept TDD/ADR technical review for **{initiative}**?",
        recommend=ACCEPT_TDD_ADR,
        recommend_why="Architecture + test intent lock before implementation plan.",
        reply_tokens=[ACCEPT_TDD_ADR, ANOTHER_ROUND, HOLD],
        artefact_path=artefact,
        card_kind="tdd-adr",
    )


def tdd_adr_coach(*, initiative: str, artefact: str) -> CoachSpec:
    return CoachSpec(
        i_did=f"Technical review ready for **{initiative}** (`{artefact}`).",
        recommend=ACCEPT_TDD_ADR,
        recommend_why="Accept ADR/TDD before plan + verification plan.",
        evidence=f"`{artefact}`",
        outside_adh="Read ADR/API why cards; do not invent architecture on the board.",
        tokens=[
            TokenAction(ACCEPT_TDD_ADR, "accept TDD/ADR for this INIT"),
            TokenAction(ANOTHER_ROUND, "another technical-review pass"),
            TokenAction(HOLD, "park"),
        ],
        hop="tdd-adr-acceptance",
        payload={"status": "tdd_adr_acceptance", "initiative": initiative},
    )


def coding_ready_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
    plan_path: str,
    verification_path: str,
) -> JudgmentRequest:
    return briefs.build_brief(
        purpose="coding-readiness",
        node_id="coding-readiness",
        question=f"Coding-ready for **{initiative}**? (plan + verification **plan**)",
        recommend=CODING_READY,
        recommend_why=("This accepts the verification **plan**, not that proofs already ran."),
        reply_tokens=[CODING_READY, ANOTHER_ROUND, HOLD],
        artefact_path=plan_path,
        card_kind="coding-readiness",
    )


def coding_ready_coach(
    *,
    initiative: str,
    plan_path: str,
    verification_path: str,
) -> CoachSpec:
    return CoachSpec(
        i_did=(
            f"Implementation plan + verification plan ready for **{initiative}** "
            f"(`{plan_path}`, `{verification_path}`)."
        ),
        recommend=CODING_READY,
        recommend_why="Unlocks board seed — proofs still run in CI/human later.",
        evidence=f"`{plan_path}` · `{verification_path}`",
        outside_adh="Confirm coverage table is honest; Dev does not run full verify yet.",
        tokens=[
            TokenAction(CODING_READY, "mark coding-ready — proceed to board authorize"),
            TokenAction(ANOTHER_ROUND, "revise plan / verification plan"),
            TokenAction(HOLD, "park"),
        ],
        hop="coding-readiness",
        payload={"status": "coding_readiness", "initiative": initiative},
    )


def board_authorize_brief(
    briefs: HermesBriefService,
    *,
    initiative: str,
) -> JudgmentRequest:
    return briefs.build_brief(
        purpose="board-tickets-action",
        node_id="board-tickets-action",
        question=f"Authorize board ticket seed for **{initiative}**?",
        recommend=AUTHORIZE_BOARD,
        recommend_why="Dev v1 fence = board tickets seeded from WorkManifest.",
        reply_tokens=[AUTHORIZE_BOARD, HOLD],
        card_kind="board",
    )


def board_authorize_coach(*, initiative: str) -> CoachSpec:
    return CoachSpec(
        i_did=f"Coding-ready for **{initiative}** — ready to seed GitHub board tickets.",
        recommend=AUTHORIZE_BOARD,
        recommend_why="Seeds board from plan/WorkManifest; coder hire is later.",
        outside_adh="Do not hand-create board tickets; authorize here so Dev seeds them.",
        tokens=[
            TokenAction(AUTHORIZE_BOARD, "run create-board-tickets"),
            TokenAction(HOLD, "park — no board seed yet"),
        ],
        hop="board-tickets-action",
        payload={"status": "board_authorize", "initiative": initiative},
    )


def stage_of(session: AgentWorkSession) -> str:
    return (session.stage or "").strip()
