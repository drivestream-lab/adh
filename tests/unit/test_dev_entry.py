"""Dev programme entry fail-closed checks."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.adh_agents.programmes.dev.entry import resolve_dev_entry


def _tenant() -> MagicMock:
    t = MagicMock()
    t.slug = "realworld"
    t.meta_root = "/tmp/meta"
    return t


def test_entry_requires_initiative() -> None:
    ws = MagicMock()
    entry, stall = resolve_dev_entry(ws, _tenant(), initiative="")
    assert entry is None
    assert stall and "initiative" in stall.lower()


def test_entry_requires_prd_pr_url() -> None:
    ws = MagicMock()
    ws.read_local.return_value = "# map"
    entry, stall = resolve_dev_entry(ws, _tenant(), initiative="INIT-007")
    assert entry is None
    assert stall and ("PR URL" in stall or "PE → Dev" in stall)


def test_entry_requires_impact_map() -> None:
    ws = MagicMock()
    ws.read_local.return_value = ""
    entry, stall = resolve_dev_entry(
        ws, _tenant(), initiative="INIT-007", prd_pr_url="https://github.com/o/r/pull/1"
    )
    assert entry is None
    assert stall and "Impact-Map" in stall


def test_entry_ok() -> None:
    ws = MagicMock()

    def _read(_t, path: str) -> str:
        if "Impact-Map" in path or path.endswith(".md"):
            return "# body"
        return ""

    ws.read_local.side_effect = _read
    entry, stall = resolve_dev_entry(
        ws,
        _tenant(),
        initiative="init-007",
        prd_pr_url="https://github.com/o/r/pull/1",
    )
    assert stall is None
    assert entry is not None
    assert entry.initiative == "INIT-007"
    assert "Impact-Map-INIT-007" in entry.impact_map
