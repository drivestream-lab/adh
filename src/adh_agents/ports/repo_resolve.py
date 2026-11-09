"""Resolve baton repo_ref → local checkout path via tenant context (no hardcoding)."""

from __future__ import annotations

from pathlib import Path

from src.models.tenant_models import TenantContext


class RepoResolveError(ValueError):
    """repo_ref cannot be mapped for this tenant."""


def resolve_repo_root(
    tenant: TenantContext,
    repo_ref: str,
    *,
    workspace_root: Path,
) -> Path:
    """Map ``repo_ref`` to a checkout directory.

    Accepts:
    - empty / tenant.meta_repo / basename of meta_root → meta_root
    - key in tenant.repos → ``workspace_root / name``
    - ``org/name`` → basename lookup against meta or repos
    """
    ref = (repo_ref or "").strip()
    meta_path = Path(tenant.meta_root).expanduser().resolve()
    meta_name = meta_path.name
    ws = workspace_root.expanduser().resolve()

    if not ref or ref == tenant.meta_repo or ref == meta_name:
        return meta_path

    name = ref.split("/")[-1].strip()
    if name == tenant.meta_repo or name == meta_name:
        return meta_path

    if ref in tenant.repos:
        return ws / ref
    if name in tenant.repos:
        return ws / name

    candidate = ws / name
    if candidate.is_dir():
        return candidate

    raise RepoResolveError(
        f"repo_ref {repo_ref!r} not in tenant {tenant.slug} "
        f"(meta={tenant.meta_repo}, repos={sorted(tenant.repos)})"
    )
