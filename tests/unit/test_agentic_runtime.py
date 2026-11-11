"""Platform agentic extract / decide / lead_commands — no regex SSOT."""

from __future__ import annotations

import asyncio

from src.adh_agents.programmes.pm.validation_report import parse_validation_findings
from src.adh_agents.runtime.agentic_extract import (
    find_init_token,
    first_vf_id,
    github_pull_number,
    heading_sections,
    labeled_fields,
)
from src.adh_agents.runtime.lead_commands import (
    LeadCommand,
    classify_lead_command_agentic,
    match_lead_command,
)


def test_labeled_fields_and_headings() -> None:
    body = "outcome: pass\nwhy: ok\n\n## Critical (MUST FIX)\n\n| VF-01 | x |\n"
    assert labeled_fields(body)["outcome"] == "pass"
    sections = heading_sections(body)
    assert "critical (must fix)" in sections
    assert "VF-01" in sections["critical (must fix)"]


def test_github_pull_number() -> None:
    assert github_pull_number("https://github.com/org/repo/pull/42") == 42
    assert github_pull_number("https://github.com/org/repo/pull/7/files") == 7
    assert github_pull_number("https://github.com/org/repo/issues/3") is None


def test_find_init_token() -> None:
    assert find_init_token("traj INIT-REALWORLD-007 please") == "INIT-REALWORLD-007"
    assert find_init_token("no init here") is None


def test_first_vf_id_and_validation_parse() -> None:
    assert first_vf_id("| VF-3 | type | loc |") == "VF-03"
    assert first_vf_id("see VF12 in text") == "VF-12"
    body = """
## Critical (MUST FIX — ship blockers)

| VF | Type | Location | Target | Check | Finding | Rec |
|----|------|----------|--------|-------|---------|-----|
| VF-01 | gap | prd | must | x | Broken flow | Fix it |

## Verify (optional)

| VF-02 | note | a | b | c | Check later | — |
"""
    rows = parse_validation_findings(body)
    assert [r["id"] for r in rows] == ["VF-01", "VF-02"]
    assert rows[0]["severity"] == "Critical"
    assert rows[1]["severity"] == "Verify"


def test_match_lead_command_phrase_lists() -> None:
    assert match_lead_command("engg go") == LeadCommand.ENGG_GO
    assert match_lead_command("hire engg please") == LeadCommand.HIRE_ENGG
    assert match_lead_command("traj") == LeadCommand.TRAJ
    assert match_lead_command("show trajectory") == LeadCommand.TRAJ
    assert match_lead_command("resume") == LeadCommand.RESUME
    assert match_lead_command("archive task") == LeadCommand.ARCHIVE_TASK
    assert match_lead_command("hello world") is None


def test_classify_lead_command_agentic_hole() -> None:
    """Reserved hole returns None until product enables agentic classify."""

    class _Stub:
        pass

    assert (
        asyncio.run(classify_lead_command_agentic(_Stub(), "engg go")) is None  # type: ignore[arg-type]
    )
