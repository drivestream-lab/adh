"""Verification **plan** artefact — Dev plans proofs; CI/human run them."""

from __future__ import annotations

import re

from src.adh_agents.programmes.dev.paths import verification_plan_path
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.models.tenant_models import TenantContext

_COVERAGE_ROW = re.compile(r"(?im)^\s*\|(?:[^|\n]+\|){2,}\s*$")


def ensure_verification_plan_stub(
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    *,
    initiative: str,
) -> str:
    path = verification_plan_path(initiative)
    if (workspace.read_local(tenant, path) or "").strip():
        return path
    init = initiative.strip().upper()
    body = "\n".join(
        [
            f"# Verification Plan — {init}",
            "",
            "> **Plan only.** Dev owns this document. CI / human / later verify agent **run** proofs.",
            "",
            "## Coverage table",
            "",
            "| Layer | Proof | Owner (run) | Status |",
            "|-------|-------|-------------|--------|",
            "| Unit | `tests/unit` for changed modules | CI | planned |",
            "| Integration | service contract / API | CI or human | planned |",
            "| Live verify | `tests/verify` / guinea pig | human | planned |",
            "",
            "## Gaps / risks",
            "",
            "- (fill after technical review)",
            "",
            "## Honest coach copy",
            "",
            "Accepting coding-readiness means the **plan** is coherent — not that proofs already passed.",
            "",
        ]
    )
    workspace.write_local(tenant, path, body)
    return path


def verification_plan_has_coverage_table(body: str) -> bool:
    """Require a markdown table with at least one data row under Coverage."""
    text = body or ""
    if "coverage" not in text.lower():
        return False
    rows = [ln for ln in text.splitlines() if _COVERAGE_ROW.match(ln)]
    # header + separator + ≥1 data
    data = [
        r
        for r in rows
        if not re.search(r"\|\s*-+\s*\|", r) and not re.search(r"(?i)\|\s*layer\s*\|", r)
    ]
    return len(data) >= 1
