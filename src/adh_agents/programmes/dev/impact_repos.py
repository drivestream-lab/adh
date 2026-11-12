"""Impact-Map affected repos — pipe-table parse (no regex); tenant-scoped."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.models.tenant_models import TenantContext


@dataclass(frozen=True)
class ImpactedRepo:
    """One affected product repo from the Impact-Map §2 table."""

    service: str
    repo: str  # short name (last path segment)
    full_name: str  # org/repo when present
    spec_to_create: str = ""  # relative path or filename from map when present


def parse_affected_repos(
    impact_map_body: str,
    *,
    meta_repo: str,
) -> list[ImpactedRepo]:
    """Extract **Affected** product-repo rows from the Impact-Map.

    Impact maps carry several ``Service | Repo`` tables (Affected, Deferred,
    Dependent, Control-plane). Only the Affected table has ``Spec to create``
    and/or ``Scope digest``. Parsing every service/repo table incorrectly
    opened Spec PRs for deferred repos (thin stub bodies only).

    Excludes the tenant control-plane ``meta_repo``. No tenant/INIT hardcoding.
    """
    meta_short = _short_repo(meta_repo)
    rows = _pipe_rows(impact_map_body or "")
    out: list[ImpactedRepo] = []
    seen: set[str] = set()
    i = 0
    while i < len(rows):
        header = rows[i]
        svc_i = _header_index(header, "service")
        repo_i = _header_index(header, "repo")
        spec_i = _header_index(header, "spec to create", "spec")
        digest_i = _header_index(header, "scope digest", "digest")
        i += 1
        if svc_i is None or repo_i is None:
            continue
        # Affected product table only — Deferred/Dependent/Control-plane share
        # Service|Repo but lack Spec-to-create / Scope-digest columns.
        if spec_i is None and digest_i is None:
            continue
        while i < len(rows):
            row = rows[i]
            # Next table header (service+repo again, or contract table).
            if _header_index(row, "service") is not None and _header_index(row, "repo") is not None:
                break
            if _header_index(row, "contract id", "contract") is not None:
                break
            i += 1
            if len(row) <= max(svc_i, repo_i):
                continue
            service = row[svc_i].strip().strip("`")
            raw_repo = row[repo_i].strip().strip("`")
            if not service or not raw_repo:
                continue
            name = _short_repo(raw_repo)
            if not name or name.lower() in seen:
                continue
            if name == meta_short or raw_repo == meta_repo:
                continue
            # Skip deferred / empty placeholders.
            if name in {"—", "-"} or service in {"—", "-"}:
                continue
            seen.add(name.lower())
            spec = ""
            if spec_i is not None and spec_i < len(row):
                spec = row[spec_i].strip().strip("`")
            full = raw_repo if "/" in raw_repo else name
            out.append(
                ImpactedRepo(
                    service=service,
                    repo=name,
                    full_name=full,
                    spec_to_create=spec,
                )
            )
    return out


def resolve_repo_root(workspace_root: Path, repo: str) -> Optional[Path]:
    """Checkout under ORCH workspace root (scale: any tenant repo name)."""
    name = _short_repo(repo)
    if not name:
        return None
    candidate = Path(workspace_root).expanduser().resolve() / name
    if candidate.is_dir() and (candidate / ".git").is_dir():
        return candidate
    return None


def resolve_repo_root_for_tenant(
    tenant: TenantContext, workspace_root: Path, repo: str
) -> Optional[Path]:
    """Prefer workspace_root/<repo>; fail soft only when checkout absent."""
    del tenant  # topology already validated at registry load; reserved for future pins
    return resolve_repo_root(workspace_root, repo)


def _short_repo(raw: str) -> str:
    text = (raw or "").strip().strip("`")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text.strip()


def _pipe_rows(text: str) -> list[list[str]]:
    """Split markdown table lines on `|` — no regex (same approach as PE Gate‑1)."""
    rows: list[list[str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        if all(not c or set(c) <= {"-", ":", " "} for c in cells):
            continue
        rows.append(cells)
    return rows


def _header_index(header: list[str], *names: str) -> int | None:
    lowered = [h.lower() for h in header]
    for name in names:
        key = name.lower()
        for i, cell in enumerate(lowered):
            if key == cell or key in cell:
                return i
    return None
