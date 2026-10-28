"""Buzz conversation plane: rooms, identities, messages, heartbeats."""

import asyncio
import json
from collections.abc import AsyncIterator
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
    BuzzRoomSchema,
)
from src.exceptions.app_exceptions import NotFoundError, ValidationError
from src.infra_services.postgres_service import PostgresService
from src.infra_services.redis_service import RedisService
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
    MessageRead,
    RoomCreate,
    RoomKind,
    RoomRead,
    StaleIdentity,
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
        handle="adh.system",
        display_name="Buzz system",
        kind=IdentityKind.AGENT,
        role=IdentityRole.SYSTEM,
    ),
)

_SEED_ROOMS: tuple[RoomCreate, ...] = (
    RoomCreate(slug="adh-ops", title="ADH ops", kind=RoomKind.OPS),
    RoomCreate(slug="adh-memory", title="Lead memory", kind=RoomKind.MEMORY),
)


class BuzzService(BaseBusinessService):
    """Human↔agent and agent↔agent conversation plane."""

    @inject
    def __init__(
        self,
        postgres_service: PostgresService,
        redis_service: RedisService,
    ) -> None:
        super().__init__()
        self._postgres = postgres_service
        self._redis = redis_service
        self._settings = BuzzSettings.get_instance()
        self._identity_repo: Optional[BasePostgresRepository[BuzzIdentitySchema]] = None
        self._room_repo: Optional[BasePostgresRepository[BuzzRoomSchema]] = None
        self._message_repo: Optional[BasePostgresRepository[BuzzMessageSchema]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None

    async def initialize(self) -> None:
        factory = self._postgres.get_session_factory()
        self._identity_repo = BasePostgresRepository(BuzzIdentitySchema, factory)
        self._room_repo = BasePostgresRepository(BuzzRoomSchema, factory)
        self._message_repo = BasePostgresRepository(BuzzMessageSchema, factory)
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
            for room in _SEED_ROOMS:
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
        async with self._postgres.get_session() as session:
            rows = await self._rooms().list_all(session, limit=500)
            return [RoomRead.model_validate(row) for row in rows]

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

    async def list_messages(self, slug: str, limit: int = 200) -> list[MessageRead]:
        async with self._postgres.get_session() as session:
            room = await self._get_room_by_slug(session, slug)
            if room is None:
                raise NotFoundError("room", slug)
            stmt = (
                select(BuzzMessageSchema, BuzzIdentitySchema)
                .join(
                    BuzzIdentitySchema,
                    BuzzMessageSchema.identity_id == BuzzIdentitySchema.id,
                )
                .where(BuzzMessageSchema.room_id == room.id)
                .order_by(BuzzMessageSchema.created_at.asc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [self._to_message_read(message, identity) for message, identity in result.all()]

    async def post_message(self, slug: str, payload: MessageCreate) -> MessageRead:
        async with self._postgres.get_session() as session:
            posted = await self._post_message(session, slug, payload)
        await self._publish_room(slug, posted)
        return posted

    async def stream_room(self, slug: str) -> AsyncIterator[str]:
        """Yield JSON MessageRead payloads for one room (Redis Pub/Sub)."""
        await self.get_room(slug)
        pubsub = self._redis.pubsub()
        channel = self._room_channel(slug)
        await pubsub.subscribe(channel)
        self.logger.info("Buzz SSE subscribed", room=slug, channel=channel)
        last_ping = asyncio.get_event_loop().time()
        try:
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
