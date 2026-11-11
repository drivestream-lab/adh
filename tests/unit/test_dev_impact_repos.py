"""Impact-Map affected-repo parsing for Dev YAML walker."""

from __future__ import annotations

from src.adh_agents.programmes.dev.impact_repos import parse_affected_repos


_SAMPLE = """
## 2. Affected repositories

| Service | Repo | Team | Scope summary |
|---------|------|------|---------------|
| realworld-api | drivestream-lab/realworld-api | @x | api |
| realworld-web | drivestream-lab/realworld-web | @y | web |
| realworld-local | drivestream-lab/realworld-local | @z | local |

## 3. Deferred repositories
"""


def test_parse_affected_repos_order() -> None:
    rows = parse_affected_repos(_SAMPLE)
    assert [r.repo for r in rows] == ["realworld-api", "realworld-web", "realworld-local"]


def test_pass_chain_has_no_deps_acceptance() -> None:
    from src.adh_agents.programmes.dev.programme import _PASS_CHAIN

    assert "deps-acceptance" not in _PASS_CHAIN
    assert _PASS_CHAIN[0] == "spec-draft"
    assert _PASS_CHAIN[-1] == "board-tickets-action"
    assert "spec-pr-action" in _PASS_CHAIN
    assert "spec-merge" in _PASS_CHAIN
