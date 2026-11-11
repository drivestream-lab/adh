"""Human rewind ladder — can / cannot / outside (pure; no I/O).

God and post–product-merge always yield an empty ``can`` list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence

from src.adh_agents.collaboration.temp_papers import PurgeEvent


class RewindTargetId(str, Enum):
    GATE_REOPEN = "gate-reopen"
    AUTHORING_PROMOTE = "authoring-promote"
    AUTHORING_QUALITY = "authoring-quality"
    AUTHORING_THINK = "authoring-think"
    START = "start"
    PRD_IMPACT_ACCEPTANCE = "prd-impact-acceptance"
    PRD_IMPACT_MAP = "prd-impact-map"
    PRD_PR_ACTION = "prd-pr-action"


# Pipeline order (earliest → latest). Post-merge is past the last entry.
_PIPELINE: tuple[RewindTargetId, ...] = (
    RewindTargetId.START,
    RewindTargetId.AUTHORING_THINK,
    RewindTargetId.AUTHORING_QUALITY,
    RewindTargetId.AUTHORING_PROMOTE,
    RewindTargetId.PRD_IMPACT_ACCEPTANCE,
    RewindTargetId.PRD_IMPACT_MAP,
    RewindTargetId.PRD_PR_ACTION,
)

_PURGE_FOR_TARGET: dict[RewindTargetId, PurgeEvent] = {
    RewindTargetId.GATE_REOPEN: PurgeEvent.REWIND_GATE_REOPEN,
    RewindTargetId.AUTHORING_PROMOTE: PurgeEvent.REWIND_TO_PROMOTE,
    RewindTargetId.AUTHORING_QUALITY: PurgeEvent.REWIND_TO_QUALITY,
    RewindTargetId.AUTHORING_THINK: PurgeEvent.REWIND_TO_THINK,
    RewindTargetId.START: PurgeEvent.REWIND_START,
    RewindTargetId.PRD_IMPACT_ACCEPTANCE: PurgeEvent.REWIND_TO_ACCEPTANCE,
    RewindTargetId.PRD_IMPACT_MAP: PurgeEvent.REWIND_TO_IMPACT_MAP,
    RewindTargetId.PRD_PR_ACTION: PurgeEvent.REWIND_TO_PR_ACTION,
}

_IMPACT: dict[RewindTargetId, str] = {
    RewindTargetId.GATE_REOPEN: "same gate again; keep all artefacts; no PR close",
    RewindTargetId.AUTHORING_PROMOTE: (
        "keep thinks+quality+PRD; purge forward briefs; reopen C-pick; "
        "next promote may overwrite PRD"
    ),
    RewindTargetId.AUTHORING_QUALITY: (
        "keep thinks; purge quality/promote brief + forward; back to quality hop"
    ),
    RewindTargetId.AUTHORING_THINK: (
        "keep existing thinks; purge quality/PRD/forward; resume discovery"
    ),
    RewindTargetId.START: (
        "purge all thinks/quality/PRD/forward; same task room; paste outline again"
    ),
    RewindTargetId.PRD_IMPACT_ACCEPTANCE: (
        "purge post-pm brief + Impact (+ PE/KB temps); keep Resolution; reopen confirm"
    ),
    RewindTargetId.PRD_IMPACT_MAP: "purge Impact-Map (+ PE/KB temps); re-run impact-map",
    RewindTargetId.PRD_PR_ACTION: "purge PE/KB temps; reopen draft-PR authorize",
}

_OUTSIDE_ADH: tuple[str, ...] = (
    "Revert/un-merge on GitHub/git after develop land",
    "Close or edit PRs we did not open / already merged",
    "Fix conflicts, branch protection, CI",
    "Anything not listed under “Can rewind”",
)

# Map live session stage / brief purpose → tip pipeline id (or post-merge sentinel).
_TIP_ALIASES: dict[str, str] = {
    "start": RewindTargetId.START.value,
    "outline": RewindTargetId.START.value,
    "prd-think": RewindTargetId.AUTHORING_THINK.value,
    "authoring-think": RewindTargetId.AUTHORING_THINK.value,
    "authoring-quality": RewindTargetId.AUTHORING_QUALITY.value,
    "authoring-promote": RewindTargetId.AUTHORING_PROMOTE.value,
    "prd-impact-acceptance": RewindTargetId.PRD_IMPACT_ACCEPTANCE.value,
    "prd-impact-map": RewindTargetId.PRD_IMPACT_MAP.value,
    "prd-pr-action": RewindTargetId.PRD_PR_ACTION.value,
    "requirements-clarification": RewindTargetId.PRD_IMPACT_ACCEPTANCE.value,
    "requirements-human-decision": RewindTargetId.PRD_IMPACT_ACCEPTANCE.value,
    "update-manifest": RewindTargetId.PRD_IMPACT_ACCEPTANCE.value,
    "update-documents": RewindTargetId.PRD_IMPACT_ACCEPTANCE.value,
    "prd-merge": "__merged__",
    "prd-merge-sync": "__merged__",
    "task-archive": "__merged__",
}


@dataclass(frozen=True)
class RewindTarget:
    """One reachable rewind destination."""

    id: RewindTargetId
    impact: str
    purge_event: PurgeEvent
    close_prs: bool
    resume_purpose: str  # catalogue purpose to reopen after execute


@dataclass(frozen=True)
class RewindLadder:
    """Coach inputs — always show all three blocks (can may be empty)."""

    tip_purpose: str
    can: tuple[RewindTarget, ...] = ()
    cannot: tuple[str, ...] = ()
    outside: tuple[str, ...] = _OUTSIDE_ADH
    denied: bool = False
    deny_reason: str = ""

    def target_by_index(self, index: int) -> Optional[RewindTarget]:
        if index < 1 or index > len(self.can):
            return None
        return self.can[index - 1]


@dataclass(frozen=True)
class RewindTipFacts:
    """Facts the coach gathers before calling ``build_ladder``."""

    stage: str = ""
    brief_purpose: str = ""
    has_open_gate: bool = False
    merge_sha: str = ""
    has_open_draft_pr: bool = False
    product_landed: bool = False  # traj LAND / merge_sha / stage past merge
    is_god: bool = False
    event_purposes: Sequence[str] = field(default_factory=tuple)


def normalize_tip_purpose(raw: str) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return ""
    return _TIP_ALIASES.get(key, key)


def infer_tip(facts: RewindTipFacts) -> str:
    """Best tip purpose string (pipeline id or ``__merged__``)."""
    if facts.product_landed or (facts.merge_sha or "").strip():
        return "__merged__"
    for candidate in (facts.brief_purpose, facts.stage, *reversed(list(facts.event_purposes))):
        tip = normalize_tip_purpose(candidate)
        if tip == "__merged__":
            return tip
        if tip in {t.value for t in _PIPELINE}:
            return tip
    # Default: if we only have thinks-ish work, tip at promote when gate open there.
    if facts.has_open_gate and normalize_tip_purpose(facts.brief_purpose):
        return normalize_tip_purpose(facts.brief_purpose)
    return RewindTargetId.AUTHORING_THINK.value


def _rank(purpose: str) -> int:
    tip = normalize_tip_purpose(purpose)
    if tip == "__merged__":
        return len(_PIPELINE)
    for i, item in enumerate(_PIPELINE):
        if item.value == tip:
            return i
    return -1


def _resume_purpose(target: RewindTargetId) -> str:
    if target is RewindTargetId.GATE_REOPEN:
        return ""  # caller reuses current brief purpose
    if target is RewindTargetId.START:
        return "start"
    return target.value


def build_ladder(facts: RewindTipFacts) -> RewindLadder:
    """Build can / cannot / outside for one rewind request."""
    outside = _OUTSIDE_ADH
    tip = infer_tip(facts)

    if facts.is_god:
        return RewindLadder(
            tip_purpose=tip,
            can=(),
            cannot=(
                "God mode — rewind disabled (forward recommend or halt only)",
                "Past product merge on develop — git undo is outside ADH",
                "Undoing other people’s commits / force-push / rewriting history",
            ),
            outside=outside,
            denied=True,
            deny_reason="god_mode",
        )

    if tip == "__merged__" or facts.product_landed:
        return RewindLadder(
            tip_purpose="__merged__",
            can=(),
            cannot=(
                "Past product merge on develop — git undo is outside ADH",
                "Targets above the tip / unknown catalogue nodes",
                "Undoing other people’s commits / force-push / rewriting history",
            ),
            outside=outside,
            denied=True,
            deny_reason="post_product_merge",
        )

    tip_rank = _rank(tip)
    if tip_rank < 0:
        tip_rank = _rank(RewindTargetId.AUTHORING_THINK.value)
        tip = RewindTargetId.AUTHORING_THINK.value

    can: list[RewindTarget] = []
    if facts.has_open_gate:
        can.append(
            RewindTarget(
                id=RewindTargetId.GATE_REOPEN,
                impact=_IMPACT[RewindTargetId.GATE_REOPEN],
                purge_event=_PURGE_FOR_TARGET[RewindTargetId.GATE_REOPEN],
                close_prs=False,
                resume_purpose=_resume_purpose(RewindTargetId.GATE_REOPEN),
            )
        )

    # Offer every pipeline target at or before tip (rework current + go back).
    for target in _PIPELINE:
        rank = _rank(target.value)
        if rank < 0 or rank > tip_rank:
            continue
        close = bool(facts.has_open_draft_pr) and rank <= _rank(RewindTargetId.PRD_PR_ACTION.value)
        can.append(
            RewindTarget(
                id=target,
                impact=_IMPACT[target],
                purge_event=_PURGE_FOR_TARGET[target],
                close_prs=close,
                resume_purpose=_resume_purpose(target),
            )
        )

    cannot = (
        "Past product merge on develop — git undo is outside ADH",
        "God mode — rewind disabled",
        "Targets above the current tip / unknown catalogue nodes",
        "Undoing other people’s commits / force-push / rewriting history",
    )
    return RewindLadder(
        tip_purpose=tip,
        can=tuple(can),
        cannot=cannot,
        outside=outside,
        denied=False,
    )


def format_can_block(can: Sequence[RewindTarget]) -> str:
    if not can:
        return "**Can rewind (ADH will do this)**\n_(none — see Cannot / Outside ADH)_"
    lines = ["**Can rewind (ADH will do this)**"]
    for i, target in enumerate(can, start=1):
        extra = "; close open draft PRs we raised" if target.close_prs else ""
        lines.append(f"{i} · `{target.id.value}` — {target.impact}{extra}")
    return "\n".join(lines)


def format_cannot_block(cannot: Iterable[str]) -> str:
    lines = ["**Cannot rewind (ADH will not do this)**"]
    for item in cannot:
        lines.append(f"• {item}")
    return "\n".join(lines)


def format_outside_block(outside: Iterable[str] = _OUTSIDE_ADH) -> str:
    lines = ["**Outside ADH — do manually if needed**"]
    for item in outside:
        lines.append(f"• {item}")
    return "\n".join(lines)


def format_ladder_body(ladder: RewindLadder) -> str:
    parts = [
        format_can_block(ladder.can),
        "",
        format_cannot_block(ladder.cannot),
        "",
        format_outside_block(ladder.outside),
    ]
    return "\n".join(parts).rstrip()
