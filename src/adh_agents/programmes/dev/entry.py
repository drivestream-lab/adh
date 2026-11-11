"""Dev programme entry — fail closed without PRD draft PR + Impact-Map."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.adh_agents.programmes.pm.validation_report import impact_map_path
from src.infra_services.pm_workspace_service import PmWorkspaceService, prd_path
from src.models.tenant_models import TenantContext


@dataclass(frozen=True)
class DevEntry:
    initiative: str
    prd_pr_url: str
    impact_map: str
    prd: str


def resolve_dev_entry(
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    *,
    initiative: str,
    prd_pr_url: str = "",
    slots: Optional[dict[str, str]] = None,
) -> tuple[Optional[DevEntry], Optional[str]]:
    """Validate bind inputs. Returns (entry, stall_reason)."""
    init = (initiative or "").strip().upper()
    if not init:
        return None, "Dev engg-think needs an initiative id."

    slots = slots or {}
    pr_url = (prd_pr_url or slots.get("prd_pr_url") or slots.get("pr_url") or "").strip()
    if not pr_url:
        return None, (
            f"**{init}** has no product PR URL — Dev starts after **PE → Dev** "
            "handoff (`engg go` / post–Gate‑1). Merged product PR is OK."
        )

    impact = impact_map_path(init)
    impact_body = (workspace.read_local(tenant, impact) or "").strip()
    if not impact_body:
        return None, (f"**{init}** missing Impact-Map at `{impact}` — Dev cannot bind without it.")

    prd = prd_path(init)
    if not (workspace.read_local(tenant, prd) or "").strip():
        return None, f"**{init}** missing PRD at `{prd}`."

    return (
        DevEntry(initiative=init, prd_pr_url=pr_url, impact_map=impact, prd=prd),
        None,
    )
