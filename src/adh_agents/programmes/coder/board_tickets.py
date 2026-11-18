"""Resolve initiative board tickets from WorkManifest + GitHub (Coder pickup)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.adh_agents.programmes.dev.forge_ops import app_for_repo, apps_with_installation
from src.adh_agents.programmes.dev.workmanifest_board import BoardManifest, parse_board_manifest
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.logging import get_logger

logger = get_logger()


@dataclass(frozen=True)
class BoardTicketSnapshot:
    """EPIC + wave tickets in WorkManifest order — what a human coder would see."""

    initiative: str
    issue_urls: tuple[str, ...]
    epic_url: str
    wave_urls: dict[str, str]
    evidence_lines: tuple[str, ...]


def load_manifest(plan_path: Path | str) -> BoardManifest:
    path = Path(plan_path)
    if not path.is_file():
        raise ValidationError(f"implementation plan missing: {path}")
    return parse_board_manifest(path.read_text(encoding="utf-8"))


def match_issue_urls(
    manifest: BoardManifest,
    issues: list[dict],
) -> BoardTicketSnapshot:
    """Map open GitHub issues onto EPIC + wave titles (same order as board seed)."""
    by_title: dict[str, dict] = {}
    for row in issues:
        title = str(row.get("title") or "").strip()
        if title and title not in by_title:
            by_title[title] = row

    evidence: list[str] = []
    urls: list[str] = []
    wave_urls: dict[str, str] = {}

    epic = by_title.get(manifest.epic_title)
    epic_url = str((epic or {}).get("html_url") or "").strip()
    if epic:
        state = str(epic.get("state") or "open")
        evidence.append(f"EPIC — {manifest.epic_title} → {epic_url} ({state})")
        urls.append(epic_url)
    else:
        evidence.append(f"EPIC — {manifest.epic_title} → MISSING on board")

    for wave in manifest.waves:
        row = by_title.get(wave.title)
        url = str((row or {}).get("html_url") or "").strip()
        deps = ",".join(wave.depends_on) or "none"
        if row:
            state = str(row.get("state") or "open")
            evidence.append(
                f"{wave.wave_id} `{wave.repo}` — {wave.title} → {url} ({state}; depends_on={deps})"
            )
            urls.append(url)
            wave_urls[wave.wave_id] = url
        else:
            evidence.append(
                f"{wave.wave_id} `{wave.repo}` — {wave.title} → MISSING (depends_on={deps})"
            )

    return BoardTicketSnapshot(
        initiative=manifest.initiative,
        issue_urls=tuple(urls),
        epic_url=epic_url,
        wave_urls=wave_urls,
        evidence_lines=tuple(evidence),
    )


async def resolve_board_tickets(
    *,
    github: GitHubAppService,
    workspace: PmWorkspaceService,
    plan_path: Path | str,
    initiative: str = "",
    repo_hint: str = "",
) -> BoardTicketSnapshot:
    """List initiative-labeled issues and project onto WM EPIC/wave titles."""
    manifest = load_manifest(plan_path)
    init = (initiative or manifest.initiative or "").strip().upper()
    if manifest.initiative and init and manifest.initiative.upper() != init:
        raise ValidationError(f"plan initiative {manifest.initiative!r} != {init!r}")

    label = (manifest.labels[0] if manifest.labels else init).strip() or init
    repo = (repo_hint or manifest.epic_repo or "").strip().rsplit("/", 1)[-1]
    if not repo:
        raise ValidationError("cannot resolve board tickets — no epic repo")

    apps = apps_with_installation(workspace)
    if not apps:
        raise ValidationError("no GitHub App installation available to list board issues")
    try:
        app = app_for_repo(workspace, repo)
    except ValidationError:
        app = apps[0]

    try:
        token, _ = await github.installation_token(
            app,
            write=False,
            repositories=[repo],
            permissions={"issues": "read"},
        )
    except Exception:
        # Some installs only mint issues:write — still fine for list.
        token, _ = await github.installation_token(
            app,
            write=True,
            repositories=[repo],
            permissions={"issues": "write"},
        )
    issues = await github.list_issues_by_label(token, repo, label=label, state="all")
    snap = match_issue_urls(manifest, issues)
    logger.info(
        "Coder board ticket snapshot",
        initiative=init,
        repo=repo,
        label=label,
        urls=len(snap.issue_urls),
        waves=len(snap.wave_urls),
    )
    return snap
