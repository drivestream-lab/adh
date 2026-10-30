"""Pinned runtime copies of adh-meta rubrics. Hermes cannot edit threshold_x."""

from typing import Any

RUBRIC_ENG: dict[str, Any] = {
    "id": "rubric-eng",
    "lane": "eng",
    "threshold_x": 2.7,
    "hard_fail": ["process_integrity"],
    "dimensions": {
        "process_integrity": {"weight": 0.25, "blocker_at": 0},
        "spec_fidelity": {"weight": 0.25},
        "verify": {"weight": 0.25},
        "knowledge": {"weight": 0.15},
        "harness_hygiene": {"weight": 0.10},
    },
}

RUBRIC_PM: dict[str, Any] = {
    "id": "rubric-pm",
    "lane": "pm",
    "threshold_x": 2.7,
    "dimensions": {
        "citation": {"weight": 0.25},
        "journeys": {"weight": 0.25},
        "req_coverage": {"weight": 0.30},
        "findings_quality": {"weight": 0.20},
    },
}


def weighted_overall(scores: dict[str, float], rubric: dict[str, Any]) -> float:
    """Deterministic overall from dimension scores and pinned weights."""
    total = 0.0
    for name, spec in rubric["dimensions"].items():
        total += float(scores.get(name, 0.0)) * float(spec["weight"])
    return round(total, 3)
