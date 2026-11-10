"""OKF context loader — empty-safe thin excerpts."""

from __future__ import annotations

from pathlib import Path

from src.adh_agents.collaboration.okf_context import load_okf_context


def test_missing_knowledge_returns_empty(tmp_path: Path) -> None:
    assert load_okf_context(tmp_path) == ""


def test_loads_foundation_and_repo(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    (knowledge / "repos").mkdir(parents=True)
    (knowledge / "foundation.md").write_text("# foundation\n\nHarness norms.\n", encoding="utf-8")
    (knowledge / "repos" / "api.md").write_text("# repos/api\n\nEntrypoints\n", encoding="utf-8")
    text = load_okf_context(tmp_path, repo_names=["org/api", "api"])
    assert "foundation" in text.lower()
    assert "repos/api.md" in text or "api.md" in text
