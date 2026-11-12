"""Fail-closed board seed proof from skill output."""

from __future__ import annotations

from src.adh_agents.programmes.dev.board_verify import (
    extract_github_issue_urls,
    verify_board_seed_output,
)


def test_extract_dedupes_issue_urls() -> None:
    text = (
        "Seeded EPIC https://github.com/drivestream-lab/realworld-api/issues/10\n"
        "Wave https://github.com/drivestream-lab/realworld-api/issues/11\n"
        "again https://github.com/drivestream-lab/realworld-api/issues/10\n"
    )
    urls = extract_github_issue_urls(text)
    assert urls == (
        "https://github.com/drivestream-lab/realworld-api/issues/10",
        "https://github.com/drivestream-lab/realworld-api/issues/11",
    )


def test_verify_fails_without_urls() -> None:
    proof = verify_board_seed_output(
        "Board seed complete (commands printed; has_issues=false).",
        initiative="INIT-REALWORLD-001",
    )
    assert not proof.ok
    assert "Board seed proof failed" in proof.reason
    assert "reseed board" in proof.reason
    assert proof.issue_urls == ()


def test_verify_passes_with_issue_urls() -> None:
    text = "Created https://github.com/drivestream-lab/realworld-meta/issues/42"
    proof = verify_board_seed_output(text, initiative="INIT-REALWORLD-001")
    assert proof.ok
    assert proof.issue_urls == ("https://github.com/drivestream-lab/realworld-meta/issues/42",)
