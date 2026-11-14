"""Coder forge helpers — ``update_board_status`` (wave In Progress / Done)."""

from __future__ import annotations

import re

from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.dev.forge_ops import apps_with_installation
from src.adh_agents.programmes.dev.workmanifest_board import load_governance_board
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.models.hermes.execution_models import ForgeActionResult
from src.models.tenant_models import TenantContext

_ISSUE_URL = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)",
    flags=re.IGNORECASE,
)


def forge_allowed_board_status() -> bool:
    return forge_allowed("adh.coder", "update_board_status")


def parse_issue_url(url: str) -> tuple[str, str, int]:
    """Return (org, repo, number) from an issue HTML URL."""
    match = _ISSUE_URL.search((url or "").strip())
    if not match:
        raise ValidationError(f"not a GitHub issue URL: {url!r}")
    return match.group(1), match.group(2), int(match.group(3))


def pick_wave_issue_url(
    issue_urls: list[str] | tuple[str, ...],
    *,
    wave_id: str,
    wave_index: int,
) -> str:
    """Board seed order is EPIC then waves in manifest order — wave N ⇒ index N+1."""
    urls = [u.strip() for u in issue_urls if (u or "").strip()]
    if not urls:
        raise ValidationError("no board issue URLs for update_board_status")
    idx = int(wave_index) + 1
    if 0 <= idx < len(urls):
        return urls[idx]
    # Fallback: last non-epic URL.
    if len(urls) > 1:
        return urls[-1]
    raise ValidationError(
        f"no issue URL for wave {wave_id!r} (have {len(urls)} URL(s); need epic+wave)"
    )


async def move_wave_board_status(
    *,
    forge: ForgeActionService,
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    issue_url: str,
    status: str,
    repo_hint: str = "",
) -> ForgeActionResult:
    """YAML ``wave-in-progress-action`` / ``wave-done-action`` — forge only."""
    if not forge_allowed_board_status():
        raise ValidationError("forge ACL denies update_board_status for adh.coder")
    org_from_url, repo_from_url, number = parse_issue_url(issue_url)
    repo = (repo_hint or repo_from_url).rsplit("/", 1)[-1]
    board_name, enabled = load_governance_board(tenant.meta_root, tenant.org)
    if not enabled:
        raise ValidationError(f"governance project_board.enabled=false for {tenant.slug}")
    org = (tenant.org or org_from_url or "").strip()
    apps = apps_with_installation(workspace)
    if not apps:
        raise ValidationError("no GitHub App roles available for update_board_status")
    return await forge.update_board_status(
        apps=apps,
        org=org,
        board_name=board_name,
        issue_repo=repo,
        issue_number=number,
        status=status,
    )
