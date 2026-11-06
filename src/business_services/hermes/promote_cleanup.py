"""Allowlist builder for archiving pre-promote PM scratch reports."""

from __future__ import annotations

import re
from typing import Iterable

# Initiative segment is whatever sits before the known scratch suffix — not a
# hardcoded INIT- token. Callers still pass the bound initiative for equality.
_THINK = re.compile(r"^prd/reports/(.+)-prd-think(?:-\d+)?\.md$", re.I)
_QUALITY = re.compile(r"^prd/reports/(.+)-prd-quality\.md$", re.I)
_ASK = re.compile(r"^prd/reports/(.+)-prd-ask\.md$", re.I)
_RECOMMEND = re.compile(r"^prd/reports/(.+)-prd-recommend\.md$", re.I)


def archive_prefix(initiative: str) -> str:
    return f"prd/reports/_archive/{initiative}"


def is_prepromote_scratch(path: str, initiative: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    init = initiative.upper()
    for pattern in (_THINK, _QUALITY, _ASK, _RECOMMEND):
        match = pattern.match(normalized)
        if match and match.group(1).upper() == init:
            return True
    return False


def scratch_paths_for_initiative(initiative: str, candidates: Iterable[str]) -> list[str]:
    """Return allowlisted scratch paths for an initiative; never includes prd/{id}.md."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        path = str(raw or "").replace("\\", "/").strip()
        if not path or path in seen:
            continue
        if path.startswith("prd/") and not path.startswith("prd/reports/"):
            continue
        if is_prepromote_scratch(path, initiative):
            out.append(path)
            seen.add(path)
    return out


def archive_dest(path: str, initiative: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return f"{archive_prefix(initiative)}/{name}"
