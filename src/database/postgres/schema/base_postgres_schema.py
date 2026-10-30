"""Base schema definitions for PostgreSQL tables."""

import uuid
from datetime import datetime, UTC

from sqlalchemy import Column, MetaData, TIMESTAMP, UUID
from sqlalchemy.orm import declarative_base

postgres_metadata = MetaData()
BasePostgres = declarative_base(metadata=postgres_metadata)


class TimestampMixin:
    """Mixin for timestamp columns with UTC timezone awareness."""

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Timestamp (UTC) when record was created",
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        comment="Timestamp (UTC) when record was last updated",
    )


class UUIDMixin:
    """Mixin for UUID primary key."""

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique identifier for the record",
    )


class PostgresBaseModel(BasePostgres, UUIDMixin, TimestampMixin):
    """Base model for PostgreSQL tables with UUID, timestamps."""

    __abstract__ = True

    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id})>"
