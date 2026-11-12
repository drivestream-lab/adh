"""WorkManifest §9 → board seed projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.adh_agents.programmes.dev.workmanifest_board import (
    extract_workmanifest_yaml,
    parse_board_manifest,
)
from src.exceptions.app_exceptions import ValidationError

_PLAN = Path(
    "/Users/kumardeepak/Workspace/next-gen/realworld-api/docs/specification/reports/"
    "Implementation-Plan-INIT-REALWORLD-001.md"
)


def test_extract_from_live_plan() -> None:
    if not _PLAN.is_file():
        pytest.skip("live RealWorld plan not checked out")
    raw = extract_workmanifest_yaml(_PLAN.read_text(encoding="utf-8"))
    assert "kind: WorkManifest" in raw
    assert "INIT-REALWORLD-001" in raw


def test_parse_live_plan_waves() -> None:
    if not _PLAN.is_file():
        pytest.skip("live RealWorld plan not checked out")
    m = parse_board_manifest(_PLAN.read_text(encoding="utf-8"))
    assert m.initiative == "INIT-REALWORLD-001"
    assert m.project_name == "RealWorld"
    assert m.epic_repo == "realworld-api"
    assert [w.wave_id for w in m.waves] == ["W0", "W1", "W2"]
    assert m.labels == ("INIT-REALWORLD-001",)


def test_parse_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        parse_board_manifest("# no manifest\n")


def test_parse_minimal_fence() -> None:
    text = """
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
    title: wave0
    tasks:
      - id: TASK-W0-01
        implements: [REQ-01]
        depends_on: []
```
"""
    m = parse_board_manifest(text)
    assert m.epic_title == "epic title"
    assert m.waves[0].wave_id == "W0"
    assert "TASK-W0-01" in m.waves[0].body
