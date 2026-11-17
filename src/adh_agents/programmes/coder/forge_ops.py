"""Coder forge helpers — board status + wave Draft PR open/land."""

from __future__ import annotations

import re
from pathlib import Path

from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.coder.dirty import (
    discard_worktree_changes,
    list_dirty_relative_paths,
)
from src.adh_agents.programmes.coder.paths import wave_pr_body_path
from src.adh_agents.programmes.dev.forge_ops import (
    _distinct_approver,
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


def forge_allowed_commit_workspace() -> bool:
    """YAML ``commit_workspace`` uses Contents push (ACL: ``push_branch``)."""
    return forge_allowed("adh.coder", "push_branch")


def forge_allowed_land() -> bool:
    return forge_allowed("adh.coder", "land_pull_request") or forge_allowed(
        "adh.coder", "prd_merge"
    )


async def commit_workspace(
    *,
    github: GitHubAppService,
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    repo: str,
    repo_root: Path,
    branch: str,
    initiative: str,
    stage: str,
    wave_id: str = "",
    required: bool = True,
) -> list[str]:
    """YAML skill pin ``forge.commit_workspace`` — publish dirty paths to ``head_ref``.

    Pushes via GitHub Contents API (no ``gh``), then discards local dirt so the
    next skill can ``assert_clean_worktree``. Incremental: does **not** reset the
    wave head (unlike first ``open_draft_pr``).
    """
    if not forge_allowed_commit_workspace():
        raise ValidationError("forge ACL denies push_branch (commit_workspace) for adh.coder")
    short = repo.rsplit("/", 1)[-1]
    base = (tenant.integration_branch or "").strip()
    if not base:
        raise ValidationError("tenant.integration_branch unset — set governance integration_branch")
    dirty = list_dirty_relative_paths(repo_root)
    if not dirty:
        if required:
            raise ValidationError(
                f"commit_workspace required after `{stage}` but worktree is clean "
                f"(nothing to publish on `{short}`)"
            )
        return []
    wid = (wave_id or "").strip() or "?"
    pushed = await push_local_paths(
        github=github,
        workspace=workspace,
        repo=short,
        repo_root=repo_root,
        branch=branch,
        relative_paths=dirty,
        commit_message=f"chore({initiative}): {stage} {wid} for {short}",
        from_branch=base,
        reset_branch=False,
    )
    discard_worktree_changes(repo_root)
    return pushed


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
    base = (tenant.integration_branch or "").strip()
    if not base:
        raise ValidationError("tenant.integration_branch unset — set governance integration_branch")
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
    # Head already holds pre-implement/loop-spec commit_workspace tips — do not reset.
    await push_local_paths(
        github=github,
        workspace=workspace,
        repo=short,
        repo_root=repo_root,
        branch=branch,
        relative_paths=push_paths or [body_rel],
        commit_message=f"feat({initiative}): wave {wave_id} for {short}",
        from_branch=base,
        reset_branch=False,
    )
    app = app_for_repo(workspace, short)
    pr_title = title or f"feat({initiative}): {wave_id} — {short}"
    result = await forge.run_action(
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
    # Contents push leaves local Wave-PR-Body / push_paths as dirt — discard so
    # Pass-2 learning-extract can assert_clean (board Done is after Pass-2).
    discard_worktree_changes(repo_root)
    return result


async def project_wave_accepted(
    *,
    github: GitHubAppService,
    workspace: PmWorkspaceService,
    repo: str,
    pr_number: int,
) -> None:
    """Phase-1 acceptance ingress — label tip ``wave-accepted`` (remove ``wave-pending``).

    Pass-2 ``learning-extract`` fail-closes without this projection. Harness-owned
    (not a content skill). Called when Verify returns ``verify_accepted``.
    """
    if not forge_allowed("adh.coder", "apply_labels"):
        raise ValidationError("forge ACL denies apply_labels for adh.coder")
    short = (repo or "").rsplit("/", 1)[-1].strip()
    n = int(pr_number)
    if not short or n <= 0:
        raise ValidationError("project_wave_accepted requires repo + pr_number")
    app = app_for_repo(workspace, short)
    token, _ = await github.installation_token(app, write=True, repositories=[short])
    await github.replace_issue_labels(
        token,
        short,
        issue_number=n,
        add=["wave-accepted"],
        remove=["wave-pending"],
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
    """YAML ``wave-signoff`` merge — Lead/god authorized.

    ``develop`` (integration) often requires ≥1 approving review — same as Spec
    land: APPROVE via a distinct ``adh-reviewer`` (or other) install, then merge.
    Labels-only returns GitHub 405 when branch protection demands reviews.
    """
    if not forge_allowed_land():
        raise ValidationError("forge ACL denies land_pull_request for adh.coder")
    short = repo.rsplit("/", 1)[-1]
    app = app_for_repo(workspace, short)
    n = int(pr_number)
    approver = _distinct_approver(workspace, app, repo=short)
    if approver is None:
        raise ValidationError(
            f"Cannot land `{short}`#{n}: no distinct reviewer app for APPROVE "
            "(branch protection) — configure adh-reviewer in roles.yaml"
        )
    return await forge.land_pull_request(
        app=app,
        repo=short,
        pr_number=n,
        commit_title=f"feat({initiative}): merge wave {wave_id}",
        action="prd_merge",
        pre_approve_app=approver,
        pre_approve_body=(
            f"Wave-signoff / Lead-authorized land for `{initiative}` `{wave_id}` "
            f"on `{short}` — APPROVE + `wave-merged` before merge."
        ),
        gate_label_add=["wave-merged"],
        gate_label_remove=["wave-pending", "wave-accepted"],
    )
