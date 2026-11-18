"""Wave branch + artefact path helpers (no INIT/repo hardcoding)."""

from __future__ import annotations


def wave_branch(*, initiative: str, wave_id: str, repo: str) -> str:
    """Convention: ``feature/<init>-<wave>-<repo>`` (lowercase)."""
    init = (initiative or "").strip().lower()
    wid = (wave_id or "").strip().lower()
    short = (repo or "").strip().rsplit("/", 1)[-1].lower()
    return f"feature/{init}-{wid}-{short}"


def wave_pr_body_path(*, initiative: str, wave_id: str, repo: str) -> str:
    init = (initiative or "").strip().upper()
    wid = (wave_id or "").strip().upper()
    short = (repo or "").strip().rsplit("/", 1)[-1]
    return f"docs/specification/reports/Wave-PR-Body-{init}-{wid}-{short}.md"


def pre_implement_report_path(*, initiative: str, wave_id: str) -> str:
    init = (initiative or "").strip().upper()
    wid = (wave_id or "").strip().upper()
    return f"docs/specification/reports/Pre-Implement-{init}-{wid}.md"


def wave_execution_report_path(*, initiative: str, wave_id: str) -> str:
    init = (initiative or "").strip().upper()
    wid = (wave_id or "").strip().upper()
    return f"docs/specification/reports/Wave-Execution-{init}-{wid}.md"
