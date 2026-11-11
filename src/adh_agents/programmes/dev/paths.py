"""Artefact path helpers for the Dev YAML development lane."""

from __future__ import annotations


def feasibility_report_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"docs/specification/reports/Initiative-Feasibility-Report-{init}.md"


def technical_review_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"docs/specification/reports/Technical-Review-{init}.md"


def implementation_plan_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"docs/specification/plans/Implementation-Plan-{init}.md"


def workmanifest_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"docs/specification/plans/WorkManifest-{init}.yaml"


def spec_slice_path(initiative: str, repo: str) -> str:
    """Per-repo product spec slice (spec-draft output)."""
    init = (initiative or "").strip().upper()
    short = (repo or "").strip().rsplit("/", 1)[-1]
    suffix = short.replace("realworld-", "") if short.startswith("realworld-") else short
    return f"docs/specification/product/{init}-{suffix}.md"
