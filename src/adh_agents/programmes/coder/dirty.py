"""Fail-fast dirty working tree before Coder skills / wave PR (C.16 / C2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.exceptions.app_exceptions import ValidationError


def list_dirty_relative_paths(repo_root: Path) -> list[str]:
    """Return porcelain paths (untracked + modified) relative to ``repo_root``."""
    root = Path(repo_root).expanduser().resolve()
    if not (root / ".git").is_dir():
        raise ValidationError(f"not a git checkout: {root}")
    proc = subprocess.run(
        ["git", "status", "--porcelain", "-u"],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ValidationError(f"git status failed in {root}: {(proc.stderr or proc.stdout)[:200]}")
    paths: list[str] = []
    for line in (proc.stdout or "").splitlines():
        raw = line[3:] if len(line) >= 3 else line.strip()
        # rename: "old -> new"
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[-1]
        rel = raw.strip().strip('"')
        if rel:
            paths.append(rel)
    return list(dict.fromkeys(paths))


def assert_clean_worktree(repo_root: Path, *, label: str = "") -> None:
    """Raise when ``git status --porcelain`` is non-empty (uncommitted changes)."""
    dirty = list_dirty_relative_paths(repo_root)
    if dirty:
        where = label or str(Path(repo_root).expanduser().resolve())
        raise ValidationError(
            f"dirty worktree under {where} — clean or commit before Coder continues "
            f"(fail-fast; no silent overwrite)"
        )


def discard_worktree_changes(repo_root: Path) -> None:
    """Drop local modifications + untracked after forge ``commit_workspace`` push."""
    root = Path(repo_root).expanduser().resolve()
    for args in (("checkout", "--", "."), ("clean", "-fd")):
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise ValidationError(
                f"git {' '.join(args)} failed in {root}: " f"{(proc.stderr or proc.stdout)[:300]}"
            )


def sync_clean_integration(
    repo_root: Path,
    *,
    branch: str,
) -> str:
    """Fetch + align onto tenant ``integration_branch`` (caller passes it). Fail-closed if dirty."""
    tip = (branch or "").strip()
    if not tip:
        raise ValidationError(
            "sync_clean_integration requires branch (tenant.integration_branch from governance)"
        )
    return sync_clean_head_ref(repo_root, branch=tip, create_from=None)


def sync_clean_head_ref(
    repo_root: Path,
    *,
    branch: str,
    create_from: str | None = None,
) -> str:
    """Fetch + hard-align local checkout to ``origin/<branch>`` (wave / integration head).

    - Remote head exists → ``checkout -B <branch> origin/<branch>``.
    - Remote head missing (first wave skill) → require ``create_from`` =
      ``tenant.integration_branch`` (governance SSOT). **No literal branch names.**

    Coder skills must see prior ``commit_workspace`` tips on the wave head — syncing
    only to integration left Pre-Implement on the remote wave branch while
    ``loop-spec`` ran on a bare integration tip and fail-closed ``blocked``.
    """
    assert_clean_worktree(repo_root, label=str(repo_root))
    head = (branch or "").strip()
    if not head:
        raise ValidationError("sync_clean_head_ref requires branch")
    root = Path(repo_root).expanduser().resolve()

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )

    fetch_head = _run("fetch", "origin", head)
    remote_head = _run("rev-parse", "--verify", f"origin/{head}")
    if remote_head.returncode == 0 and (remote_head.stdout or "").strip():
        co = _run("checkout", "-B", head, f"origin/{head}")
        if co.returncode != 0:
            raise ValidationError(
                f"git checkout -B {head} origin/{head} failed: " f"{(co.stderr or co.stdout)[:300]}"
            )
    else:
        base = (create_from or "").strip()
        if not base:
            detail = (fetch_head.stderr or fetch_head.stdout or "")[:300]
            raise ValidationError(
                f"origin/{head} missing — pass create_from=tenant.integration_branch "
                f"(governance); fetch detail: {detail or 'n/a'}"
            )
        fetch_base = _run("fetch", "origin", base)
        if fetch_base.returncode != 0:
            raise ValidationError(
                f"git fetch origin {base} failed: "
                f"{(fetch_base.stderr or fetch_base.stdout)[:300]}"
            )
        co_base = _run("checkout", base)
        if co_base.returncode != 0:
            raise ValidationError(
                f"git checkout {base} failed: {(co_base.stderr or co_base.stdout)[:300]}"
            )
        merge = _run("merge", "--ff-only", f"origin/{base}")
        if merge.returncode != 0:
            raise ValidationError(
                f"git merge --ff-only origin/{base} failed: "
                f"{(merge.stderr or merge.stdout)[:300]}"
            )
        co_new = _run("checkout", "-B", head)
        if co_new.returncode != 0:
            raise ValidationError(
                f"git checkout -B {head} failed: {(co_new.stderr or co_new.stdout)[:300]}"
            )
    rev = _run("rev-parse", "HEAD")
    return (rev.stdout or "").strip() if rev.returncode == 0 else ""
