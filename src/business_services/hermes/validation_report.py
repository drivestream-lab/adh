"""Parse Validation-Report markdown into frozen finding rows for Hermes cards."""

from __future__ import annotations

import re
from typing import Any

# Live validate-requirements reports use titled sections, e.g.
# "## Critical (MUST FIX — …)" / "## Should Fix (reframe, …)".
_HEADING = re.compile(
    r"^##\s+(Critical|Should Fix|Verify|Gaps)\b.*$",
    re.I | re.M,
)
_VF = re.compile(r"\bVF-?(\d+)\b", re.I)


def validation_report_path(initiative: str) -> str:
    return f"prd/reports/Validation-Report-{initiative}.md"


def resolution_path(initiative: str) -> str:
    return f"prd/reports/Resolution-{initiative}.md"


def impact_map_path(initiative: str) -> str:
    return f"prd/reports/Impact-Map-{initiative}.md"


def parse_validation_findings(body: str) -> list[dict[str, Any]]:
    """Extract open findings with id, severity, and raw row text."""
    text = body or ""
    if not text.strip():
        return []
    findings: list[dict[str, Any]] = []
    matches = list(_HEADING.finditer(text))
    if not matches:
        # fallback: any VF ids in body as verify
        for match in _VF.finditer(text):
            fid = f"VF-{int(match.group(1)):02d}"
            findings.append(
                {
                    "id": fid,
                    "severity": "Verify",
                    "location": "",
                    "finding": f"Finding {fid}",
                    "recommendation": "",
                }
            )
        return _unique(findings)

    for index, match in enumerate(matches):
        severity = match.group(1)
        if severity.lower() == "gaps":
            severity = "Gaps"
        elif severity.lower().startswith("should"):
            severity = "Should Fix"
        elif severity.lower() == "critical":
            severity = "Critical"
        else:
            severity = "Verify"
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[start:end]
        for line in chunk.splitlines():
            vf = _VF.search(line)
            if not vf:
                continue
            fid = f"VF-{int(vf.group(1)):02d}"
            finding_text, location, recommendation = _row_fields(line)
            findings.append(
                {
                    "id": fid,
                    "severity": severity,
                    "location": location,
                    "finding": finding_text,
                    "recommendation": recommendation,
                }
            )
    return _unique(findings)


def _row_fields(line: str) -> tuple[str, str, str]:
    """Pull finding / location / recommendation from a markdown table row when present."""
    stripped = line.strip()
    if "|" not in stripped:
        return stripped, "", ""
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if not cells or not _VF.search(cells[0]):
        return stripped, "", ""
    # Critical / Should Fix / Verify / Gaps share: VF | Type | Location | Target | Check | Finding | …
    location = cells[2] if len(cells) > 2 else ""
    finding = cells[5] if len(cells) > 5 else stripped
    recommendation = cells[-1] if len(cells) > 6 else ""
    return finding or stripped, location, recommendation


def _unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        fid = str(row.get("id") or "")
        if not fid or fid in seen:
            continue
        seen.add(fid)
        out.append(row)
    return out


def open_critical(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in findings if str(row.get("severity") or "") == "Critical"]


def format_resolution_markdown(
    initiative: str,
    decisions: dict[str, str],
    findings: list[dict[str, Any]],
) -> str:
    by_id = {str(item.get("id") or ""): item for item in findings}
    lines = [
        f"# Resolution-{initiative}",
        "",
        "| CHG | VF | Decision | Finding |",
        "|-----|----|----------|---------|",
    ]
    chg = 1
    for fid, decision in sorted(decisions.items()):
        if fid.startswith("_"):
            continue
        if decision in {"explain"}:
            continue
        row = by_id.get(fid) or {}
        lines.append(
            f"| CHG-{chg:02d} | {fid} | {decision} | "
            f"{str(row.get('finding') or '')[:120].replace('|', '/')} |"
        )
        chg += 1
    lines.extend(["", "## Approved Fixes", ""])
    for fid, decision in sorted(decisions.items()):
        if decision in {"fix", "accept"}:
            lines.append(f"- {fid}: {decision}")
    lines.extend(["", "## Rejected Items", ""])
    for fid, decision in sorted(decisions.items()):
        if decision == "reject":
            lines.append(f"- {fid}")
    lines.extend(["", "## Deferred Items", ""])
    for fid, decision in sorted(decisions.items()):
        if decision == "defer":
            lines.append(f"- {fid}")
    return "\n".join(lines) + "\n"
