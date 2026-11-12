"""Resolve TenantContext from hub, task, or engg room slug."""

from __future__ import annotations

from typing import Optional

from src.business_services.buzz_service import BuzzService
from src.exceptions.app_exceptions import NotFoundError
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.tenant_models import TenantContext


def task_room_slug_for(task_id: str) -> str:
    """Canonical `#task-{TASK_ID}` slug (matches buzz_service.create_task)."""
    return f"task-{task_id.strip()}".lower()


def engg_room_slug_for(task_id: str) -> str:
    """Canonical `#engg-{TASK_ID}` Dev collaboration floor (E1)."""
    return f"engg-{task_id.strip()}".lower()


def task_id_from_engg_room(room: str) -> str | None:
    slug = (room or "").strip().lower()
    if not slug.startswith("engg-"):
        return None
    return slug[len("engg-") :].upper() or None


def is_hub_room(room: str, tenant: TenantContext) -> bool:
    return (room or "").strip() == tenant.ops_room


def is_task_room(room: str) -> bool:
    return (room or "").startswith("task-")


def is_engg_room(room: str) -> bool:
    return (room or "").startswith("engg-")


async def collaboration_room(
    buzz: BuzzService,
    tenant: TenantContext,
    *,
    initiative: str | None,
    fallback: str | None = None,
) -> str:
    """Where army talk for a bound INIT goes — task room, never hub when task exists.

    Hub is intake/announce only. Once ``buzz_tasks`` has the INIT, batons + coaches
    + CollabPosts use ``task_room_slug``. Dev engg-think uses ``engg_collaboration_room``.
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


async def engg_collaboration_room(
    buzz: BuzzService,
    tenant: TenantContext,
    *,
    initiative: str | None,
    fallback: str | None = None,
) -> str:
    """Dev programme floor — `#engg-<id>`, never hub / task home."""
    init = (initiative or "").strip().upper()
    if not init or init.startswith("__"):
        return fallback or tenant.ops_room
    _ = buzz  # reserved for future task-linked lookups
    return engg_room_slug_for(init)


async def resolve_tenant_for_room(
    tenants: TenantRegistryService,
    buzz: BuzzService,
    room: str,
) -> Optional[TenantContext]:
    """Hub ops, `#task-…`, or `#engg-…` → tenant."""
    hit = tenants.by_ops_room(room)
    if hit is not None:
        return hit
    task = await buzz.get_task_by_room_slug(room)
    if task is not None:
        return tenants.by_slug(task.tenant_slug)
    engg_id = task_id_from_engg_room(room)
    if engg_id:
        for tenant in tenants.active():
            try:
                await buzz.get_task(tenant.slug, engg_id)
                return tenant
            except NotFoundError:
                continue
            except Exception:
                continue
        # Merged-PR guinea pig may open engg before task row — match init prefix.
        for tenant in tenants.active():
            prefix = (tenant.init_prefix or "").strip().upper().rstrip("-")
            if prefix and engg_id.startswith(prefix):
                return tenant
    return None


async def listen_rooms_for_tenants(
    buzz: BuzzService,
    tenants: TenantRegistryService,
    *,
    include_task: bool = True,
    include_engg: bool = True,
) -> list[str]:
    """Hub (+ optional task / engg) floors for every active tenant.

    Role scoping (Team OS): ``#engg-*`` is the Dev YAML floor — PM/PE/KB must
    not SSE-consume Lead there (otherwise product authoring steals Dev replies).
    """
    rooms: list[str] = []
    seen: set[str] = set()
    for tenant in tenants.active():
        slugs: list[str] = [tenant.ops_room]
        if include_task:
            slugs.extend(await buzz.list_active_task_rooms(tenant.slug))
        if include_engg:
            slugs.extend(await buzz.list_active_engg_rooms(tenant.slug))
        for slug in slugs:
            if slug and slug not in seen:
                seen.add(slug)
                rooms.append(slug)
    return rooms


async def listen_rooms_for_role(
    buzz: BuzzService,
    tenants: TenantRegistryService,
    role_id: str,
) -> list[str]:
    """Role-scoped Buzz listen set — engg floor is Dev-only."""
    role = (role_id or "").strip()
    if role == "adh.dev":
        # Hub (hire / announce) + `#engg-*` Dev lane. Not product `#task-*`.
        return await listen_rooms_for_tenants(buzz, tenants, include_task=False, include_engg=True)
    # PM / PE / KB / Read: hub + task homes. Never engg Lead traffic.
    return await listen_rooms_for_tenants(buzz, tenants, include_task=True, include_engg=False)
