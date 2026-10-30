"""Postgres stores for the hermes and ledger databases."""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
from urllib.parse import quote_plus
from uuid import UUID, uuid4
from datetime import UTC, datetime

from injector import inject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.configs.hermes_settings import HermesSettings
from src.database.postgres.schema.hermes_schema import (
    HermesKnowledgeSchema,
    HermesMemorySchema,
    hermes_metadata,
)
from src.database.postgres.schema.ledger_schema import LedgerEntrySchema, ledger_metadata
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.hermes_models import HermesArtifactRead

logger = get_logger()


class HermesStoreService(BaseInfraService):
    """Owns hermes + ledger engines. Buzz stays on the primary PostgresService."""

    @inject
    def __init__(self) -> None:
        self._settings = HermesSettings.get_instance()
        self._hermes_engine: Optional[AsyncEngine] = None
        self._ledger_engine: Optional[AsyncEngine] = None
        self._hermes_sessions: Optional[async_sessionmaker[AsyncSession]] = None
        self._ledger_sessions: Optional[async_sessionmaker[AsyncSession]] = None
        self._initialized = False

    def _url(self, db: str) -> str:
        password = quote_plus(self._settings.pg_password.get_secret_value())
        return (
            f"postgresql+asyncpg://{self._settings.pg_user}:{password}"
            f"@{self._settings.pg_host}:{self._settings.pg_port}/{db}"
        )

    async def initialize(self) -> None:
        if self._initialized:
            return
        logger.info(
            "Initializing Hermes stores",
            hermes_db=self._settings.pg_db,
            ledger_db=self._settings.ledger_db,
        )
        self._hermes_engine = create_async_engine(
            self._url(self._settings.pg_db), pool_pre_ping=True
        )
        self._ledger_engine = create_async_engine(
            self._url(self._settings.ledger_db), pool_pre_ping=True
        )
        self._hermes_sessions = async_sessionmaker(
            self._hermes_engine, expire_on_commit=False, autoflush=False
        )
        self._ledger_sessions = async_sessionmaker(
            self._ledger_engine, expire_on_commit=False, autoflush=False
        )
        async with self._hermes_engine.begin() as conn:
            await conn.run_sync(hermes_metadata.create_all)
        async with self._ledger_engine.begin() as conn:
            await conn.run_sync(ledger_metadata.create_all)
        self._initialized = True
        logger.info("Hermes stores initialized")

    async def close(self) -> None:
        if self._hermes_engine is not None:
            await self._hermes_engine.dispose()
            self._hermes_engine = None
        if self._ledger_engine is not None:
            await self._ledger_engine.dispose()
            self._ledger_engine = None
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized and self._hermes_engine is not None

    @asynccontextmanager
    async def _session(
        self, factory: Optional[async_sessionmaker[AsyncSession]]
    ) -> AsyncGenerator[AsyncSession, None]:
        if factory is None:
            raise RuntimeError("Hermes store has not been initialized")
        session = factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def has_kind(self, kind: str, initiative: str) -> bool:
        async with self._session(self._ledger_sessions) as session:
            stmt = (
                select(LedgerEntrySchema.id)
                .where(
                    LedgerEntrySchema.kind == kind,
                    LedgerEntrySchema.initiative == initiative,
                )
                .limit(1)
            )
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def save_knowledge(
        self,
        *,
        lane: str,
        dimension: str,
        key: str,
        body: str,
        payload: dict[str, Any],
        source_buzz_id: Optional[UUID],
    ) -> None:
        async with self._session(self._hermes_sessions) as session:
            existing = (
                await session.execute(
                    select(HermesKnowledgeSchema).where(HermesKnowledgeSchema.key == key)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                HermesKnowledgeSchema(
                    id=uuid4(),
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    lane=lane,
                    dimension=dimension,
                    key=key,
                    body=body,
                    payload=payload,
                    source_buzz_id=source_buzz_id,
                )
            )

    async def save_memory(
        self,
        *,
        kind: str,
        initiative: str,
        body: str,
        payload: dict[str, Any],
        source_buzz_id: Optional[UUID],
    ) -> None:
        async with self._session(self._hermes_sessions) as session:
            session.add(
                HermesMemorySchema(
                    id=uuid4(),
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    kind=kind,
                    initiative=initiative,
                    body=body,
                    payload=payload,
                    source_buzz_id=source_buzz_id,
                )
            )

    async def save_ledger(
        self,
        *,
        kind: str,
        initiative: str,
        rubric_id: str,
        overall: Optional[float],
        recommend_merge: Optional[str],
        body: str,
        payload: dict[str, Any],
        buzz_message_id: Optional[UUID],
    ) -> HermesArtifactRead:
        async with self._session(self._ledger_sessions) as session:
            row = LedgerEntrySchema(
                id=uuid4(),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                kind=kind,
                initiative=initiative,
                rubric_id=rubric_id,
                overall=overall,
                recommend_merge=recommend_merge,
                body=body,
                payload=payload,
                buzz_message_id=buzz_message_id,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return HermesArtifactRead.model_validate(row)

    async def list_ledger(self, limit: int = 50) -> list[HermesArtifactRead]:
        async with self._session(self._ledger_sessions) as session:
            stmt = (
                select(LedgerEntrySchema).order_by(LedgerEntrySchema.created_at.desc()).limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [HermesArtifactRead.model_validate(row) for row in rows]
