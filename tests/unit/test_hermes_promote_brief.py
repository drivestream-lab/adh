"""Hermes PM promote brief fields from Hermes judge artefact + quality fallback."""

from __future__ import annotations

from src.adh_agents.programmes.pm.authoring import (
    promote_brief_from_hermes,
    promote_brief_from_quality,
)

_THINKS = [
    "prd/reports/INIT-RW-001-prd-think.md",
    "prd/reports/INIT-RW-001-prd-think-2.md",
]

_SCORECARD = """
# INIT-RW-001-prd-quality

| Rank | tie |

Prefer C2 if a single pick is needed (explicit authenticate CAP, register≠publish).

### C1 `INIT-RW-001-prd-think.md`

| Bar | Result | Material FAIL? | Evidence (id + quote) |
|-----|--------|----------------|------------------------|
| B1 Job | PASS | no | Job: “first author publishes so a visitor can read”. |

### C2 `INIT-RW-001-prd-think-2.md`

| Bar | Result | Material FAIL? | Evidence (id + quote) |
|-----|--------|----------------|------------------------|
| B1 Job | PASS | no | Job: “later visitor discovers the first real article without the author”. |

## Next (human)

- Recommended single pick when jobs agree: **C2** `prd/reports/x.md` (authenticate CAP, multi-publish retention)
"""


def test_promote_brief_uses_recommended_pick_why_and_job_example() -> None:
    judgment = promote_brief_from_quality(_SCORECARD, _THINKS)
    assert judgment.recommend == "C2"
    assert "authenticate CAP" in judgment.bluf
    assert judgment.example.startswith("If we promote C2")
    assert "later visitor discovers" in judgment.example
    assert "prd-critic" not in judgment.bluf.lower()
    assert judgment.revise_if  # thin fallback still has revise_if


def test_promote_brief_falls_back_when_quality_silent() -> None:
    judgment = promote_brief_from_quality("", _THINKS)
    assert judgment.recommend == "C2"
    assert "scorecard" in judgment.bluf.lower() or "pick" in judgment.bluf.lower()
    assert "C2" in judgment.example


_HERMES_BRIEF = """
# Hermes promote brief — INIT-RW-001

recommend: C2

## bluf
Promote C2 — authenticate + register≠publish; C1 leaves that implicit.

## locking
- Explicit authenticate CAP
- Register is not publish

## not_locking
- Thinner C1 seam story

## revise_if
- Lead wants thinner seam → pick C1

## example
A later visitor finds the first real article on the public home without the author’s session.

## options
- C1 — thinner seam story
- C2 — fuller publish loop
"""


def test_promote_brief_from_hermes_owns_judgment() -> None:
    judgment = promote_brief_from_hermes(_HERMES_BRIEF, _THINKS)
    assert judgment is not None
    assert judgment.recommend == "C2"
    assert "authenticate" in judgment.bluf
    assert judgment.recommend_why == judgment.bluf
    assert "later visitor" in judgment.example
    assert judgment.locking
    assert judgment.not_locking


def test_promote_brief_from_hermes_rejects_empty() -> None:
    assert promote_brief_from_hermes("", _THINKS) is None
    assert promote_brief_from_hermes("recommend: C9\n## bluf\nx\n## example\ny", _THINKS) is None
    # Legacy recommend_why shape is rejected (schema A only).
    assert (
        promote_brief_from_hermes("recommend: C2\n## recommend_why\nx\n## example\ny", _THINKS)
        is None
    )
