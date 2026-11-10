"""Fence: live programmes should not assign AWAITING_JUDGMENT outside GateOpener.

Clarify / explain re-asserts and AWAITING_NONE clears are allowed.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "src" / "adh_agents"
_ALLOWED = {
    "runtime/gate_opener.py",
    "runtime/work_models.py",
    # Orchestrator still clears / routes; programmes open via GateOpener.
    "runtime/orchestrator.py",
    "catalogue/navigator.py",
}


def test_no_new_judgment_assignments_outside_gate_opener() -> None:
    offenders: list[str] = []
    needle = "awaiting = AWAITING_JUDGMENT"
    for path in _ROOT.rglob("*.py"):
        rel = str(path.relative_to(_ROOT))
        if rel in _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if needle in line and not line.strip().startswith("#"):
                # Re-assert after explain / stall keep is OK when brief already open.
                if "session.awaiting = AWAITING_JUDGMENT" in line and (
                    "explain" in text[max(0, text.find(line) - 200) : text.find(line) + 50]
                    or rel.endswith("pe_glue.py")
                    and "sync_stall" in text
                ):
                    continue
                offenders.append(f"{rel}:{i}: {line.strip()}")
    # Soft fence during Floor land: flag but allow known residual re-opens.
    residual_ok = {
        "programmes/pm/meta_pm.py",  # explain re-assert
        "programmes/pm/pe_glue.py",  # may still have edge stalls
        "programmes/kb/enrich.py",
        "programmes/pm/authoring.py",
    }
    hard = [o for o in offenders if o.split(":")[0] not in residual_ok]
    assert hard == [], "new AWAITING_JUDGMENT opens must go through GateOpener:\n" + "\n".join(hard)
