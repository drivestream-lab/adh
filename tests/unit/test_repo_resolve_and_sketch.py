"""D3 unit tests — tenant repo resolve + structured sketch (no hardcoding)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.adh_agents.ports.filesystem import structured_repo_sketch
from src.adh_agents.ports.repo_resolve import RepoResolveError, resolve_repo_root
from src.adh_agents.programmes.kb.heads import stub_heads_from_signals, validate_knowledge_rel
from src.models.tenant_models import TenantContext


def _tenant(tmp_path: Path) -> TenantContext:
    meta = tmp_path / "acme-meta"
    meta.mkdir()
    return TenantContext(
        slug="acme",
        org="example",
        meta_repo="acme-meta",
        meta_root=str(meta),
        repos={"acme-api": "python-backend", "acme-web": "nextjs-frontend"},
    )


def test_resolve_meta_and_app(tmp_path: Path) -> None:
    tenant = _tenant(tmp_path)
    ws = tmp_path
    (ws / "acme-api").mkdir()
    assert (
        resolve_repo_root(tenant, tenant.meta_repo, workspace_root=ws)
        == Path(tenant.meta_root).resolve()
    )
    assert resolve_repo_root(tenant, "acme-api", workspace_root=ws) == (ws / "acme-api").resolve()
    assert (
        resolve_repo_root(tenant, "example/acme-api", workspace_root=ws)
        == (ws / "acme-api").resolve()
    )


def test_resolve_unknown_raises(tmp_path: Path) -> None:
    tenant = _tenant(tmp_path)
    with pytest.raises(RepoResolveError):
        resolve_repo_root(tenant, "no-such-repo", workspace_root=tmp_path)


def test_structured_sketch_signals(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text("# hi\n", encoding="utf-8")
    (root / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    sketch = structured_repo_sketch(root, repo_ref="repo", limit=20)
    assert "README.md" in sketch.entrypoints
    assert "src" in sketch.signals or "dir:src" in sketch.signals
    assert sketch.path_count >= 2
    assert "README.md" in sketch.to_markdown()


def test_kb_heads_policy() -> None:
    assert validate_knowledge_rel("knowledge/repos/acme-api.md")
    assert not validate_knowledge_rel("knowledge/initiatives/INIT-1/notes.md")
    patches = stub_heads_from_signals(
        initiative="INIT-ACME-001",
        repo_ref="acme-meta",
        signals=["dir:src"],
        tenant_repos={"acme-api": "python-backend"},
    )
    paths = {p.relative_path for p in patches}
    assert "knowledge/foundation.md" in paths
    assert "knowledge/repos/acme-api.md" in paths
    assert "knowledge/stacks/python-backend.md" in paths
