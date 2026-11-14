"""Fail-fast dirty working tree before Coder skills / wave PR (C.16 / C2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.exceptions.app_exceptions import ValidationError


def assert_clean_worktree(repo_root: Path, *, label: str = "") -> None:
    """Raise when ``git status --porcelain`` is non-empty (uncommitted changes)."""
    root = Path(repo_root).expanduser().resolve()
    if not (root / ".git").is_dir():
        raise ValidationError(f"not a git checkout: {root}")
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ValidationError(f"git status failed in {root}: {(proc.stderr or proc.stdout)[:200]}")
    if (proc.stdout or "").strip():
        where = label or str(root)
        raise ValidationError(
            f"dirty worktree under {where} — clean or commit before Coder continues "
            f"(fail-fast; no silent overwrite)"
        )


def sync_clean_integration(
    repo_root: Path,
    *,
    branch: str,
) -> str:
    """Fetch + ff-only onto ``branch`` when clean. Returns HEAD sha. Fail-closed if dirty."""
    assert_clean_worktree(repo_root, label=str(repo_root))
    base = (branch or "develop").strip() or "develop"
    root = Path(repo_root).expanduser().resolve()

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )

    fetch = _run("fetch", "origin", base)
    if fetch.returncode != 0:
        raise ValidationError(
            f"git fetch origin {base} failed: {(fetch.stderr or fetch.stdout)[:300]}"
        )
    checkout = _run("checkout", base)
    if checkout.returncode != 0:
        raise ValidationError(
            f"git checkout {base} failed: {(checkout.stderr or checkout.stdout)[:300]}"
        )
    merge = _run("merge", "--ff-only", f"origin/{base}")
    if merge.returncode != 0:
        raise ValidationError(
            f"git merge --ff-only origin/{base} failed (diverged?) — "
            f"{(merge.stderr or merge.stdout)[:300]}"
        )
    rev = _run("rev-parse", "HEAD")
    return (rev.stdout or "").strip() if rev.returncode == 0 else ""
