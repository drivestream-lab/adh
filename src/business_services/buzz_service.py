"""Buzz conversation plane: rooms, identities, messages, heartbeats."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Optional

from injector import inject
from sqlalchemy import select

from src.business_services.base_business_service import BaseBusinessService
from src.configs.buzz_settings import BuzzSettings
from src.database.postgres.repository.base_repository import BasePostgresRepository
from src.database.postgres.schema.buzz_schema import (
    BuzzIdentitySchema,
    BuzzMessageSchema,
    BuzzRoomMemberSchema,
    BuzzRoomSchema,
    BuzzTaskEventSchema,
    BuzzTaskSchema,
)
from src.exceptions.app_exceptions import NotFoundError, ValidationError
from src.infra_services.postgres_service import PostgresService
from src.infra_services.redis_service import RedisService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.logging import get_logger
from src.models.buzz_models import (
    EventType,
    HeartbeatIngest,
    IdentityCreate,
    IdentityKind,
    IdentityRead,
    IdentityRole,
    MessageCreate,
    MessageKind,
    MessagePage,
    MessageRead,
    RoomCreate,
    RoomKind,
    RoomMemberCreate,
    RoomMemberRead,
    RoomRead,
    RoomRosterEntry,
    StaleIdentity,
    TaskCreate,
    TaskEventCreate,
    TaskEventKind,
    TaskEventRead,
    TaskKind,
    TaskRead,
    TaskSource,
    TaskState,
)

logger = get_logger()

_SEED_IDENTITIES: tuple[IdentityCreate, ...] = (
    IdentityCreate(
        handle="nikd10x",
        display_name="Lead",
        kind=IdentityKind.HUMAN,
        role=IdentityRole.LEAD,
    ),
    IdentityCreate(
        handle="adh.orchestrator",
        display_name="Orchestrator",
        kind=IdentityKind.AGENT,
        role=IdentityRole.ORCHESTRATOR,
    ),
    IdentityCreate(
        handle="adh.coder.adh",
        display_name="Backend coder (adh)",
        kind=IdentityKind.AGENT,
        role=IdentityRole.CODER,
    ),
    IdentityCreate(
        handle="adh.coder.realworld-api",
        display_name="Backend coder (realworld-api)",
        kind=IdentityKind.AGENT,
        role=IdentityRole.CODER,
    ),
    IdentityCreate(
        handle="adh.reviewer",
        display_name="Reviewer",
        kind=IdentityKind.AGENT,
        role=IdentityRole.REVIEWER,
    ),
    IdentityCreate(
        handle="adh.pm",
        display_name="PM",
        kind=IdentityKind.AGENT,
        role=IdentityRole.PM,
    ),
    IdentityCreate(
        handle="adh.pe",
        display_name="PE",
        kind=IdentityKind.AGENT,
        role=IdentityRole.PE,
    ),
    IdentityCreate(
        handle="adh.read",
        display_name="Read",
        kind=IdentityKind.AGENT,
        role=IdentityRole.READ,
    ),
    IdentityCreate(
        handle="adh.kb",
        display_name="KB",
        kind=IdentityKind.AGENT,
        role=IdentityRole.KB,
    ),
    IdentityCreate(
        handle="adh.dev",
        display_name="Dev",
        kind=IdentityKind.AGENT,
        role=IdentityRole.DEV,
    ),
    IdentityCreate(
        handle="adh.system",
        display_name="Buzz system",
        kind=IdentityKind.AGENT,
        role=IdentityRole.SYSTEM,
    ),
)

_SEED_ROOMS: tuple[RoomCreate, ...] = (
    RoomCreate(slug="adh-ops", title="ADH ops", kind=RoomKind.OPS),
    # Wave 0a: no Buzz memory floors — OKF knowledge/ + DB remain SSOT.
)


class BuzzService(BaseBusinessService):
    """Human↔agent and agent↔agent conversation plane."""

    @inject
    def __init__(
        self,
        postgres_service: PostgresService,
        redis_service: RedisService,
        tenants: TenantRegistryService,
    ) -> None:
        super().__init__()
        self._postgres = postgres_service
        self._redis = redis_service
        self._tenants = tenants
        self._settings = BuzzSettings.get_instance()
        self._identity_repo: Optional[BasePostgresRepository[BuzzIdentitySchema]] = None
        self._room_repo: Optional[BasePostgresRepository[BuzzRoomSchema]] = None
        self._message_repo: Optional[BasePostgresRepository[BuzzMessageSchema]] = None
        self._member_repo: Optional[BasePostgresRepository[BuzzRoomMemberSchema]] = None
        self._task_repo: Optional[BasePostgresRepository[BuzzTaskSchema]] = None
        self._event_repo: Optional[BasePostgresRepository[BuzzTaskEventSchema]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None

    async def initialize(self) -> None:
        factory = self._postgres.get_session_factory()
        self._identity_repo = BasePostgresRepository(BuzzIdentitySchema, factory)
        self._room_repo = BasePostgresRepository(BuzzRoomSchema, factory)
        self._message_repo = BasePostgresRepository(BuzzMessageSchema, factory)
        self._member_repo = BasePostgresRepository(BuzzRoomMemberSchema, factory)
        self._task_repo = BasePostgresRepository(BuzzTaskSchema, factory)
        self._event_repo = BasePostgresRepository(BuzzTaskEventSchema, factory)
        if self._settings.seed_on_start:
            await self.seed_defaults()
        await super().initialize()
        if self._settings.publish_system_heartbeat:
            self._heartbeat_task = asyncio.create_task(self._system_heartbeat_loop())
            self.logger.info(
                "Buzz system heartbeat publisher started",
                interval_seconds=self._settings.heartbeat_seconds,
            )

    async def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        await super().close()

    def _identities(self) -> BasePostgresRepository[BuzzIdentitySchema]:
        if self._identity_repo is None:
            raise RuntimeError("BuzzService has not been initialized")
        return self._identity_repo

    def _rooms(self) -> BasePostgresRepository[BuzzRoomSchema]:
        if self._room_repo is None:
            raise RuntimeError("BuzzService has not been initialized")
        return self._room_repo

    def _messages(self) -> BasePostgresRepository[BuzzMessageSchema]:
        if self._message_repo is None:
            raise RuntimeError("BuzzService has not been initialized")
        return self._message_repo

    def _members(self) -> BasePostgresRepository[BuzzRoomMemberSchema]:
        if self._member_repo is None:
            raise RuntimeError("BuzzService has not been initialized")
        return self._member_repo

    def _tasks(self) -> BasePostgresRepository[BuzzTaskSchema]:
        if self._task_repo is None:
            raise RuntimeError("BuzzService has not been initialized")
        return self._task_repo

    def _events(self) -> BasePostgresRepository[BuzzTaskEventSchema]:
        if self._event_repo is None:
            raise RuntimeError("BuzzService has not been initialized")
        return self._event_repo

    def _to_message_read(
        self, message: BuzzMessageSchema, identity: BuzzIdentitySchema
    ) -> MessageRead:
        return MessageRead.model_validate(message).model_copy(
            update={
                "identity_handle": identity.handle,
                "identity_display_name": identity.display_name,
            }
        )

    async def seed_defaults(self) -> None:
        async with self._postgres.get_session() as session:
            for ident in _SEED_IDENTITIES:
                existing = await self._get_identity_by_handle(session, ident.handle)
                if existing is None:
                    await self._identities().create(session, ident)
                    self.logger.info("Seeded Buzz identity", handle=ident.handle)
            for room in (*_SEED_ROOMS, *_tenant_rooms(self._tenants)):
                existing = await self._get_room_by_slug(session, room.slug)
                if existing is None:
                    await self._rooms().create(session, room)
                    self.logger.info("Seeded Buzz room", slug=room.slug)

    async def list_identities(self) -> list[IdentityRead]:
        async with self._postgres.get_session() as session:
            rows = await self._identities().list_all(session, limit=500)
            return [IdentityRead.model_validate(row) for row in rows]

    async def create_identity(self, payload: IdentityCreate) -> IdentityRead:
        async with self._postgres.get_session() as session:
            existing = await self._get_identity_by_handle(session, payload.handle)
            if existing is not None:
                raise ValidationError(
                    f"Identity handle already exists: {payload.handle}",
                    field_errors={"handle": "duplicate"},
                )
            row = await self._identities().create(session, payload)
            return IdentityRead.model_validate(row)

    async def list_rooms(self) -> list[RoomRead]:
        """Helpful rooms only — exclude retired Buzz memory floors (Wave 0a)."""
        async with self._postgres.get_session() as session:
            rows = await self._rooms().list_all(session, limit=500)
            return [
                RoomRead.model_validate(row)
                for row in rows
                if str(getattr(row, "kind", "") or "").lower() != RoomKind.MEMORY.value
            ]

    async def create_room(self, payload: RoomCreate) -> RoomRead:
        async with self._postgres.get_session() as session:
            existing = await self._get_room_by_slug(session, payload.slug)
            if existing is not None:
                raise ValidationError(
                    f"Room slug already exists: {payload.slug}",
                    field_errors={"slug": "duplicate"},
                )
            row = await self._rooms().create(session, payload)
            return RoomRead.model_validate(row)

    async def get_room(self, slug: str) -> RoomRead:
        async with self._postgres.get_session() as session:
            row = await self._get_room_by_slug(session, slug)
            if row is None:
                raise NotFoundError("room", slug)
            return RoomRead.model_validate(row)

    async def list_messages(
        self,
        slug: str,
        *,
        limit: int = 20,
        before_id: Optional[str] = None,
    ) -> MessagePage:
        """Return a chronological page of the newest ``limit`` messages (or older than cursor)."""
        async with self._postgres.get_session() as session:
            room = await self._get_room_by_slug(session, slug)
            if room is None:
                raise NotFoundError("room", slug)
            before_created = None
            before_uuid = None
            if before_id:
                from uuid import UUID as _UUID

                try:
                    before_uuid = _UUID(str(before_id))
                except ValueError as exc:
                    raise ValidationError(
                        f"Invalid before_id: {before_id}",
                        field_errors={"before_id": "uuid"},
                    ) from exc
                cursor = await session.get(BuzzMessageSchema, before_uuid)
                if cursor is None or cursor.room_id != room.id:
                    raise NotFoundError("message", before_id)
                before_created = cursor.created_at

            filters = [BuzzMessageSchema.room_id == room.id]
            if before_created is not None and before_uuid is not None:
                filters.append(
                    (BuzzMessageSchema.created_at < before_created)
                    | (
                        (BuzzMessageSchema.created_at == before_created)
                        & (BuzzMessageSchema.id < before_uuid)
                    )
                )
            # Fetch limit+1 to detect has_more.
            stmt = (
                select(BuzzMessageSchema, BuzzIdentitySchema)
                .join(
                    BuzzIdentitySchema,
                    BuzzMessageSchema.identity_id == BuzzIdentitySchema.id,
                )
                .where(*filters)
                .order_by(BuzzMessageSchema.created_at.desc(), BuzzMessageSchema.id.desc())
                .limit(limit + 1)
            )
            result = await session.execute(stmt)
            rows = list(result.all())
            has_more = len(rows) > limit
            rows = rows[:limit]
            rows.reverse()
            items = [self._to_message_read(message, identity) for message, identity in rows]
            return MessagePage(items=items, has_more=has_more)

    async def post_message(self, slug: str, payload: MessageCreate) -> MessageRead:
        async with self._postgres.get_session() as session:
            posted = await self._post_message(session, slug, payload)
        await self._publish_room(slug, posted)
        return posted

    async def stream_room(self, slug: str) -> AsyncGenerator[str, None]:
        """Yield JSON MessageRead payloads for one room (Redis Pub/Sub)."""
        await self.get_room(slug)
        pubsub = self._redis.pubsub()
        channel = self._room_channel(slug)
        try:
            await pubsub.subscribe(channel)
            self.logger.info("Buzz SSE subscribed", room=slug, channel=channel)
            last_ping = asyncio.get_event_loop().time()
            yield json.dumps({"type": "subscribed", "slug": slug})
            while True:
                raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if raw is not None and raw.get("type") == "message":
                    data = raw.get("data")
                    if isinstance(data, (bytes, bytearray)):
                        data = data.decode("utf-8")
                    if isinstance(data, str) and data:
                        yield data
                now = asyncio.get_event_loop().time()
                if now - last_ping >= 25:
                    yield json.dumps({"type": "ping"})
                    last_ping = now
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                self.logger.exception("Failed to unsubscribe Buzz pubsub", room=slug)
            try:
                await pubsub.aclose()
            except Exception:
                self.logger.exception("Failed to close Buzz pubsub", room=slug)

    async def ingest_heartbeat(self, payload: HeartbeatIngest) -> MessageRead:
        create = MessageCreate(
            identity_handle=payload.identity_handle,
            body=payload.body,
            kind=MessageKind.HEARTBEAT,
            event_type=payload.event_type,
            payload=payload.payload,
        )
        async with self._postgres.get_session() as session:
            posted = await self._post_message(session, payload.room_slug, create)
        await self._redis.set(
            f"heartbeat:{posted.identity_handle}",
            posted.created_at.isoformat() if posted.created_at else "1",
            ttl=self._settings.heartbeat_seconds * 2,
        )
        await self._publish_room(payload.room_slug, posted)
        return posted

    async def list_stale_identities(self) -> list[StaleIdentity]:
        cutoff_seconds = self._settings.heartbeat_seconds
        now = datetime.now(UTC)
        async with self._postgres.get_session() as session:
            identities = await self._identities().list_all(session, limit=500)
            stale: list[StaleIdentity] = []
            for ident in identities:
                ident_read = IdentityRead.model_validate(ident)
                if ident_read.role == IdentityRole.LEAD or ident_read.kind == IdentityKind.HUMAN:
                    continue
                stmt = (
                    select(BuzzMessageSchema.created_at)
                    .where(
                        BuzzMessageSchema.identity_id == ident_read.id,
                        BuzzMessageSchema.kind == MessageKind.HEARTBEAT.value,
                    )
                    .order_by(BuzzMessageSchema.created_at.desc())
                    .limit(1)
                )
                last = (await session.execute(stmt)).scalar_one_or_none()
                if last is None:
                    stale.append(
                        StaleIdentity.model_validate(ident_read).model_copy(
                            update={"last_heartbeat_at": None, "stale_seconds": None}
                        )
                    )
                    continue
                age = (now - last).total_seconds()
                if age > cutoff_seconds:
                    stale.append(
                        StaleIdentity.model_validate(ident_read).model_copy(
                            update={"last_heartbeat_at": last, "stale_seconds": age}
                        )
                    )
            return stale

    async def ensure_member(self, payload: RoomMemberCreate) -> RoomMemberRead:
        async with self._postgres.get_session() as session:
            room = await self._get_room_by_slug(session, payload.room_slug)
            if room is None:
                raise NotFoundError("room", payload.room_slug)
            identity = await self._get_identity_by_handle(session, payload.identity_handle)
            if identity is None:
                raise NotFoundError("identity", payload.identity_handle)
            stmt = select(BuzzRoomMemberSchema).where(
                BuzzRoomMemberSchema.room_id == room.id,
                BuzzRoomMemberSchema.identity_id == identity.id,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                existing = BuzzRoomMemberSchema(
                    room_id=room.id,
                    identity_id=identity.id,
                    member_role=payload.member_role or "participant",
                )
                session.add(existing)
                await session.flush()
                await session.refresh(existing)
            return RoomMemberRead(
                id=existing.id,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
                room_id=room.id,
                identity_id=identity.id,
                identity_handle=str(identity.handle),
                identity_display_name=str(identity.display_name),
                member_role=str(existing.member_role or "participant"),
            )

    async def list_members(self, room_slug: str) -> list[RoomMemberRead]:
        async with self._postgres.get_session() as session:
            room = await self._get_room_by_slug(session, room_slug)
            if room is None:
                raise NotFoundError("room", room_slug)
            stmt = (
                select(BuzzRoomMemberSchema, BuzzIdentitySchema)
                .join(
                    BuzzIdentitySchema,
                    BuzzRoomMemberSchema.identity_id == BuzzIdentitySchema.id,
                )
                .where(BuzzRoomMemberSchema.room_id == room.id)
            )
            rows = (await session.execute(stmt)).all()
            return [
                RoomMemberRead(
                    id=member.id,
                    created_at=member.created_at,
                    updated_at=member.updated_at,
                    room_id=room.id,
                    identity_id=identity.id,
                    identity_handle=str(identity.handle),
                    identity_display_name=str(identity.display_name),
                    member_role=str(member.member_role or "participant"),
                )
                for member, identity in rows
            ]

    async def create_task(self, payload: TaskCreate) -> TaskRead:
        """Create durable task + task room; hub announcement is caller's job."""
        task_room_slug = f"task-{payload.task_id}".lower()
        async with self._postgres.get_session() as session:
            existing = await self._get_task(session, payload.tenant_slug, payload.task_id)
            if existing is not None:
                return self._to_task_read(existing)
            if payload.source_ref:
                stmt = select(BuzzTaskSchema).where(
                    BuzzTaskSchema.tenant_slug == payload.tenant_slug,
                    BuzzTaskSchema.source_ref == payload.source_ref,
                )
                by_ref = (await session.execute(stmt)).scalar_one_or_none()
                if by_ref is not None:
                    return self._to_task_read(by_ref)
            room = await self._get_room_by_slug(session, task_room_slug)
            if room is None:
                room = BuzzRoomSchema(
                    slug=task_room_slug,
                    title=payload.title[:256],
                    kind=RoomKind.TASK.value,
                )
                session.add(room)
                await session.flush()
            row = BuzzTaskSchema(
                tenant_slug=payload.tenant_slug,
                kind=payload.kind.value,
                task_id=payload.task_id.strip().upper(),
                title=payload.title,
                state=payload.state.value,
                source=payload.source.value,
                source_ref=payload.source_ref,
                hub_room_slug=payload.hub_room_slug,
                task_room_slug=task_room_slug,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return self._to_task_read(row)

    async def get_task(self, tenant_slug: str, task_id: str) -> TaskRead:
        async with self._postgres.get_session() as session:
            row = await self._get_task(session, tenant_slug, task_id)
            if row is None:
                raise NotFoundError("task", task_id)
            return self._to_task_read(row)

    async def get_task_by_room_slug(self, room_slug: str) -> Optional[TaskRead]:
        """Resolve durable task from `#task-…` room slug."""
        async with self._postgres.get_session() as session:
            stmt = select(BuzzTaskSchema).where(
                BuzzTaskSchema.task_room_slug == room_slug.strip().lower()
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return self._to_task_read(row)

    async def list_tasks(
        self,
        tenant_slug: str,
        *,
        include_archived: bool = False,
    ) -> list[TaskRead]:
        async with self._postgres.get_session() as session:
            stmt = select(BuzzTaskSchema).where(BuzzTaskSchema.tenant_slug == tenant_slug)
            if not include_archived:
                stmt = stmt.where(BuzzTaskSchema.archived_at.is_(None))
            stmt = stmt.order_by(BuzzTaskSchema.created_at.desc())
            rows = (await session.execute(stmt)).scalars().all()
            return [self._to_task_read(row) for row in rows]

    async def list_active_task_rooms(self, tenant_slug: str) -> list[str]:
        tasks = await self.list_tasks(tenant_slug, include_archived=False)
        return [t.task_room_slug for t in tasks]

    async def list_active_engg_rooms(self, tenant_slug: str) -> list[str]:
        """Engg floors for non-archived tasks (`engg-{task_id}`) that exist as rooms."""
        from src.adh_agents.runtime.room_resolve import engg_room_slug_for

        out: list[str] = []
        for task in await self.list_tasks(tenant_slug, include_archived=False):
            slug = engg_room_slug_for(task.task_id)
            try:
                await self.get_room(slug)
            except Exception:
                continue
            out.append(slug)
        return out

    async def ensure_engg_room(self, *, task_id: str, title: str | None = None) -> RoomRead:
        """Idempotent `#engg-{TASK_ID}` programme floor for Dev engg-think."""
        from src.adh_agents.runtime.room_resolve import engg_room_slug_for

        slug = engg_room_slug_for(task_id)
        init = task_id.strip().upper()
        try:
            return await self.get_room(slug)
        except NotFoundError:
            pass
        try:
            return await self.create_room(
                RoomCreate(
                    slug=slug,
                    title=(title or f"Engg {init}")[:256],
                    kind=RoomKind.ENGG,
                )
            )
        except ValidationError:
            return await self.get_room(slug)

    async def set_task_state(
        self,
        tenant_slug: str,
        task_id: str,
        state: TaskState,
        *,
        role_id: str = "",
    ) -> TaskRead:
        """Advance durable delivery-harness task state (kind stays; state moves).

        ADH orchestrates from ``buzz_tasks`` — not from replaying Buzz chat.
        """
        if state == TaskState.ARCHIVED:
            raise ValidationError(
                "Use archive_task for ARCHIVED (sets archived_at + trajectory).",
                field_errors={"state": "use_archive_task"},
            )
        async with self._postgres.get_session() as session:
            row = await self._get_task(session, tenant_slug, task_id)
            if row is None:
                raise NotFoundError("task", task_id)
            if row.archived_at is not None:
                raise ValidationError(
                    f"Task {task_id} is archived",
                    field_errors={"task_id": "archived"},
                )
            prev = str(row.state)
            if prev == state.value:
                return self._to_task_read(row)
            row.state = state.value  # type: ignore[assignment]
            await session.flush()
            await session.refresh(row)
            self.logger.info(
                "Buzz task state updated",
                tenant=tenant_slug,
                task_id=task_id,
                kind=str(row.kind),
                from_state=prev,
                to_state=state.value,
                role=role_id or None,
            )
            event = await self._append_event_unlocked(
                session,
                TaskEventCreate(
                    tenant_slug=tenant_slug,
                    task_id=task_id,
                    kind=TaskEventKind.STATE,
                    role_id=role_id or "",
                    purpose="state",
                    token=state.value,
                    payload={"from": prev, "to": state.value},
                ),
            )
            await self._mirror_traj_to_hub(session, row, event)
            return self._to_task_read(row)

    async def archive_task(self, tenant_slug: str, task_id: str, *, archived_by: str) -> TaskRead:
        async with self._postgres.get_session() as session:
            row = await self._get_task(session, tenant_slug, task_id)
            if row is None:
                raise NotFoundError("task", task_id)
            row.archived_at = datetime.now(UTC)  # type: ignore[assignment]
            row.archived_by = archived_by  # type: ignore[assignment]
            row.state = TaskState.ARCHIVED.value  # type: ignore[assignment]
            await session.flush()
            await session.refresh(row)
            event = await self._append_event_unlocked(
                session,
                TaskEventCreate(
                    tenant_slug=tenant_slug,
                    task_id=task_id,
                    kind=TaskEventKind.ARCHIVE,
                    role_id=archived_by,
                    purpose="archive",
                    token="archive task",
                ),
            )
            await self._mirror_traj_to_hub(session, row, event)
            return self._to_task_read(row)

    async def delete_task(self, tenant_slug: str, task_id: str, *, deleted_by: str) -> None:
        """Hard-delete task room messages + room + task row (Lead-explicit)."""
        async with self._postgres.get_session() as session:
            row = await self._get_task(session, tenant_slug, task_id)
            if row is None:
                raise NotFoundError("task", task_id)
            room = await self._get_room_by_slug(session, str(row.task_room_slug))
            if room is not None:
                msgs = await session.execute(
                    select(BuzzMessageSchema).where(BuzzMessageSchema.room_id == room.id)
                )
                for msg in msgs.scalars().all():
                    await session.delete(msg)
                members = await session.execute(
                    select(BuzzRoomMemberSchema).where(BuzzRoomMemberSchema.room_id == room.id)
                )
                for member in members.scalars().all():
                    await session.delete(member)
                await session.delete(room)
            events = await session.execute(
                select(BuzzTaskEventSchema).where(
                    BuzzTaskEventSchema.tenant_slug == tenant_slug,
                    BuzzTaskEventSchema.task_id == row.task_id,
                )
            )
            for event in events.scalars().all():
                await session.delete(event)
            await session.delete(row)
            await session.flush()
            self.logger.info(
                "Buzz task deleted",
                tenant=tenant_slug,
                task_id=task_id,
                by=deleted_by,
            )

    async def append_task_event(self, payload: TaskEventCreate) -> TaskEventRead:
        async with self._postgres.get_session() as session:
            event = await self._append_event_unlocked(session, payload)
            task = await self._get_task(session, payload.tenant_slug, payload.task_id)
            if task is not None:
                await self._mirror_traj_to_hub(session, task, event)
            return event

    async def list_task_events(self, tenant_slug: str, task_id: str) -> list[TaskEventRead]:
        async with self._postgres.get_session() as session:
            stmt = (
                select(BuzzTaskEventSchema)
                .where(
                    BuzzTaskEventSchema.tenant_slug == tenant_slug,
                    BuzzTaskEventSchema.task_id == task_id.strip().upper(),
                )
                .order_by(BuzzTaskEventSchema.seq.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [self._to_event_read(row) for row in rows]

    async def list_room_roster(self, slug: str) -> list[RoomRosterEntry]:
        """Members + Redis presence (tenant-scoped heartbeat) for listening strip."""
        members = await self.list_members(slug)
        tenant_slug = await self._tenant_slug_for_room(slug)
        presence_map: dict[str, str] = {}
        if tenant_slug:
            try:
                keys = await self._redis.keys(f"adh:presence:{tenant_slug}:*")
                prefix = f"adh:presence:{tenant_slug}:"
                for key in keys:
                    raw_key = (
                        key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else str(key)
                    )
                    role = raw_key[len(prefix) :] if raw_key.startswith(prefix) else ""
                    if not role:
                        continue
                    state = await self._redis.get(raw_key)
                    if state is None:
                        continue
                    if isinstance(state, (bytes, bytearray)):
                        state = state.decode("utf-8")
                    presence_map[role] = str(state)
            except Exception:
                self.logger.exception("presence scan failed", room=slug, tenant=tenant_slug)
        return [
            RoomRosterEntry(
                identity_handle=m.identity_handle,
                identity_display_name=m.identity_display_name,
                member_role=m.member_role,
                presence=presence_map.get(m.identity_handle),
            )
            for m in members
        ]

    async def _tenant_slug_for_room(self, slug: str) -> Optional[str]:
        hit = self._tenants.by_ops_room(slug)
        if hit is not None:
            return hit.slug
        task = await self.get_task_by_room_slug(slug)
        if task is not None:
            return task.tenant_slug
        return None

    async def _mirror_traj_to_hub(
        self, session, task: BuzzTaskSchema, event: TaskEventRead
    ) -> None:
        """Buzz-light pointer on tenant ops — fail-open; never raise to callers."""
        hub = str(task.hub_room_slug or "").strip()
        if not hub:
            return
        # Avoid mirror loops if a future writer tags skip.
        if (event.payload or {}).get("skip_hub_mirror"):
            return
        purpose = (event.purpose or "").strip()
        token = (event.token or "").strip()
        extra = f" · `{purpose}`" if purpose else ""
        if token:
            extra = f"{extra} · `{token}`" if extra else f" · `{token}`"
        task_room = str(task.task_room_slug)
        task_state = str(task.state)
        body = (
            f"traj `{event.kind.value}` `{event.task_id}` → `#{task_room}` "
            f"({task_state}){extra}"
        )
        handle = (event.role_id or "").strip() or "adh.system"
        try:
            await self._post_message(
                session,
                hub,
                MessageCreate(
                    identity_handle=handle,
                    body=body,
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": "traj_mirror",
                        "traj_mirror": True,
                        "task_id": event.task_id,
                        "task_room": task_room,
                        "event_kind": event.kind.value,
                        "seq": event.seq,
                        "task_state": task_state,
                    },
                ),
            )
        except Exception:
            self.logger.exception(
                "traj hub mirror failed",
                hub=hub,
                task_id=event.task_id,
                kind=event.kind.value,
            )

    async def _append_event_unlocked(self, session, payload: TaskEventCreate) -> TaskEventRead:
        task_id = payload.task_id.strip().upper()
        seq_stmt = select(BuzzTaskEventSchema.seq).where(
            BuzzTaskEventSchema.tenant_slug == payload.tenant_slug,
            BuzzTaskEventSchema.task_id == task_id,
        )
        seqs = (await session.execute(seq_stmt)).scalars().all()
        next_seq = (max(seqs) + 1) if seqs else 1
        row = BuzzTaskEventSchema(
            tenant_slug=payload.tenant_slug,
            task_id=task_id,
            seq=next_seq,
            kind=payload.kind.value,
            role_id=payload.role_id or "",
            purpose=payload.purpose or "",
            token=payload.token or "",
            evidence_ref=payload.evidence_ref or "",
            payload=payload.payload,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return self._to_event_read(row)

    def _to_task_read(self, row: BuzzTaskSchema) -> TaskRead:
        return TaskRead.model_validate(
            {
                "id": row.id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "tenant_slug": str(row.tenant_slug),
                "kind": TaskKind(str(row.kind)),
                "task_id": str(row.task_id),
                "title": str(row.title),
                "state": TaskState(str(row.state)),
                "source": TaskSource(str(row.source)),
                "source_ref": str(row.source_ref) if row.source_ref is not None else None,
                "hub_room_slug": str(row.hub_room_slug),
                "task_room_slug": str(row.task_room_slug),
                "archived_at": row.archived_at,
                "archived_by": str(row.archived_by) if row.archived_by is not None else None,
            }
        )

    def _to_event_read(self, row: BuzzTaskEventSchema) -> TaskEventRead:
        return TaskEventRead.model_validate(
            {
                "id": row.id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "tenant_slug": str(row.tenant_slug),
                "task_id": str(row.task_id),
                "seq": int(row.seq),  # type: ignore[arg-type]
                "kind": TaskEventKind(str(row.kind)),
                "role_id": str(row.role_id or ""),
                "purpose": str(row.purpose or ""),
                "token": str(row.token or ""),
                "evidence_ref": str(row.evidence_ref or ""),
                "payload": row.payload,
            }
        )

    async def _get_task(self, session, tenant_slug: str, task_id: str) -> Optional[BuzzTaskSchema]:
        stmt = select(BuzzTaskSchema).where(
            BuzzTaskSchema.tenant_slug == tenant_slug,
            BuzzTaskSchema.task_id == task_id.strip().upper(),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _post_message(self, session, slug: str, payload: MessageCreate) -> MessageRead:
        room = await self._get_room_by_slug(session, slug)
        if room is None:
            raise NotFoundError("room", slug)
        identity = await self._get_identity_by_handle(session, payload.identity_handle)
        if identity is None:
            raise NotFoundError("identity", payload.identity_handle)
        dump = payload.model_dump(exclude={"identity_handle"})
        dump["room_id"] = room.id
        dump["identity_id"] = identity.id
        row = BuzzMessageSchema(
            **{
                k: (v.value if hasattr(v, "value") else v)
                for k, v in dump.items()
                if k in {"body", "kind", "event_type", "payload", "room_id", "identity_id"}
            }
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        self.logger.info(
            "Buzz message posted",
            room=slug,
            handle=identity.handle,
            kind=row.kind,
            message_id=str(row.id),
        )
        return self._to_message_read(row, identity)

    def _room_channel(self, slug: str) -> str:
        return f"buzz:room:{slug}"

    async def _publish_room(self, slug: str, posted: MessageRead) -> None:
        try:
            await self._redis.publish(
                self._room_channel(slug),
                posted.model_dump_json(),
            )
        except Exception:
            self.logger.exception("Buzz room publish failed", room=slug)

    async def _get_identity_by_handle(self, session, handle: str) -> Optional[BuzzIdentitySchema]:
        stmt = select(BuzzIdentitySchema).where(BuzzIdentitySchema.handle == handle)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _get_room_by_slug(self, session, slug: str) -> Optional[BuzzRoomSchema]:
        stmt = select(BuzzRoomSchema).where(BuzzRoomSchema.slug == slug)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _system_heartbeat_loop(self) -> None:
        interval = max(5, self._settings.heartbeat_seconds)
        while True:
            try:
                await self.ingest_heartbeat(
                    HeartbeatIngest(
                        identity_handle="adh.system",
                        room_slug="adh-ops",
                        body="alive",
                        event_type=EventType.PROGRESS,
                        payload={"interval_seconds": interval},
                    )
                )
            except Exception:
                self.logger.exception("System heartbeat ingest failed")
            await asyncio.sleep(interval)


def _tenant_rooms(tenants: TenantRegistryService) -> tuple[RoomCreate, ...]:
    """Seed ops rooms only — memory rooms retired (Wave 0a)."""
    rooms: list[RoomCreate] = []
    seen: set[str] = {"adh-ops"}
    for tenant in tenants.active():
        if tenant.ops_room not in seen:
            rooms.append(
                RoomCreate(
                    slug=tenant.ops_room,
                    title=f"{tenant.slug} ops",
                    kind=RoomKind.OPS,
                )
            )
            seen.add(tenant.ops_room)
    return tuple(rooms)
