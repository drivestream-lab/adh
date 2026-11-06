"""Codegraph port stub — MCP adapter later; baton/rollup schema stays stable."""

from __future__ import annotations

from typing import Protocol


class CodegraphPort(Protocol):
    async def query(self, repo: str, question: str) -> str: ...


class DegradedCodegraph:
    """Filesystem-only stand-in until fleet MCP is wired."""

    async def query(self, repo: str, question: str) -> str:
        return f"(codegraph unavailable) repo={repo} q={question[:120]}"
