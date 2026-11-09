"""Filesystem port for read agent (degraded stand-in for codegraph)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Deterministic entrypoint / signal markers (path suffixes / names — not tenant-specific).
_ENTRY_NAMES = (
    "README.md",
    "readme.md",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Dockerfile",
    "Makefile",
)
_SIGNAL_PREFIXES = (
    "prd/",
    "knowledge/",
    "docs/",
    "src/",
    "app/",
    "config/",
    "stacks/",
    "contracts/",
)


@dataclass
class RepoSketch:
    """Structured one-repo walk evidence (artefact body; keep Buzz light)."""

    repo_ref: str
    root: str
    entrypoints: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    path_count: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"# Read walk — `{self.repo_ref}`",
            "",
            f"- **Root:** `{self.root}`",
            f"- **Files sampled:** {self.path_count}",
            "",
            "## Entrypoints",
            "",
        ]
        if self.entrypoints:
            lines.extend(f"- `{p}`" for p in self.entrypoints)
        else:
            lines.append("- (none detected)")
        lines.extend(["", "## Signals", ""])
        if self.signals:
            lines.extend(f"- `{s}`" for s in self.signals)
        else:
            lines.append("- (none)")
        lines.extend(["", "## Path sample", ""])
        lines.extend(f"- `{p}`" for p in self.paths[:40])
        lines.append("")
        return "\n".join(lines)


def list_repo_sketch(root: Path, *, limit: int = 40) -> list[str]:
    """Shallow path list (legacy helper). Prefer :func:`structured_repo_sketch`."""
    sketch = structured_repo_sketch(root, repo_ref=root.name, limit=limit)
    return list(sketch.paths)


def structured_repo_sketch(
    root: Path,
    *,
    repo_ref: str,
    limit: int = 80,
) -> RepoSketch:
    """Deterministic structured sketch for one repo checkout."""
    if not root.exists():
        return RepoSketch(repo_ref=repo_ref, root=str(root), path_count=0)

    paths: list[str] = []
    entrypoints: list[str] = []
    signal_hits: set[str] = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.parts):
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        if rel.startswith(".git/") or "/.git/" in f"/{rel}/":
            continue
        paths.append(rel)
        name = path.name
        if name in _ENTRY_NAMES or rel in _ENTRY_NAMES:
            entrypoints.append(rel)
        for prefix in _SIGNAL_PREFIXES:
            if rel.startswith(prefix) or f"/{prefix}" in f"/{rel}":
                signal_hits.add(prefix.rstrip("/"))
                break
        if len(paths) >= limit:
            break

    # Also note top-level dirs as signals when present.
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            signal_hits.add(f"dir:{child.name}")

    return RepoSketch(
        repo_ref=repo_ref,
        root=str(root.resolve()),
        entrypoints=sorted(set(entrypoints))[:20],
        paths=paths,
        signals=sorted(signal_hits)[:30],
        path_count=len(paths),
    )
