"""Load Stratum Hermes dry-run fixtures (no src changes; tests/verify only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "hermes" / "stratum"
SCENARIOS_PATH = FIXTURE_ROOT / "scenarios.yaml"


def load_index() -> dict[str, Any]:
    data = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "scenarios" not in data:
        raise RuntimeError(f"invalid scenario index: {SCENARIOS_PATH}")
    return data


def scenario_dir(scenario_id: str) -> Path:
    index = load_index()
    sc = index["scenarios"][scenario_id]
    return FIXTURE_ROOT / sc["dir"]


def read_fixture(scenario_id: str, rel: str) -> str:
    path = scenario_dir(scenario_id) / rel
    return path.read_text(encoding="utf-8")


def impact_excerpt(scenario_id: str, *, max_chars: int = 6000) -> str:
    index = load_index()
    sc = index["scenarios"][scenario_id]
    body = read_fixture(scenario_id, sc["impact_map"])
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "\n\n… omitted from middle …\n"


def pack_variables(scenario_id: str, hop_id: str) -> dict[str, Any]:
    """Build PromptService variables for a hop against a Stratum scenario."""
    index = load_index()
    sc = index["scenarios"][scenario_id]
    initiative = sc["initiative"]
    impact = impact_excerpt(scenario_id)
    think = read_fixture(scenario_id, sc["think"])
    quality = read_fixture(scenario_id, sc["quality"])
    first = sc["expected_affected"][0]
    repo = first["repo"]
    map_spec = first["spec_to_create"]

    common = {
        "initiative": initiative,
        "kb_excerpt": "(none)",
    }

    if hop_id == "pe.impact.challenge":
        return {**common, "impact_excerpt": impact}
    if hop_id == "pe.gate1.recommend":
        return {
            **common,
            "round_number": "1",
            "max_rounds": "3",
            "reply_tokens": "await_pm, new_round, hold, attest",
            "questions_summary": (
                f"- Does {repo} Spec `{map_spec}` cover CAP/CTR without pulling deferred HITL/IaC?"
            ),
            "impact_excerpt": impact,
        }
    if hop_id == "dev.debate.pass":
        return {
            **common,
            "purpose": "coding-readiness",
            "pass_number": "1",
            "max_passes": "4",
            "reply_tokens": "`coding ready`, `hold`, `another round`",
            "challenge": "First pass: Spec + Impact-Map boundaries for Stratum stack.",
            "context": impact,
            "prior": "(none)",
        }
    if hop_id == "dev.decide.reply":
        return {
            **common,
            "role_id": "adh.dev",
            "purpose": "coding-readiness",
            "reply_tokens": "coding ready, hold",
            "context": impact,
        }
    if hop_id == "dev.decide.outcome":
        return {
            **common,
            "role_id": "adh.dev",
            "node_id": "spec-pr-action",
            "allowed_outcomes": "success, failed, blocked",
            "evidence": (
                f"Impact-Map Affected={repo} Spec={map_spec}; "
                "Deferred tables present but must not open Spec PRs."
            ),
        }
    if hop_id == "kb.learning.harvest":
        return {
            **common,
            "purpose": "post-fence",
            "evidence": impact[:2000],
        }
    if hop_id == "kb.head.fill":
        return {
            **common,
            "repo_ref": first["full_name"],
            "stub": (
                f"# repos/{repo}\n\n## entrypoints\n(pending)\n\n" "## contracts\n(pending)\n"
            ),
        }
    if hop_id == "pm.validate.card":
        return {
            **common,
            "prd_path": f"prd/{initiative}.md",
            "findings": (
                "VF-01 | medium | Impact-Map §3 Deferred | "
                "Confirm deferred repos stay out of Spec wave for this INIT."
            ),
        }
    if hop_id == "pm.promote.judge":
        return {
            **common,
            "think_list": f"- C1 — `prd/reports/{sc['think']}`\n\n{think[:2500]}",
            "quality_path": f"prd/reports/{sc['quality']}",
            "brief_path": f"prd/reports/{initiative}-hermes-promote-brief.md",
            "labels": "C1",
            "extra": "(none)",
        }
    if hop_id == "pm.postpm.judge":
        return {
            **common,
            "prd_path": f"prd/{initiative}.md",
            "validation_path": f"prd/reports/{initiative}-validation.md",
            "resolution_path": f"prd/reports/{initiative}-resolution.md",
            "brief_path": f"prd/reports/{initiative}-hermes-post-pm-brief.md",
            "extra": quality[:1500],
        }
    raise KeyError(f"unknown hop_id={hop_id}")
