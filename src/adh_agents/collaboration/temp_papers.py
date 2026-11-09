"""Temporary programme papers — global purge strategy (delete, never archive).

Temp papers under ``prd/reports/`` are **working artefacts**, not SSOT.
Durable truth lives in ``prd/{INIT}.md``, forge PRs, and OKF ``knowledge/**``.

Design:
- **Families** name path shapes (authoring scratch, decision briefs, walk rollups, …).
- **Events** are lifecycle points (promote done, Gate‑1 attested, PRD merged, …).
- Any programme gate calls ``resolve_purge_paths(event, …)`` then
  ``workspace.purge_local_paths`` — Gate‑1 is just one event, not a special case.

Do not add gate-private purge helpers. Extend ``TempFamily`` / ``PURGE_MATRIX`` instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from src.infra_services.pm_workspace_service import (
    hermes_gate1_brief_path,
    hermes_post_pm_brief_path,
    hermes_promote_brief_path,
)

# Authoring scratch suffixes — match path shape, not a hardcoded INIT- token.
_THINK = re.compile(r"^prd/reports/(.+)-prd-think(?:-\d+)?\.md$", re.I)
_QUALITY = re.compile(r"^prd/reports/(.+)-prd-quality\.md$", re.I)
_ASK = re.compile(r"^prd/reports/(.+)-prd-ask\.md$", re.I)
_RECOMMEND = re.compile(r"^prd/reports/(.+)-prd-recommend\.md$", re.I)
_AUTHORING_SCRATCH = (_THINK, _QUALITY, _ASK, _RECOMMEND)


class TempFamily(str, Enum):
    """Known temporary artefact families (local meta ``prd/reports/``)."""

    AUTHORING_SCRATCH = "authoring_scratch"  # think / quality / ask / recommend
    PROMOTE_BRIEF = "promote_brief"  # *-hermes-promote-brief.md
    POST_PM_BRIEF = "post_pm_brief"  # *-hermes-post-pm-brief.md
    GATE1_QUESTIONS = "gate1_questions"  # PE-Product-Questions-*.md
    GATE1_BRIEF = "gate1_brief"  # *-hermes-gate1-brief.md
    READ_ROLLUP = "read_rollup"  # *-read-walk-*.md
    KB_ENRICH_BODY = "kb_enrich_body"  # *-kb-enrich-pr-body.md


class PurgeEvent(str, Enum):
    """Lifecycle events — call sites use these, not family names."""

    PROMOTE_DONE = "promote_done"
    POST_PM_DONE = "post_pm_done"
    GATE1_ATTESTED = "gate1_attested"
    PRD_MERGED = "prd_merged"
    KB_ENRICH_DONE = "kb_enrich_done"
    LANE_ABORT = "lane_abort"


# Which families become eligible to delete at each event.
# Read rollups stay until KB enrich consumes them (not purged at PRD_MERGED).
PURGE_MATRIX: dict[PurgeEvent, frozenset[TempFamily]] = {
    PurgeEvent.PROMOTE_DONE: frozenset({TempFamily.AUTHORING_SCRATCH, TempFamily.PROMOTE_BRIEF}),
    PurgeEvent.POST_PM_DONE: frozenset({TempFamily.POST_PM_BRIEF}),
    PurgeEvent.GATE1_ATTESTED: frozenset({TempFamily.GATE1_QUESTIONS, TempFamily.GATE1_BRIEF}),
    PurgeEvent.PRD_MERGED: frozenset(
        {
            TempFamily.GATE1_QUESTIONS,
            TempFamily.GATE1_BRIEF,
            TempFamily.PROMOTE_BRIEF,
            TempFamily.POST_PM_BRIEF,
            TempFamily.AUTHORING_SCRATCH,
        }
    ),
    PurgeEvent.KB_ENRICH_DONE: frozenset({TempFamily.KB_ENRICH_BODY, TempFamily.READ_ROLLUP}),
    PurgeEvent.LANE_ABORT: frozenset(TempFamily),
}


@dataclass(frozen=True)
class PurgeContext:
    """Enough context to resolve family paths for one initiative."""

    initiative: str
    meta_repo: str = ""
    # Workspace inventory / known paths — used to filter AUTHORING_SCRATCH.
    candidates: Sequence[str] = field(default_factory=tuple)


def is_authoring_scratch(path: str, initiative: str) -> bool:
    """True when path is allowlisted pre-promote scratch for this initiative."""
    normalized = path.replace("\\", "/").lstrip("./")
    init = initiative.strip().upper()
    for pattern in _AUTHORING_SCRATCH:
        match = pattern.match(normalized)
        if match and match.group(1).upper() == init:
            return True
    return False


def authoring_scratch_paths(initiative: str, candidates: Iterable[str]) -> list[str]:
    """Allowlisted authoring scratch; never includes durable ``prd/{id}.md``."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        path = str(raw or "").replace("\\", "/").strip()
        if not path or path in seen:
            continue
        if path.startswith("prd/") and not path.startswith("prd/reports/"):
            continue
        if is_authoring_scratch(path, initiative):
            out.append(path)
            seen.add(path)
    return out


def paths_for_family(family: TempFamily, ctx: PurgeContext) -> list[str]:
    """Resolve concrete relative paths for one family."""
    init = ctx.initiative.strip().upper()
    if not init:
        return []
    if family is TempFamily.AUTHORING_SCRATCH:
        # Always include known fixed suffixes even if inventory omitted them.
        fixed = [
            f"prd/reports/{init}-prd-quality.md",
            f"prd/reports/{init}-prd-ask.md",
            f"prd/reports/{init}-prd-recommend.md",
        ]
        return authoring_scratch_paths(init, list(ctx.candidates) + fixed)
    if family is TempFamily.PROMOTE_BRIEF:
        return [hermes_promote_brief_path(init)]
    if family is TempFamily.POST_PM_BRIEF:
        return [hermes_post_pm_brief_path(init)]
    if family is TempFamily.GATE1_QUESTIONS:
        return [f"prd/reports/PE-Product-Questions-{init}.md"]
    if family is TempFamily.GATE1_BRIEF:
        return [hermes_gate1_brief_path(init)]
    if family is TempFamily.READ_ROLLUP:
        safe = (ctx.meta_repo or "meta").replace("/", "-")
        return [f"prd/reports/{init}-read-walk-{safe}.md"]
    if family is TempFamily.KB_ENRICH_BODY:
        return [f"prd/reports/{init}-kb-enrich-pr-body.md"]
    return []


def paths_for_families(families: Iterable[TempFamily], ctx: PurgeContext) -> list[str]:
    """Union of family paths; order-preserving dedupe."""
    seen: set[str] = set()
    out: list[str] = []
    for family in families:
        for path in paths_for_family(family, ctx):
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def resolve_purge_paths(event: PurgeEvent, ctx: PurgeContext) -> list[str]:
    """Paths to delete for a lifecycle event (may include missing files — purge is idempotent)."""
    allowed = PURGE_MATRIX.get(event) or frozenset()
    # Enum declaration order — stable across processes (frozenset alone is not).
    ordered = [family for family in TempFamily if family in allowed]
    return paths_for_families(ordered, ctx)


def buzz_purge_notice(event: PurgeEvent, initiative: str, purged: Sequence[str]) -> str:
    """Short Buzz line after a purge (caller posts when ``purged`` non-empty)."""
    path_list = ", ".join(f"`{p}`" for p in purged) or "(none)"
    return f"Purged temp papers (`{event.value}`) for {initiative}: {path_list}."


def execute_purge(
    workspace: object, tenant: object, event: PurgeEvent, ctx: PurgeContext
) -> list[str]:
    """Resolve + delete for an event. ``workspace`` must expose ``purge_local_paths``."""
    purge_local = getattr(workspace, "purge_local_paths", None)
    if purge_local is None:
        return []
    paths = resolve_purge_paths(event, ctx)
    result = purge_local(tenant, paths)
    return list(result or [])
