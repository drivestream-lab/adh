"""Deprecated shim — prefer ``adh_agents.collaboration.temp_papers``.

Gate‑1 / promote path helpers lived here briefly; the SSOT is now the global
``TempFamily`` / ``PurgeEvent`` matrix.
"""

from __future__ import annotations

from typing import Iterable

from src.adh_agents.collaboration.temp_papers import (
    PurgeContext,
    PurgeEvent,
    TempFamily,
    authoring_scratch_paths,
    paths_for_families,
    resolve_purge_paths,
)


def gate1_temp_paths(initiative: str, *, meta_repo: str = "") -> list[str]:
    """Legacy: Gate‑1 + read + KB body paths. Prefer ``resolve_purge_paths``."""
    ctx = PurgeContext(initiative=initiative, meta_repo=meta_repo)
    return paths_for_families(
        {
            TempFamily.GATE1_QUESTIONS,
            TempFamily.GATE1_BRIEF,
            TempFamily.READ_ROLLUP,
            TempFamily.KB_ENRICH_BODY,
        },
        ctx,
    )


def promote_temp_paths(initiative: str, candidates: Iterable[str]) -> list[str]:
    """Legacy: authoring scratch. Prefer ``PurgeEvent.PROMOTE_DONE``."""
    return authoring_scratch_paths(initiative, candidates)


def all_lane_temp_paths(
    initiative: str, *, meta_repo: str, promote_candidates: Iterable[str] | None = None
) -> list[str]:
    """Legacy: full abort set. Prefer ``PurgeEvent.LANE_ABORT``."""
    ctx = PurgeContext(
        initiative=initiative,
        meta_repo=meta_repo,
        candidates=tuple(promote_candidates or ()),
    )
    return resolve_purge_paths(PurgeEvent.LANE_ABORT, ctx)
