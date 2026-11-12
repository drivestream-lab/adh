"""Artefact path helpers for the Dev YAML development lane (tenant-agnostic)."""

from __future__ import annotations


def feasibility_report_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"docs/specification/reports/Initiative-Feasibility-Report-{init}.md"


def technical_review_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"docs/specification/reports/Technical-Review-{init}.md"


def implementation_plan_path(initiative: str) -> str:
    """Canonical path — SSOT ``artifact-write-contract`` ``{reports_dir}/Implementation-Plan-…``."""
    init = (initiative or "").strip().upper()
    return f"docs/specification/reports/Implementation-Plan-{init}.md"


def workmanifest_path(initiative: str) -> str:
    """WorkManifest walk-time carrier is §9 YAML inside the Implementation-Plan (not a sibling file)."""
    return implementation_plan_path(initiative)


def spec_slice_path(initiative: str, repo: str, *, map_spec: str = "") -> str:
    """Per-repo product spec slice.

    Prefer Impact-Map ``Spec to create`` when it is a relative path or filename;
    otherwise ``docs/specification/product/{INIT}-{repo}.md``.
    """
    init = (initiative or "").strip().upper()
    short = (repo or "").strip().rsplit("/", 1)[-1]
    hinted = (map_spec or "").strip().strip("`")
    if hinted:
        if "/" in hinted or hinted.endswith(".md"):
            if hinted.startswith("docs/") or hinted.startswith("prd/"):
                return hinted
            return f"docs/specification/product/{hinted}"
        return f"docs/specification/product/{hinted}"
    return f"docs/specification/product/{init}-{short}.md"
