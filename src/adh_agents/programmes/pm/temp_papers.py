"""Temporary programme papers — purge (delete), never archive as SSOT."""

from __future__ import annotations

from typing import Iterable

from src.adh_agents.programmes.pm.promote_cleanup import scratch_paths_for_initiative
from src.infra_services.pm_workspace_service import hermes_gate1_brief_path


def gate1_temp_paths(initiative: str, *, meta_repo: str = "") -> list[str]:
    """Gate‑1 / read / KB working papers for one initiative (local meta)."""
    init = initiative.strip().upper()
    safe_meta = (meta_repo or "meta").replace("/", "-")
    return [
        f"prd/reports/PE-Product-Questions-{init}.md",
        hermes_gate1_brief_path(init),
        f"prd/reports/{init}-read-walk-{safe_meta}.md",
        f"prd/reports/{init}-kb-enrich-pr-body.md",
    ]


def promote_temp_paths(initiative: str, candidates: Iterable[str]) -> list[str]:
    """Pre-promote think/quality/ask/recommend scratch — purge after promote."""
    return scratch_paths_for_initiative(initiative, candidates)


def all_lane_temp_paths(
    initiative: str, *, meta_repo: str, promote_candidates: Iterable[str] | None = None
) -> list[str]:
    paths = list(gate1_temp_paths(initiative, meta_repo=meta_repo))
    if promote_candidates is not None:
        paths.extend(promote_temp_paths(initiative, promote_candidates))
    # Dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out
