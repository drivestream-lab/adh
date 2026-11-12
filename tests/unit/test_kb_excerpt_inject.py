"""Mode A — OKF knowledge excerpt loader for behaviour prompt inject."""

from __future__ import annotations

from pathlib import Path

from src.adh_agents.programmes.kb.heads import load_kb_excerpt


def test_load_kb_excerpt_reads_foundation_and_repos(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "foundation.md").write_text("# foundation\n\nnorms\n", encoding="utf-8")
    repos = knowledge / "repos"
    repos.mkdir()
    (repos / "realworld-api.md").write_text(
        "# repos/realworld-api\n\nentrypoints\n", encoding="utf-8"
    )
    text = load_kb_excerpt(tmp_path, repos=["realworld-api", "missing"])
    assert "foundation" in text
    assert "realworld-api" in text


def test_load_kb_excerpt_empty_without_knowledge(tmp_path: Path) -> None:
    assert load_kb_excerpt(tmp_path, repos=["x"]) == ""
