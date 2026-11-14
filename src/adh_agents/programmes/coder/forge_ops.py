"""Coder forge helpers — board status + wave Draft PR open/land."""

from __future__ import annotations

import re
from pathlib import Path

from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.coder.paths import wave_pr_body_path
from src.adh_agents.programmes.dev.forge_ops import (
    app_for_repo,
    apps_with_installation,
    push_local_paths,
)
from src.adh_agents.programmes.dev.workmanifest_board import load_governance_board
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.github_app_service import GitHubAppService
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


def forge_allowed_open_pr() -> bool:
    return forge_allowed("adh.coder", "open_draft_pr")


def forge_allowed_land() -> bool:
    return forge_allowed("adh.coder", "land_pull_request") or forge_allowed(
        "adh.coder", "prd_merge"
    )


async def open_wave_draft_pr(
    *,
    forge: ForgeActionService,
    github: GitHubAppService,
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    repo: str,
    repo_root: Path,
    initiative: str,
    wave_id: str,
    branch: str,
    push_paths: list[str],
    title: str = "",
) -> ForgeActionResult:
    """YAML ``wave-pr-action`` — automated Draft PR after loop-spec."""
    if not forge_allowed_open_pr():
        raise ValidationError("forge ACL denies open_draft_pr for adh.coder")
    short = repo.rsplit("/", 1)[-1]
    base = (tenant.integration_branch or "develop").strip() or "develop"
    body_rel = wave_pr_body_path(initiative=initiative, wave_id=wave_id, repo=short)
    body_path = repo_root / body_rel
    if not body_path.is_file():
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(
            (
                f"# Wave PR — {initiative} — {wave_id} — {short}\n\n"
                "Automated Coder YAML `wave-pr-action`.\n"
            ),
            encoding="utf-8",
        )
        push_paths = [*push_paths, body_rel]
    await push_local_paths(
        github=github,
        workspace=workspace,
        repo=short,
        repo_root=repo_root,
        branch=branch,
        relative_paths=push_paths or [body_rel],
        commit_message=f"feat({initiative}): wave {wave_id} for {short}",
        from_branch=base,
    )
    app = app_for_repo(workspace, short)
    pr_title = title or f"feat({initiative}): {wave_id} — {short}"
    return await forge.run_action(
        tenant,
        "open_draft_pr",
        app=app,
        title=pr_title,
        body_path=str(body_path.resolve()),
        head_branch=branch,
        draft=True,
        labels=[initiative, "wave-pending"],
        repo=short,
    )


async def land_wave_pr(
    *,
    forge: ForgeActionService,
    workspace: PmWorkspaceService,
    repo: str,
    pr_number: int,
    initiative: str,
    wave_id: str,
) -> ForgeActionResult:
    """YAML ``wave-signoff`` merge — Lead/god authorized."""
    if not forge_allowed_land():
        raise ValidationError("forge ACL denies land_pull_request for adh.coder")
    short = repo.rsplit("/", 1)[-1]
    app = app_for_repo(workspace, short)
    return await forge.land_pull_request(
        app=app,
        repo=short,
        pr_number=int(pr_number),
        commit_title=f"feat({initiative}): merge wave {wave_id}",
        action="prd_merge",
        gate_label_add=["wave-merged"],
        gate_label_remove=["wave-pending"],
    )
