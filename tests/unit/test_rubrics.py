"""Pinned rubric math used by Hermes grades."""

from src.configs.rubrics import RUBRIC_ENG, weighted_overall


def test_eng_overall_below_x() -> None:
    scores = {
        "process_integrity": 2.0,
        "spec_fidelity": 1.0,
        "verify": 3.0,
        "knowledge": 2.0,
        "harness_hygiene": 2.0,
    }
    overall = weighted_overall(scores, RUBRIC_ENG)
    assert overall < RUBRIC_ENG["threshold_x"]
    assert overall == 2.0


def test_process_integrity_zero_still_computes() -> None:
    scores = {
        "process_integrity": 0.0,
        "spec_fidelity": 3.0,
        "verify": 3.0,
        "knowledge": 3.0,
        "harness_hygiene": 3.0,
    }
    overall = weighted_overall(scores, RUBRIC_ENG)
    assert overall == 2.25
