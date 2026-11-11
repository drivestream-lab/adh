"""Engg-Deps artefact — durable multi-repo DAG for deps-acceptance."""

from __future__ import annotations

import re
from typing import Optional

from src.adh_agents.programmes.dev.paths import engg_deps_path
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.models.tenant_models import TenantContext

_REPO_LINE = re.compile(r"(?im)^\s*[-*]\s+`?([a-z0-9._/-]+)`?\s*(?:—|-|:)\s*(.+)$")
_TIER_HEAD = re.compile(r"(?im)^##\s+Tier\s+(\d+)\b")


def ensure_engg_deps_stub(
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    *,
    initiative: str,
    impact_map_body: str,
) -> str:
    """Write Engg-Deps stub from Impact-Map repo hints if missing. Returns relative path."""
    path = engg_deps_path(initiative)
    existing = (workspace.read_local(tenant, path) or "").strip()
    if existing:
        return path
    repos = _repos_from_impact(impact_map_body)
    lines = [
        f"# Engg-Deps — {initiative.strip().upper()}",
        "",
        "> Durable multi-repo dependency DAG for `deps-acceptance`.",
        "> Edit tiers before accepting. Parallel mutate = same tier.",
        "",
        "## Tier 0 — foundations (no parallel mutate with dependents)",
        "",
    ]
    if repos:
        for repo in repos:
            lines.append(f"- `{repo}` — (fill: why / blockers / parallel-safe?)")
    else:
        lines.append("- `(no repos parsed from Impact-Map — add explicitly)`")
    lines.extend(
        [
            "",
            "## Tier 1 — dependents",
            "",
            "- `(add repos that depend on Tier 0)`",
            "",
            "## Acceptance notes",
            "",
            "- Board wave order must follow tiers.",
            "- Coder must not invent cross-repo edges not listed here.",
            "",
        ]
    )
    workspace.write_local(tenant, path, "\n".join(lines))
    return path


def parse_deps_tiers(body: str) -> list[tuple[int, list[str]]]:
    """Extract (tier, repos) from Engg-Deps markdown."""
    text = body or ""
    tiers: list[tuple[int, list[str]]] = []
    current_tier: Optional[int] = None
    current_repos: list[str] = []
    for line in text.splitlines():
        head = _TIER_HEAD.match(line)
        if head:
            if current_tier is not None:
                tiers.append((current_tier, current_repos))
            current_tier = int(head.group(1))
            current_repos = []
            continue
        if current_tier is None:
            continue
        m = _REPO_LINE.match(line)
        if m:
            repo = m.group(1).strip()
            if repo and not repo.startswith("("):
                current_repos.append(repo)
    if current_tier is not None:
        tiers.append((current_tier, current_repos))
    return tiers


def deps_has_visible_dag(body: str) -> bool:
    """True when at least one tier lists a concrete repo."""
    for _tier, repos in parse_deps_tiers(body):
        if repos:
            return True
    return False


def _repos_from_impact(body: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r"(?im)\b(?:repo|repository|package)\s*[:=]\s*`?([a-z0-9._/-]+)`?",
        body or "",
    ):
        repo = m.group(1).strip()
        key = repo.lower()
        if key not in seen:
            seen.add(key)
            found.append(repo)
    # Fallback: backtick paths that look like org/repo
    for m in re.finditer(r"`([a-z0-9._-]+/[a-z0-9._-]+)`", body or "", re.I):
        repo = m.group(1).strip()
        key = repo.lower()
        if key not in seen:
            seen.add(key)
            found.append(repo)
    return found
