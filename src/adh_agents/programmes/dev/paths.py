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


def spec_pr_branch(initiative: str) -> str:
    """Spec head branch — ``chore/`` prefix passes guinea-pig policy-branch-name.

    Allowed prefixes on realworld-* policy checks: feature, fix, hotfix, release, chore.
    ``docs/spec-…`` fails CI and can leave merge state UNSTABLE even after APPROVE.
    """
    init = (initiative or "").strip().lower()
    return f"chore/spec-{init}"


def spec_pr_body_path(initiative: str, repo: str) -> str:
    init = (initiative or "").strip().upper()
    short = (repo or "").strip().rsplit("/", 1)[-1]
    return f"docs/specification/reports/Spec-PR-Body-{init}-{short}.md"


def spec_pr_push_paths(initiative: str, repo: str, *, map_spec: str = "") -> list[str]:
    """INIT-scoped Spec PR paths only — never rglob the whole docs tree.

    Prior INITs / chassis ADRs already on ``develop`` must not be re-pushed.
    """
    init = (initiative or "").strip().upper()
    short = (repo or "").strip().rsplit("/", 1)[-1]
    return [
        spec_slice_path(init, short, map_spec=map_spec),
        feasibility_report_path(init),
        technical_review_path(init),
        implementation_plan_path(init),
        spec_pr_body_path(init, short),
    ]
