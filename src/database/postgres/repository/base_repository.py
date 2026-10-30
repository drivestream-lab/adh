"""Base repository pattern implementation for PostgreSQL database access.

ORM → Pydantic mapping (Abhilekh / Airforge convention):
- Single-table rows: ``Model.model_validate(orm_row)`` with ``from_attributes=True`` on the DTO.
- Joins / enriched fields: ``base = Model.model_validate(primary_row)`` then
  ``base.model_copy(update={...})`` for columns from other tables or labels.
- Composite boundary DTOs: build from validated sub-models or typed ORM attributes on
  joined schemas (no per-field ``getattr`` helper modules).
"""

import uuid
from datetime import datetime, UTC
from typing import Any, Dict, Generic, List, Optional, Protocol, Type, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.di.qualified_types import PostgresSessionFactory
from src.logging import get_logger
from src.models.base_models import BaseCreateModel, BaseUpdateModel


class PostgresOrmRow(Protocol):
    """Minimal ORM row shape used by BasePostgresRepository."""

    id: UUID
    updated_at: Optional[datetime]


ModelType = TypeVar("ModelType", bound=PostgresOrmRow)
CreateModelType = TypeVar("CreateModelType", bound=BaseCreateModel)
UpdateModelType = TypeVar("UpdateModelType", bound=BaseUpdateModel)

logger = get_logger()


class BasePostgresRepository(Generic[ModelType]):
    """Base repository implementing common CRUD operations."""

    def __init__(
        self,
        model_class: Type[ModelType],
        session_factory: PostgresSessionFactory,
    ) -> None:
        self._model_class = model_class
        self._session_factory = session_factory
        logger.info("Created repository", repository=self.__class__.__name__)

    def _serialize_pydantic_for_db(self, obj: Any) -> Dict[str, Any]:
        """Convert Pydantic model to database-compatible dictionary."""
        obj_dict = obj.model_dump(exclude_unset=True, mode="json")
        for key, value in obj_dict.items():
            if isinstance(value, str) and value.endswith("Z"):
                try:
                    obj_dict[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    pass
        return obj_dict

    async def create(self, session: AsyncSession, obj_in: BaseCreateModel) -> ModelType:
        """Create a new record in the database."""
        clean_data = self._serialize_pydantic_for_db(obj_in)
        if "id" not in clean_data or clean_data["id"] is None:
            clean_data["id"] = uuid.uuid4()
        clean_data["created_at"] = datetime.now(UTC)
        clean_data["updated_at"] = datetime.now(UTC)
        db_obj = self._model_class(**clean_data)
        session.add(db_obj)
        await session.flush()
        await session.refresh(db_obj)
        return db_obj

    async def get(self, session: AsyncSession, record_id: Any) -> Optional[ModelType]:
        """Get a record by ID."""
        stmt = select(self._model_class).where(self._model_class.id == record_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self, session: AsyncSession, record_id: Any, obj_in: BaseUpdateModel
    ) -> Optional[ModelType]:
        """Update a record."""
        db_obj = await self.get(session, record_id)
        if db_obj is None:
            return None
        update_data = self._serialize_pydantic_for_db(obj_in)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        db_obj.updated_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(db_obj)
        return db_obj

    async def delete(self, session: AsyncSession, record_id: Any) -> bool:
        """Delete a record by ID."""
        db_obj = await self.get(session, record_id)
        if db_obj is None:
            return False
        await session.delete(db_obj)
        await session.flush()
        return True

    async def count(self, session: AsyncSession) -> int:
        """Count all records."""
        stmt = select(func.count()).select_from(self._model_class)
        result = await session.execute(stmt)
        return result.scalar_one()

    async def list_all(
        self, session: AsyncSession, skip: int = 0, limit: int = 100
    ) -> List[ModelType]:
        """List records with pagination."""
        stmt = select(self._model_class).offset(skip).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())
