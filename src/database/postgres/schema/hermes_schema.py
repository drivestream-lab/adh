"""Hermes knowledge / memory tables (hermes database)."""

from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

from src.database.postgres.schema.base_postgres_schema import (
    MetaData,
    TimestampMixin,
    UUIDMixin,
)

hermes_metadata = MetaData()
HermesBase = declarative_base(metadata=hermes_metadata)


class HermesBaseModel(HermesBase, UUIDMixin, TimestampMixin):
    __abstract__ = True


class HermesKnowledgeSchema(HermesBaseModel):
    """Reusable finding keyed by lane + dimension."""

    __tablename__ = "hermes_knowledge"

    lane = Column(String(32), nullable=False, comment="pm | eng")
    dimension = Column(String(64), nullable=False)
    key = Column(String(256), nullable=False, unique=True)
    body = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=True)
    source_buzz_id = Column(UUID(as_uuid=True), nullable=True)


class HermesMemorySchema(HermesBaseModel):
    """Overlay notes Hermes may propose; humans bake in."""

    __tablename__ = "hermes_memory"

    kind = Column(String(32), nullable=False, comment="brief | grade | proposal")
    initiative = Column(String(128), nullable=False)
    body = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=True)
    source_buzz_id = Column(UUID(as_uuid=True), nullable=True)
