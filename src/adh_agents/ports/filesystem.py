"""Filesystem port for read agent (degraded stand-in for codegraph)."""

from __future__ import annotations

from pathlib import Path


def list_repo_sketch(root: Path, *, limit: int = 40) -> list[str]:
    """Shallow path list for Buzz rollup evidence (not a full walk)."""
    if not root.exists():
        return []
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                out.append(str(path.relative_to(root)))
            except ValueError:
                out.append(str(path))
            if len(out) >= limit:
                break
    return out
