"""Parse Impact-Map affected repos and resolve local checkouts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_CELL = re.compile(
    r"`?(?:[\w.-]+/)?(?P<name>[\w.-]+)`?",
)
_TABLE_ROW = re.compile(
    r"^\|\s*(?P<service>[^|]+?)\s*\|\s*(?P<repo>[^|]+?)\s*\|",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ImpactedRepo:
    """One affected product repo from the Impact-Map table."""

    service: str
    repo: str  # short name, e.g. realworld-api
    full_name: str  # org/repo when present


def parse_affected_repos(impact_map_body: str) -> list[ImpactedRepo]:
    """Extract §2 Affected repositories rows (fail soft → empty)."""
    text = impact_map_body or ""
    # Prefer the section between "## 2." and the next "## ".
    start = text.find("## 2.")
    if start < 0:
        start = text.find("## Affected")
    chunk = text[start:] if start >= 0 else text
    end = chunk.find("\n## ", 4)
    if end > 0:
        chunk = chunk[:end]

    out: list[ImpactedRepo] = []
    seen: set[str] = set()
    for m in _TABLE_ROW.finditer(chunk):
        service = (m.group("service") or "").strip()
        raw_repo = (m.group("repo") or "").strip()
        if not raw_repo or not service:
            continue
        if set(service) <= {"-", "—", " "} or set(raw_repo.strip("`")) <= {"-", "—", " "}:
            continue
        if service.lower() in {"service"} or raw_repo.lower().strip("`") in {"repo"}:
            continue
        if "realworld-meta" in raw_repo.lower() or service.lower().endswith("-meta"):
            # Control-plane host — not a development mutate target.
            continue
        name = _short_repo(raw_repo)
        if not name or name.lower() in seen:
            continue
        if set(name) <= {"-", "—"} or name.lower() in {"repo"}:
            continue
        seen.add(name.lower())
        full = raw_repo.strip().strip("`")
        if "/" not in full:
            full = name
        out.append(ImpactedRepo(service=service, repo=name, full_name=full))
    return out


def resolve_repo_root(meta_root: str | Path, repo: str) -> Optional[Path]:
    """Sibling checkout next to the tenant meta root (or one level up)."""
    meta = Path(meta_root).expanduser().resolve()
    name = _short_repo(repo)
    if not name:
        return None
    for base in (meta.parent, meta.parent.parent):
        candidate = base / name
        if candidate.is_dir() and (candidate / ".git").exists():
            return candidate
    return None


def _short_repo(raw: str) -> str:
    text = (raw or "").strip().strip("`")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    m = _REPO_CELL.search(text)
    return (m.group("name") if m else text).strip()
