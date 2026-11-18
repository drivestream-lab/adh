"""Shared lab + product overlay deploy helpers (Q1A — real stack only)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LabPaths:
    workspace: Path
    lab_root: Path
    overlay_root: Path


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    command: str


def resolve_lab_paths(
    workspace_root: Path | str,
    *,
    lab_name: str = "dev-infra-lab",
    overlay_name: str = "realworld-local",
    compose_dir: str = "",
) -> LabPaths:
    ws = Path(workspace_root)
    lab = ws / lab_name
    overlay = Path(compose_dir) if compose_dir.strip() else ws / overlay_name
    if not overlay.is_absolute():
        overlay = ws / overlay
    return LabPaths(workspace=ws, lab_root=lab, overlay_root=overlay)


def lab_is_healthy(*, postgres_container: str = "lab-postgres") -> tuple[bool, str]:
    """Return (ok, reason). No faking — Docker inspect only."""
    try:
        proc = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                postgres_container,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"docker inspect failed: {exc}"
    status = (proc.stdout or "").strip()
    if status == "healthy":
        return True, "lab-postgres healthy"
    return (
        False,
        f"lab-postgres status={status or 'missing'} (start: cd dev-infra-lab && make infra-up)",
    )


def run_make(
    root: Path,
    target: str,
    *,
    timeout_seconds: int = 600,
    env: dict[str, str] | None = None,
) -> CommandResult:
    cmd = f"make {target}"
    merged = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            ["make", target],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=merged,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(
            ok=False,
            exit_code=124,
            stdout="",
            stderr=str(exc),
            command=cmd,
        )
    return CommandResult(
        ok=proc.returncode == 0,
        exit_code=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        command=cmd,
    )


def discover_lab_database_url(lab_root: Path) -> str:
    """Read DATABASE_URL-ish creds from lab .env (real file — no invent)."""
    env_path = lab_root / ".env"
    if not env_path.is_file():
        env_path = lab_root / ".env.example"
    user = "adh"
    password = "adh"
    db = "realworld"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key == "POSTGRES_USER" and val:
                user = val
            elif key == "POSTGRES_PASSWORD" and val:
                password = val
    # Host-side connect to published lab Postgres.
    return f"postgresql://{user}:{password}@127.0.0.1:5432/{db}"
