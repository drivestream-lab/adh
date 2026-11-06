"""Catch-up policy — do not replay when role already has active work."""

from __future__ import annotations

from src.adh_agents.runtime.work_store import AgentWorkStore
from src.logging import get_logger

logger = get_logger()


async def should_skip_catch_up(store: AgentWorkStore, tenant: str, role_id: str) -> bool:
    """True when active work sessions exist for this role — avoid duplicate starts."""
    if await store.has_active(tenant, role_id):
        logger.info(
            "catch_up skipped — active agent work sessions present",
            tenant=tenant,
            role=role_id,
        )
        return True
    return False
