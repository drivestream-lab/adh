"""Unit tests for Gate‑1 product-question builder."""

from __future__ import annotations

from src.adh_agents.programmes.pe.questions import (
    build_product_questions,
    format_questions_document,
)

_SAMPLE = """
## 2. Affected repositories

| Service | Repo | Team | Scope summary | Scope digest | Spec to create | Confidence |
|---------|------|------|---------------|--------------|----------------|------------|
| realworld-api | drivestream-lab/realworld-api | @t | Provide API | `sha` | x | High |
| realworld-web | drivestream-lab/realworld-web | @t | Consume UI | `sha` | y | High |

## 6. Cross-repository contracts

| Contract ID | Provider repo | Consumer repo | Capability | Owner | Status |
|-------------|---------------|---------------|------------|-------|--------|
| CTR-01 | drivestream-lab/realworld-api | drivestream-lab/realworld-web | CAP-02 — session | @t | new |
| CTR-02 | drivestream-lab/realworld-api | drivestream-lab/realworld-web | CAP-02 — register | @t | new |
"""


def test_build_product_questions_caps() -> None:
    qs = build_product_questions(_SAMPLE, initiative="INIT-REALWORLD-001", max_questions=3)
    assert len(qs) == 3
    assert qs[0].qid == "PQ-01"
    assert "realworld-api" in qs[0].repos[0]


def test_format_questions_document_includes_round() -> None:
    qs = build_product_questions(_SAMPLE, initiative="INIT-X", max_questions=2)
    doc = format_questions_document(
        initiative="INIT-X",
        pr_url="https://github.com/org/repo/pull/2",
        round_number=1,
        max_rounds=4,
        questions=qs,
    )
    assert "Round **1/4**" in doc
    assert "PQ-01" in doc
    assert "adh.pe" in doc


def test_empty_map_fallback() -> None:
    qs = build_product_questions("", initiative="INIT-EMPTY", max_questions=10)
    assert len(qs) == 1
    assert qs[0].qid == "PQ-01"
