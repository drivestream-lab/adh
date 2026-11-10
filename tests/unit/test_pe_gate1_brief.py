"""Gate‑1 decision paper — PM promote / post-pm recommendation parity."""

from __future__ import annotations

from src.adh_agents.programmes.pe.gate1_brief import (
    build_gate1_decision_card,
    format_gate1_brief_markdown,
    format_gate1_buzz_bluf,
    hermes_gate1_brief_path,
)
from src.adh_agents.programmes.pe.questions import build_product_questions
from src.adh_agents.programmes.pm.temp_papers import gate1_temp_paths

_SAMPLE = """
## 2. Affected repositories

| Service | Repo | Team | Scope summary | Scope digest | Spec to create | Confidence |
|---------|------|------|---------------|--------------|----------------|------------|
| realworld-api | drivestream-lab/realworld-api | @t | Provide API | `sha` | x | High |

## 6. Cross-repository contracts

| Contract ID | Provider repo | Consumer repo | Capability | Owner | Status |
|-------------|---------------|---------------|------------|-------|--------|
| CTR-01 | drivestream-lab/realworld-api | drivestream-lab/realworld-web | CAP-02 — session | @t | new |
"""


def test_hermes_gate1_brief_path() -> None:
    assert hermes_gate1_brief_path("INIT-X") == "prd/reports/INIT-X-hermes-gate1-brief.md"


def test_gate1_brief_has_buying_not_buying() -> None:
    qs = build_product_questions(_SAMPLE, initiative="INIT-X", max_questions=3)
    card = build_gate1_decision_card(
        initiative="INIT-X",
        round_number=1,
        max_rounds=4,
        questions=qs,
        recommend="await_pm",
    )
    assert card.recommend == "await_pm"
    assert card.locking
    assert card.not_locking
    md = format_gate1_brief_markdown(
        card,
        initiative="INIT-X",
        round_number=1,
        max_rounds=4,
        questions_path="prd/reports/PE-Product-Questions-INIT-X.md",
        pr_url="https://github.com/org/repo/pull/2",
        questions=qs,
    )
    assert "recommend: await_pm" in md
    assert "**Buying.**" in md
    assert "**Not buying.**" in md
    assert "**Choose another if.**" in md
    assert "`attest`" in md
    assert "`new_round`" in md
    assert "PQ-01" in md


def test_gate1_buzz_stays_light() -> None:
    bluf = format_gate1_buzz_bluf(
        initiative="INIT-X",
        round_number=1,
        max_rounds=4,
        question_count=3,
        brief_path="prd/reports/INIT-X-hermes-gate1-brief.md",
        questions_path="prd/reports/PE-Product-Questions-INIT-X.md",
    )
    assert "**I did.**" in bluf
    assert "**Buying.**" not in bluf
    assert "ack_pe" not in bluf
    assert "Gate‑1" not in bluf
    assert "Gate-1" not in bluf
    assert "park" in bluf or "another round" in bluf


def test_gate1_temp_paths_include_brief() -> None:
    paths = gate1_temp_paths("INIT-X", meta_repo="org/meta")
    assert "prd/reports/INIT-X-hermes-gate1-brief.md" in paths
    assert "prd/reports/PE-Product-Questions-INIT-X.md" in paths
