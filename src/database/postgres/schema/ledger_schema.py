"""Ledger of PM briefs and engineering grades (ledger database)."""

from sqlalchemy import Column, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

from src.database.postgres.schema.base_postgres_schema import (
    MetaData,
    TimestampMixin,
    UUIDMixin,
)

ledger_metadata = MetaData()
LedgerBase = declarative_base(metadata=ledger_metadata)


class LedgerBaseModel(LedgerBase, UUIDMixin, TimestampMixin):
    __abstract__ = True


class LedgerEntrySchema(LedgerBaseModel):
    """Immutable-enough record of a Hermes artifact."""

    __tablename__ = "ledger_entries"

    kind = Column(String(32), nullable=False, comment="pm_brief | eng_grade")
    initiative = Column(String(128), nullable=False)
    rubric_id = Column(String(64), nullable=False)
    overall = Column(Float, nullable=True)
    recommend_merge = Column(String(16), nullable=True)
    body = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    buzz_message_id = Column(UUID(as_uuid=True), nullable=True)
