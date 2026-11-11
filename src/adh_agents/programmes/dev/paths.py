"""Meta artefact paths for the Dev engg-think lane."""

from __future__ import annotations


def engg_deps_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"prd/reports/Engg-Deps-{init}.md"


def feasibility_report_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"prd/reports/Initiative-Feasibility-Report-{init}.md"


def technical_review_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"prd/reports/Technical-Review-{init}.md"


def implementation_plan_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"prd/reports/Implementation-Plan-{init}.md"


def verification_plan_path(initiative: str) -> str:
    init = (initiative or "").strip().upper()
    return f"prd/reports/Verification-Plan-{init}.md"
