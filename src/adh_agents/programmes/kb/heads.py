"""OKF knowledge/ head stubs + LLM fill (heads-only; no initiative folders)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_ALLOWED_ROOT_FILES = frozenset({"foundation.md", "README.md"})
_ALLOWED_DIRS = frozenset({"foundation", "stacks", "repos", "contracts"})

_REPO_STUB = """# repos/{name}

## Entrypoints
- (pending)

## Pattern pointers
- (pending)

## ADR index
- (pending)

## Watchlist
- (pending)

## Sources
- {source} (footnote only — not an initiative folder)
"""

_STACK_STUB = """# stacks/{name}

## Programme overlay
- (pending)

## Sources
- {source} (footnote only)
"""


@dataclass
class HeadPatch:
    relative_path: str
    contents: str


def validate_knowledge_rel(rel: str) -> bool:
    """True when path stays under OKF heads (no initiatives/)."""
    norm = rel.replace("\\", "/").lstrip("/")
    if not norm.startswith("knowledge/"):
        return False
    rest = norm[len("knowledge/") :]
    if ".." in rest.split("/"):
        return False
    if rest.startswith("initiatives/") or "/initiatives/" in f"/{rest}/":
        return False
    if rest in _ALLOWED_ROOT_FILES:
        return True
    top = rest.split("/", 1)[0]
    return top in _ALLOWED_DIRS


def stub_heads_from_signals(
    *,
    initiative: str,
    repo_ref: str,
    signals: list[str],
    tenant_repos: dict[str, str],
) -> list[HeadPatch]:
    """Deterministic scaffolds from tenant repo topology (+ optional read signals)."""
    del signals  # reserved for LLM context; paths come from topology / OKF rules
    del repo_ref
    source = initiative or "(unknown)"
    patches: list[HeadPatch] = [
        HeadPatch(
            relative_path="knowledge/foundation.md",
            contents=(
                "# foundation\n\n"
                "## Harness / prove / path norms\n- (pending)\n\n"
                f"## Sources\n- {source} (footnote only)\n"
            ),
        )
    ]
    for repo_name, stack in sorted(tenant_repos.items()):
        patches.append(
            HeadPatch(
                relative_path=f"knowledge/repos/{repo_name}.md",
                contents=_REPO_STUB.format(name=repo_name, source=source),
            )
        )
        stack_name = (stack or "").strip()
        if stack_name:
            patches.append(
                HeadPatch(
                    relative_path=f"knowledge/stacks/{stack_name}.md",
                    contents=_STACK_STUB.format(name=stack_name, source=source),
                )
            )
    seen: set[str] = set()
    out: list[HeadPatch] = []
    for patch in patches:
        if not validate_knowledge_rel(patch.relative_path):
            continue
        if patch.relative_path in seen:
            continue
        seen.add(patch.relative_path)
        out.append(patch)
    return out


def load_kb_excerpt(
    meta_root: Path,
    *,
    repos: list[str] | None = None,
    max_chars: int = 6000,
) -> str:
    """Concatenate OKF knowledge head excerpts for behaviour-prompt inject (Mode A)."""
    root = meta_root.expanduser() / "knowledge"
    if not root.is_dir():
        return ""
    chunks: list[str] = []
    foundation = root / "foundation.md"
    if foundation.is_file():
        chunks.append(foundation.read_text(encoding="utf-8")[:2000])
    for name in repos or []:
        short = (name or "").strip().rsplit("/", 1)[-1]
        if not short:
            continue
        path = root / "repos" / f"{short}.md"
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8")[:2000])
    text = "\n\n---\n\n".join(c.strip() for c in chunks if c.strip())
    return text[:max_chars]


def merge_llm_sections(stub: str, filled: str) -> str:
    """Prefer LLM body when it still looks like a head doc; else keep stub."""
    text = (filled or "").strip()
    if not text:
        return stub
    if "initiatives/" in text.lower():
        return stub
    if not text.startswith("#"):
        return stub
    return text + ("\n" if not text.endswith("\n") else "")


def write_patches(
    meta_root: Path, patches: list[HeadPatch], *, overwrite: bool = False
) -> list[str]:
    """Write patches under meta_root; return relative paths written."""
    written: list[str] = []
    root = meta_root.expanduser()
    for patch in patches:
        if not validate_knowledge_rel(patch.relative_path):
            continue
        dest = root / patch.relative_path
        if dest.is_file() and not overwrite:
            written.append(patch.relative_path)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(patch.contents, encoding="utf-8")
        written.append(patch.relative_path)
    return written
