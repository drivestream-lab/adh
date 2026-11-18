"""Coder wave-pickup — board ticket map + ready-set (not brainless wave_ids[0])."""

from __future__ import annotations

from src.adh_agents.programmes.coder.board_tickets import match_issue_urls
from src.adh_agents.programmes.coder.ready_set import ready_wave_ids_for_repo
from src.adh_agents.programmes.dev.workmanifest_board import parse_board_manifest

_PLAN = """
## 9. WorkManifest

```yaml
apiVersion: prayog/v1
kind: WorkManifest
initiative: INIT-X-1
target:
  org: example
  project: Board
defaults:
  labels: [INIT-X-1]
epic:
  id: EPIC
  repo: api
  title: epic title
  body: epic body
work:
  - id: W0
    repo: api
    title: wave0 title
    depends_on: []
    tasks:
      - id: TASK-W0-01
        implements: [REQ-01]
        depends_on: []
  - id: W1
    repo: api
    title: wave1 title
    depends_on: [W0]
    tasks:
      - id: TASK-W1-01
        implements: [REQ-02]
        depends_on: []
  - id: W2
    repo: api
    title: wave2 title
    depends_on: []
    tasks:
      - id: TASK-W2-01
        implements: [REQ-03]
        depends_on: []
```
"""


def test_match_issue_urls_orders_epic_then_waves() -> None:
    manifest = parse_board_manifest(_PLAN)
    issues = [
        {"title": "wave1 title", "html_url": "https://github.com/o/r/issues/9", "state": "open"},
        {"title": "epic title", "html_url": "https://github.com/o/r/issues/7", "state": "open"},
        {"title": "wave0 title", "html_url": "https://github.com/o/r/issues/8", "state": "open"},
        {"title": "wave2 title", "html_url": "https://github.com/o/r/issues/10", "state": "open"},
    ]
    snap = match_issue_urls(manifest, issues)
    assert snap.epic_url.endswith("/issues/7")
    assert snap.issue_urls == (
        "https://github.com/o/r/issues/7",
        "https://github.com/o/r/issues/8",
        "https://github.com/o/r/issues/9",
        "https://github.com/o/r/issues/10",
    )
    assert snap.wave_urls["W0"].endswith("/issues/8")
    assert "MISSING" not in "\n".join(snap.evidence_lines)


def test_ready_waves_for_repo_excludes_blocked_parents() -> None:
    manifest = parse_board_manifest(_PLAN)
    assert ready_wave_ids_for_repo(manifest, "api") == ("W0", "W2")
    assert ready_wave_ids_for_repo(manifest, "api", done_wave_ids=frozenset({"W0"})) == (
        "W1",
        "W2",
    )
