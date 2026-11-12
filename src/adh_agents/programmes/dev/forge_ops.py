"""Dev forge helpers — push/open/land spec PRs on impacted code repos."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from src.adh_agents.programmes.dev.workmanifest_board import (
    load_governance_board,
    parse_board_manifest,
)
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.logging import get_logger
from src.models.hermes.execution_models import ForgeActionResult
from src.models.orchestrator_models import AppRole
from src.models.tenant_models import TenantContext

logger = get_logger()

_REVIEWER = "adh-reviewer"

# Gate 2 delivery: coding-readiness / spec-merge project these (mirror Gate 1).
_SPEC_LGTM_ADD = ["spec-lgtm"]
_SPEC_LGTM_REMOVE = [
    "spec-pending",
    "spec-blocked",
    "spec-revised",
    "spec-stale",
]


def app_for_repo(workspace: PmWorkspaceService, repo: str) -> AppRole:
    """Pick a roles.yaml app for ``repo``.

    Prefer non-reviewer writers that already pin ``installation_id`` (live install).
    Listing a repo without an install (e.g. orphan frontend app) must not win.
    """
    short = (repo or "").strip().rsplit("/", 1)[-1]
    roles_path = workspace._roles_path()
    if roles_path is None:
        raise ValidationError("roles.yaml missing; cannot resolve app for repo")
    with roles_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    apps = data.get("apps") or {}
    writers_installed: list[AppRole] = []
    writers_bare: list[AppRole] = []
    reviewer_installed: Optional[AppRole] = None
    reviewer_bare: Optional[AppRole] = None
    for slug, raw in apps.items():
        if not isinstance(raw, dict):
            continue
        listed = [str(r).strip() for r in (raw.get("repos") or [])]
        if short not in listed:
            continue
        role = AppRole.model_validate(raw)
        has_install = role.installation_id is not None
        if slug == _REVIEWER:
            if has_install:
                reviewer_installed = role
            else:
                reviewer_bare = role
            continue
        if has_install:
            writers_installed.append(role)
        else:
            writers_bare.append(role)
    # Installed identities always beat bare (uninstalled) app rows — otherwise an
    # orphan frontend app with no org install blocks reviewer/backend mint paths.
    chosen = (
        (writers_installed[0] if writers_installed else None)
        or reviewer_installed
        or (writers_bare[0] if writers_bare else None)
        or reviewer_bare
    )
    if chosen is None:
        raise ValidationError(f"no roles.yaml app lists repo {short!r}")
    return chosen


def apps_with_installation(workspace: PmWorkspaceService) -> list[AppRole]:
    """All roles.yaml apps that pin an installation_id (mintable writers/reviewers)."""
    roles_path = workspace._roles_path()
    if roles_path is None:
        return []
    with roles_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    out: list[AppRole] = []
    for raw in (data.get("apps") or {}).values():
        if not isinstance(raw, dict):
            continue
        role = AppRole.model_validate(raw)
        if role.installation_id is not None:
            out.append(role)
    return out


async def push_local_paths(
    *,
    github: GitHubAppService,
    workspace: PmWorkspaceService,
    repo: str,
    repo_root: Path,
    branch: str,
    relative_paths: list[str],
    commit_message: str,
    from_branch: str,
) -> list[str]:
    """Push existing files from a code checkout via Contents API.

    ``from_branch`` is the integration tip (``develop``) — never GitHub default
    ``main`` for product Spec lanes.
    """
    app = app_for_repo(workspace, repo)
    short = repo.rsplit("/", 1)[-1]
    base = (from_branch or "develop").strip() or "develop"
    token, _ = await github.installation_token(app, write=True, repositories=[short])
    # Force Spec head onto current develop tip before the first Contents put.
    await github.ensure_branch_from(token, short, branch, from_branch=base, reset=True)
    pushed: list[str] = []
    for rel in list(dict.fromkeys(p for p in relative_paths if p)):
        local = repo_root / rel
        if not local.is_file():
            logger.warning("skip forge push; missing local file", repo=short, path=rel)
            continue
        body = local.read_text(encoding="utf-8")
        await github.put_text_file(
            token,
            short,
            path=rel,
            contents=body,
            branch=branch,
            message=f"{commit_message}: {rel}",
            from_branch=base,
            reset_branch=False,
        )
        pushed.append(rel)
    if not pushed:
        raise ValidationError(f"no local artefacts to push for {short}@{branch}")
    return pushed


async def open_spec_draft_pr(
    *,
    forge: ForgeActionService,
    github: GitHubAppService,
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    repo: str,
    repo_root: Path,
    initiative: str,
    branch: str,
    body_rel: str,
    title: str,
    push_paths: list[str],
) -> ForgeActionResult:
    """Push INIT-scoped docs onto a head reset from ``integration_branch``, open draft."""
    short = repo.rsplit("/", 1)[-1]
    if not forge_allowed_open():
        raise ValidationError("forge ACL denies open_draft_pr for adh.dev")
    base = (tenant.integration_branch or "develop").strip() or "develop"
    # Ensure PR body exists locally.
    body_path = repo_root / body_rel
    if not body_path.is_file():
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(
            f"# Spec draft — {initiative} — {short}\n\n" "Automated Dev YAML `spec-pr-action`.\n",
            encoding="utf-8",
        )
        push_paths = [*push_paths, body_rel]
    await push_local_paths(
        github=github,
        workspace=workspace,
        repo=short,
        repo_root=repo_root,
        branch=branch,
        relative_paths=push_paths,
        commit_message=f"docs({initiative}): spec draft for {short}",
        from_branch=base,
    )
    app = app_for_repo(workspace, short)
    # Absolute body path so ForgeActionService can read outside meta_root.
    return await forge.run_action(
        tenant,
        "open_draft_pr",
        app=app,
        title=title,
        body_path=str(body_path.resolve()),
        head_branch=branch,
        draft=True,
        labels=["spec-pending"],
        repo=short,
    )


def _distinct_approver(
    workspace: PmWorkspaceService,
    opener: AppRole,
    *,
    repo: str = "",
) -> Optional[AppRole]:
    """App that can APPROVE without GitHub 422 self-review.

    Prefer ``adh-reviewer`` when it is not the opener; else any other installed
    app that **lists** ``repo`` in roles.yaml. Cross-repo installs (e.g. backend
    for ``realworld-web``) are skipped — those PRs use labels-only.
    """
    short = (repo or "").strip().rsplit("/", 1)[-1]
    reviewer = workspace.app_role(_REVIEWER)
    if (
        reviewer is not None
        and reviewer.app_id != opener.app_id
        and (not short or short in list(reviewer.repos or []))
    ):
        return reviewer
    for cand in apps_with_installation(workspace):
        if cand.app_id == opener.app_id:
            continue
        if short and short not in list(cand.repos or []):
            continue
        return cand
    return None


async def attest_spec_pr(
    *,
    forge: ForgeActionService,
    workspace: PmWorkspaceService,
    repo: str,
    pr_number: int,
    initiative: str,
) -> ForgeActionResult:
    """Gate 2 attest before merge — ready_for_review + APPROVE + ``spec-lgtm``.

    Delivery: same shape as PE Gate 1 (impact-map-lgtm) — labels must move and
    attestation must land on the exact Spec PR head **before** ``spec-merge``.

    When the Spec PR was opened by ``adh-reviewer`` (no separate writer install
    for that repo), GitHub rejects self-APPROVE (422). We still project
    ``spec-lgtm`` and skip the review submit in that case.
    """
    short = repo.rsplit("/", 1)[-1]
    app = app_for_repo(workspace, short)
    approver = _distinct_approver(workspace, app, repo=short)
    # Undraft first — Draft PRs cannot receive APPROVE.
    await forge.ready_for_review(app=app, repo=short, pr_number=pr_number)
    body = (
        f"Gate 2 / coding-readiness attestation for `{initiative}` "
        f"on `{short}`#{pr_number}.\n"
        "Projects `spec-lgtm` on the exact Spec PR head "
        "(delivery: labels + attest before merge)."
    )
    if approver is not None:
        return await forge.approve_attestation(
            app=approver,
            repo=short,
            pr_number=pr_number,
            body=body + "\nAPPROVE by distinct reviewer app.",
            gate_labels=True,
            label_add=list(_SPEC_LGTM_ADD),
            label_remove=list(_SPEC_LGTM_REMOVE),
            submit_review=True,
        )
    logger.warning(
        "Gate 2 labels-only — no distinct approver (avoid self-APPROVE 422)",
        repo=short,
        pr=pr_number,
        opener_app_id=app.app_id,
    )
    return await forge.approve_attestation(
        app=app,
        repo=short,
        pr_number=pr_number,
        body=body + "\nLabels only — opener has no distinct reviewer app.",
        gate_labels=True,
        label_add=list(_SPEC_LGTM_ADD),
        label_remove=list(_SPEC_LGTM_REMOVE),
        submit_review=False,
    )


async def land_spec_pr(
    *,
    forge: ForgeActionService,
    workspace: PmWorkspaceService,
    repo: str,
    pr_number: int,
    initiative: str,
) -> ForgeActionResult:
    """Merge Spec PR only after Gate 2 label move + attestation (fail-closed)."""
    short = repo.rsplit("/", 1)[-1]
    app = app_for_repo(workspace, short)
    reviewer = workspace.app_role(_REVIEWER)
    # GitHub rejects self-APPROVE (422) when the opener identity is also the reviewer.
    pre_approve = None if (reviewer is not None and app.app_id == reviewer.app_id) else reviewer
    return await forge.land_pull_request(
        app=app,
        repo=short,
        pr_number=pr_number,
        commit_title=f"docs({initiative}): merge spec for {short}",
        action="land_pull_request",
        pre_approve_app=pre_approve,
        pre_approve_body=(
            f"Gate 2 attestation + Lead-authorized YAML spec-merge for `{initiative}` "
            f"on `{short}` — APPROVE + `spec-lgtm` before merge."
        ),
        gate_label_add=list(_SPEC_LGTM_ADD),
        gate_label_remove=list(_SPEC_LGTM_REMOVE),
    )


def forge_allowed_open() -> bool:
    from src.adh_agents.forge_acl import forge_allowed

    return forge_allowed("adh.dev", "open_draft_pr")


def forge_allowed_board() -> bool:
    from src.adh_agents.forge_acl import forge_allowed

    return forge_allowed("adh.dev", "create_board_tickets")


async def seed_board_tickets(
    *,
    forge: ForgeActionService,
    workspace: PmWorkspaceService,
    tenant: TenantContext,
    plan_path: Path,
    initiative: str,
) -> ForgeActionResult:
    """YAML ``board-tickets-action`` — forge ``create_board_tickets`` (not Cursor skill)."""
    if not forge_allowed_board():
        raise ValidationError("forge ACL denies create_board_tickets for adh.dev")
    if not plan_path.is_file():
        raise ValidationError(f"implementation plan missing: {plan_path}")

    manifest = parse_board_manifest(plan_path.read_text(encoding="utf-8"))
    if manifest.initiative and initiative and manifest.initiative != initiative:
        raise ValidationError(f"plan initiative {manifest.initiative!r} != session {initiative!r}")
    init = initiative or manifest.initiative

    board_name, enabled = load_governance_board(tenant.meta_root, tenant.org)
    if not enabled:
        raise ValidationError(f"governance project_board.enabled=false for {tenant.slug}")
    if manifest.project_name and manifest.project_name != board_name:
        logger.warning(
            "WorkManifest target.project mismatches governance; governance wins",
            manifest_project=manifest.project_name,
            governance_project=board_name,
        )

    org = (manifest.org or tenant.org or "").strip()
    apps = _issue_capable_apps(workspace, manifest.epic_repo)
    if not apps:
        # Fall back to every installed app — mint will filter by issues:write.
        apps = apps_with_installation(workspace)

    waves = [
        {
            "id": w.wave_id,
            "repo": w.repo,
            "title": w.title,
            "body": w.body,
        }
        for w in manifest.waves
    ]
    return await forge.create_board_tickets(
        apps=apps,
        initiative=init,
        board_name=board_name,
        org=org,
        epic_repo=manifest.epic_repo,
        epic_title=manifest.epic_title,
        epic_body=manifest.epic_body,
        labels=list(manifest.labels),
        waves=waves,
    )


def _issue_capable_apps(workspace: PmWorkspaceService, repo: str) -> list[AppRole]:
    """Prefer installed writers listing ``repo`` (backend has issues+org projects).

    Reviewer is kept as fallback for issues:write-only installs.
    """
    short = repo.rsplit("/", 1)[-1]
    ordered: list[AppRole] = []
    for app in apps_with_installation(workspace):
        listed = [str(r).strip().rsplit("/", 1)[-1] for r in (app.repos or [])]
        if listed and short not in listed:
            continue
        ordered.append(app)
    try:
        reviewer = workspace.app_role(_REVIEWER)
        if reviewer.installation_id is not None:
            ordered.append(reviewer)
    except Exception:  # noqa: BLE001 — optional
        pass
    seen: set[int] = set()
    out: list[AppRole] = []
    for app in ordered:
        if app.app_id in seen:
            continue
        seen.add(app.app_id)
        out.append(app)
    return out
