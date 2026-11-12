"""Extract WorkManifest §9 fields needed to seed the programme board."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from src.exceptions.app_exceptions import ValidationError

_FENCE = re.compile(r"```(?:yaml|yml)\s*\n(.*?)```", flags=re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class BoardWave:
    wave_id: str
    repo: str
    title: str
    body: str
    task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoardManifest:
    initiative: str
    org: str
    project_name: str
    epic_repo: str
    epic_title: str
    epic_body: str
    labels: tuple[str, ...] = ()
    waves: tuple[BoardWave, ...] = field(default_factory=tuple)


def extract_workmanifest_yaml(text: str) -> str:
    """Return the §9 WorkManifest YAML fence body (fail closed)."""
    if not (text or "").strip():
        raise ValidationError("WorkManifest source empty")
    stripped = text.strip()
    if stripped.startswith("apiVersion:") and "kind: WorkManifest" in stripped:
        return stripped

    section = text
    marker = re.search(r"^##\s*9\.\s*WorkManifest", text, flags=re.MULTILINE)
    if marker:
        section = text[marker.start() :]
        next_h2 = re.search(r"^##\s+(?!9\.)", section[1:], flags=re.MULTILINE)
        if next_h2:
            section = section[: next_h2.start() + 1]

    for match in _FENCE.finditer(section):
        body = match.group(1).strip()
        if "kind: WorkManifest" in body or "kind:WorkManifest" in body:
            return body
    for match in _FENCE.finditer(text):
        body = match.group(1).strip()
        if "kind: WorkManifest" in body or "apiVersion: prayog/v1" in body:
            return body
    raise ValidationError("no WorkManifest YAML fence found in plan")


def parse_board_manifest(text: str) -> BoardManifest:
    """Parse plan markdown / YAML into board-seed projection fields."""
    raw = extract_workmanifest_yaml(text)
    try:
        data = yaml.safe_load(raw)
    except Exception as exc:  # noqa: BLE001 — surface parse errors
        raise ValidationError(f"WorkManifest YAML parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("WorkManifest root must be a mapping")
    if str(data.get("apiVersion") or "").strip() != "prayog/v1":
        raise ValidationError("WorkManifest apiVersion must be prayog/v1")
    if str(data.get("kind") or "").strip() != "WorkManifest":
        raise ValidationError("WorkManifest kind must be WorkManifest")

    initiative = str(data.get("initiative") or "").strip()
    if not initiative:
        raise ValidationError("WorkManifest.initiative missing")

    target_raw = data.get("target")
    target: dict[str, Any] = target_raw if isinstance(target_raw, dict) else {}
    org = str(target.get("org") or "").strip()
    project_name = str(target.get("project") or "").strip()
    if not project_name:
        raise ValidationError("WorkManifest.target.project missing")

    defaults_raw = data.get("defaults")
    defaults: dict[str, Any] = defaults_raw if isinstance(defaults_raw, dict) else {}
    labels_field = defaults.get("labels")
    labels_raw: list[Any] = labels_field if isinstance(labels_field, list) else []
    labels = tuple(str(x).strip() for x in labels_raw if str(x).strip()) or (initiative,)

    epic_raw = data.get("epic")
    if not isinstance(epic_raw, dict):
        raise ValidationError("WorkManifest.epic missing")
    epic: dict[str, Any] = epic_raw
    epic_repo = _short_repo(str(epic.get("repo") or epic.get("codebase") or ""))
    epic_title = str(epic.get("title") or "").strip()
    if not epic_repo or not epic_title:
        raise ValidationError("WorkManifest.epic.repo/title required")
    epic_body = str(epic.get("body") or "").strip() or _default_epic_body(initiative, epic)

    work = data.get("work")
    if not isinstance(work, list) or not work:
        raise ValidationError("WorkManifest.work[] missing")
    waves: list[BoardWave] = []
    for row_any in work:
        if not isinstance(row_any, dict):
            continue
        row: dict[str, Any] = row_any
        wid = str(row.get("id") or "").strip()
        if not re.fullmatch(r"W\d+", wid):
            raise ValidationError(f"invalid wave id {wid!r}")
        repo = _short_repo(str(row.get("repo") or row.get("codebase") or epic_repo))
        title = str(row.get("title") or "").strip()
        if not title:
            raise ValidationError(f"wave {wid} title missing")
        body = str(row.get("body") or "").strip() or _wave_body_from_tasks(wid, row)
        tasks_field = row.get("tasks")
        tasks: list[Any] = tasks_field if isinstance(tasks_field, list) else []
        task_ids = tuple(
            str(t.get("id") or "").strip()
            for t in tasks
            if isinstance(t, dict) and str(t.get("id") or "").strip()
        )
        waves.append(
            BoardWave(
                wave_id=wid,
                repo=repo,
                title=title,
                body=body,
                task_ids=task_ids,
            )
        )
    if not waves:
        raise ValidationError("WorkManifest.work[] has no waves")

    return BoardManifest(
        initiative=initiative,
        org=org,
        project_name=project_name,
        epic_repo=epic_repo,
        epic_title=epic_title,
        epic_body=epic_body,
        labels=labels,
        waves=tuple(waves),
    )


def load_governance_board(meta_root: str, org: str) -> tuple[str, bool]:
    """Return (project_board.name, enabled) from tenant meta governance."""
    from pathlib import Path

    root = Path(meta_root).expanduser()
    preferred = root / "config" / f"governance-{org}.yaml"
    path = preferred if preferred.is_file() else None
    if path is None:
        matches = sorted((root / "config").glob("governance-*.yaml"))
        path = matches[0] if matches else None
    if path is None:
        raise ValidationError(f"no governance-*.yaml under {root / 'config'}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    board = data.get("project_board") if isinstance(data, dict) else None
    if not isinstance(board, dict):
        raise ValidationError(f"project_board missing in {path}")
    enabled = bool(board.get("enabled"))
    name = str(board.get("name") or "").strip()
    if not name:
        raise ValidationError(f"project_board.name missing in {path}")
    return name, enabled


def _short_repo(value: str) -> str:
    return (value or "").strip().rsplit("/", 1)[-1]


def _default_epic_body(initiative: str, epic: dict[str, Any]) -> str:
    spec = str(epic.get("spec_path") or "").strip()
    return (
        f"## EPIC — {initiative}\n\n"
        f"Projected from WorkManifest §9.\n\n"
        f"- Spec: `{spec or 'n/a'}`\n"
        f"- Codebase: `{epic.get('codebase') or epic.get('repo')}`\n"
    )


def _wave_body_from_tasks(wave_id: str, row: dict[str, Any]) -> str:
    tasks_field = row.get("tasks")
    tasks: list[Any] = tasks_field if isinstance(tasks_field, list) else []
    lines = [
        f"## Wave {wave_id}",
        "",
        "Projected TASK metadata from WorkManifest (board is not a second authority):",
        "",
    ]
    for task_any in tasks:
        if not isinstance(task_any, dict):
            continue
        task: dict[str, Any] = task_any
        tid = str(task.get("id") or "").strip()
        impl_field = task.get("implements")
        implements: list[Any] = impl_field if isinstance(impl_field, list) else []
        dep_field = task.get("depends_on")
        depends: list[Any] = dep_field if isinstance(dep_field, list) else []
        exit_raw = task.get("exit")
        exit_block: dict[str, Any] = exit_raw if isinstance(exit_raw, dict) else {}
        crit_field = exit_block.get("criteria")
        criteria: list[Any] = crit_field if isinstance(crit_field, list) else []
        proof_raw = exit_block.get("proof")
        proof: dict[str, Any] = proof_raw if isinstance(proof_raw, dict) else {}
        lines.append(f"### {tid}")
        lines.append(f"- implements: {', '.join(str(x) for x in implements) or '—'}")
        lines.append(f"- depends_on: {', '.join(str(x) for x in depends) or '—'}")
        if criteria:
            lines.append("- exit:")
            for c in criteria:
                lines.append(f"  - {c}")
        if proof:
            kind = proof.get("kind") or ""
            expected = proof.get("expected") or ""
            lines.append(f"- proof: kind={kind}; expected={expected}")
        lines.append("")
    verify = str(row.get("verify_command") or "").strip()
    if verify:
        lines.append(f"**verify_command:** `{verify}`")
    return "\n".join(lines).strip() + "\n"


def format_seed_summary(
    *,
    initiative: str,
    board_name: str,
    board_url: str,
    issue_urls: list[str],
    roles: list[str],
) -> str:
    """Stdout-shaped summary so board_verify can extract issue URLs."""
    lines = [
        f"# Board seed report — {initiative}",
        "",
        f"Board: {board_name}",
        f"Board URL: {board_url}",
        "",
        "## Result tree",
        "",
    ]
    for role, url in zip(roles, issue_urls, strict=False):
        lines.append(f"- {role}: {url}")
    lines.append("")
    lines.append("signals.seeded: true")
    return "\n".join(lines)
