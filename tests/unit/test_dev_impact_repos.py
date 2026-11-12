"""Impact-Map affected-repo parsing for Dev YAML walker (no regex)."""

from __future__ import annotations

from src.adh_agents.programmes.dev.impact_repos import parse_affected_repos
from src.adh_agents.runtime.agentic_extract import extract_allowed, labeled_fields


_SAMPLE = """
## 2. Affected repositories

| Service | Repo | Team | Scope summary | Spec to create |
|---------|------|------|---------------|----------------|
| api | drivestream-lab/tenant-api | @x | api | INIT-X-api.md |
| web | drivestream-lab/tenant-web | @y | web | INIT-X-web.md |
| meta | drivestream-lab/tenant-meta | @z | control plane | — |

## 3. Deferred repositories

| Service | Repo | Reason | Revisit condition |
|---------|------|--------|-------------------|
| web-ui | drivestream-lab/tenant-web-ui | explicit non-goal | later INIT |
| local | drivestream-lab/tenant-local | compose only | eng prove host |

## 4. Dependent repositories

| Service | Repo | Depends on | Potential impact | Disposition |
|---------|------|------------|------------------|-------------|
| mobile | drivestream-lab/tenant-mobile | tenant-api | future client | deferred |
"""


def test_parse_affected_repos_excludes_meta() -> None:
    rows = parse_affected_repos(_SAMPLE, meta_repo="tenant-meta")
    assert [r.repo for r in rows] == ["tenant-api", "tenant-web"]
    assert rows[0].spec_to_create == "INIT-X-api.md"


def test_parse_affected_repos_skips_deferred_and_dependent_tables() -> None:
    """Regression: INIT-004 opened thin Spec PRs for deferred web/local."""
    rows = parse_affected_repos(_SAMPLE, meta_repo="tenant-meta")
    names = {r.repo for r in rows}
    assert "tenant-web-ui" not in names
    assert "tenant-local" not in names
    assert "tenant-mobile" not in names


def test_pass_chain_has_no_deps_acceptance() -> None:
    from src.adh_agents.programmes.dev.programme import _PASS_CHAIN

    assert "deps-acceptance" not in _PASS_CHAIN
    assert _PASS_CHAIN[0] == "spec-draft"
    assert _PASS_CHAIN[-1] == "board-tickets-action"
    assert "spec-pr-action" in _PASS_CHAIN
    assert "spec-merge" in _PASS_CHAIN


def test_labeled_extract_outcome() -> None:
    body = "outcome: pass\nwhy: skill look clean\n"
    assert labeled_fields(body)["outcome"] == "pass"
    assert extract_allowed(body, field="outcome", allowed=["pass", "failed"]) == "pass"
    assert extract_allowed("outcome: nope", field="outcome", allowed=["pass"]) is None
