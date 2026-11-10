"""Thin OKF knowledge/ context for PE/PM prompts (empty-safe; compounds over time)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional


_MAX_CHARS_PER_FILE = 1200
_MAX_TOTAL_CHARS = 6000


def load_okf_context(
    meta_root: str | Path,
    *,
    repo_names: Optional[Iterable[str]] = None,
    max_chars_per_file: int = _MAX_CHARS_PER_FILE,
    max_total_chars: int = _MAX_TOTAL_CHARS,
) -> str:
    """Load foundation + optional repo/stack/contract head excerpts.

    Missing ``knowledge/`` is fine — returns empty string (programmes must tolerate).
    """
    root = Path(meta_root).expanduser()
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return ""

    paths: list[Path] = []
    foundation = knowledge / "foundation.md"
    if foundation.is_file():
        paths.append(foundation)

    for name in sorted({(n or "").strip() for n in (repo_names or []) if (n or "").strip()}):
        # Accept short repo name or org/repo → basename.
        short = name.split("/")[-1]
        candidate = knowledge / "repos" / f"{short}.md"
        if candidate.is_file():
            paths.append(candidate)

    # Lightweight: include up to two stack + contract files if present.
    for sub in ("stacks", "contracts"):
        folder = knowledge / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md"))[:2]:
            paths.append(path)

    chunks: list[str] = []
    total = 0
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        body = (text or "").strip()
        if not body:
            continue
        rel = (
            path.relative_to(root).as_posix() if root in path.parents or path == root else path.name
        )
        excerpt = body[: max(1, int(max_chars_per_file))]
        block = f"### {rel}\n{excerpt}"
        if total + len(block) > max_total_chars:
            break
        chunks.append(block)
        total += len(block)
    return "\n\n".join(chunks).strip()
