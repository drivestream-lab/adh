"""Forge action allowlists per role — default deny."""

from __future__ import annotations

from typing import FrozenSet

# Role → allowed forge action names (empty = deny all)
_DEFAULT_ACL: dict[str, FrozenSet[str]] = {
    "adh.pm": frozenset({"open_draft_pr", "prd_merge", "comment_pr"}),
    "adh.pe": frozenset({"ready_for_review", "approve_attestation", "apply_labels", "comment_pr"}),
    "adh.dev": frozenset({"open_draft_pr", "push_branch", "comment_pr"}),
    "adh.qa": frozenset({"comment_pr", "set_check"}),
    "adh.read": frozenset(),
    "adh.taskgraph": frozenset(),
    # KB may open + land enrich PRs under knowledge/** (Contents push via workspace).
    "adh.kb": frozenset({"open_draft_pr", "prd_merge", "land_pull_request"}),
}


def forge_allowed(role_id: str, action: str) -> bool:
    """Default deny: action allowed only if listed for role."""
    allowed = _DEFAULT_ACL.get(role_id, frozenset())
    return (action or "").strip() in allowed


def allowlist_for(role_id: str) -> FrozenSet[str]:
    return _DEFAULT_ACL.get(role_id, frozenset())
