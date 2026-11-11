"""Dev forge helpers — push/open/land spec PRs on impacted code repos."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

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
) -> list[str]:
    """Push existing files from a code checkout via Contents API."""
    app = app_for_repo(workspace, repo)
    short = repo.rsplit("/", 1)[-1]
    token, _ = await github.installation_token(app, write=True, repositories=[short])
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
    """commit_workspace + open_draft_pr for one impacted repo."""
    short = repo.rsplit("/", 1)[-1]
    if not forge_allowed_open():
        raise ValidationError("forge ACL denies open_draft_pr for adh.dev")
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


async def land_spec_pr(
    *,
    forge: ForgeActionService,
    workspace: PmWorkspaceService,
    repo: str,
    pr_number: int,
    initiative: str,
) -> ForgeActionResult:
    short = repo.rsplit("/", 1)[-1]
    app = app_for_repo(workspace, short)
    reviewer = workspace.app_role(_REVIEWER)
    return await forge.land_pull_request(
        app=app,
        repo=short,
        pr_number=pr_number,
        commit_title=f"docs({initiative}): merge spec for {short}",
        action="land_pull_request",
        pre_approve_app=reviewer,
        pre_approve_body=(
            "Lead authorized YAML spec-merge on Buzz — forge APPROVE for branch protection."
        ),
    )


def forge_allowed_open() -> bool:
    from src.adh_agents.forge_acl import forge_allowed

    return forge_allowed("adh.dev", "open_draft_pr")
