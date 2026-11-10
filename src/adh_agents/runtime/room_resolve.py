"""Resolve TenantContext from hub or task room slug."""

from __future__ import annotations

from typing import Optional

from src.business_services.buzz_service import BuzzService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.tenant_models import TenantContext


def task_room_slug_for(task_id: str) -> str:
    """Canonical `#task-{TASK_ID}` slug (matches buzz_service.create_task)."""
    return f"task-{task_id.strip()}".lower()


def is_hub_room(room: str, tenant: TenantContext) -> bool:
    return (room or "").strip() == tenant.ops_room


def is_task_room(room: str) -> bool:
    return (room or "").startswith("task-")


async def collaboration_room(
    buzz: BuzzService,
    tenant: TenantContext,
    *,
    initiative: str | None,
    fallback: str | None = None,
) -> str:
    """Where army talk for a bound INIT goes — task room, never hub when task exists.

    Hub is intake/announce only. Once ``buzz_tasks`` has the INIT, batons + coaches
    + CollabPosts use ``task_room_slug``.
    """
    init = (initiative or "").strip().upper()
    default = fallback or tenant.ops_room
    if not init or init.startswith("__"):
        return default
    try:
        task = await buzz.get_task(tenant.slug, init)
        return task.task_room_slug
    except Exception:
        # Deterministic slug even if row missing (race); prefer over hub for bound work.
        return task_room_slug_for(init)


async def resolve_tenant_for_room(
    tenants: TenantRegistryService,
    buzz: BuzzService,
    room: str,
) -> Optional[TenantContext]:
    """Hub ops room or `#task-…` durable task room → tenant."""
    hit = tenants.by_ops_room(room)
    if hit is not None:
        return hit
    task = await buzz.get_task_by_room_slug(room)
    if task is None:
        return None
    return tenants.by_slug(task.tenant_slug)


async def listen_rooms_for_tenants(
    buzz: BuzzService,
    tenants: TenantRegistryService,
) -> list[str]:
    """Hub + all non-archived task rooms for every active tenant."""
    rooms: list[str] = []
    seen: set[str] = set()
    for tenant in tenants.active():
        for slug in (tenant.ops_room, *await buzz.list_active_task_rooms(tenant.slug)):
            if slug and slug not in seen:
                seen.add(slug)
                rooms.append(slug)
    return rooms
