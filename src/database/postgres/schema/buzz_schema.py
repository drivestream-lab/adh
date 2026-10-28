"""PostgreSQL tables for the Buzz conversation plane."""

from sqlalchemy import Column, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.database.postgres.schema.base_postgres_schema import PostgresBaseModel


class BuzzIdentitySchema(PostgresBaseModel):
    """One human or agent handle, e.g. nikd10x or adh.coder.adh."""

    __tablename__ = "buzz_identities"

    handle = Column(String(128), unique=True, nullable=False, comment="Stable handle")
    display_name = Column(String(256), nullable=False)
    kind = Column(String(32), nullable=False, comment="human | agent")
    role = Column(
        String(64),
        nullable=False,
        comment="lead | coder | reviewer | pm | orchestrator | system",
    )


class BuzzRoomSchema(PostgresBaseModel):
    """A named room humans and agents share."""

    __tablename__ = "buzz_rooms"

    slug = Column(String(128), unique=True, nullable=False)
    title = Column(String(256), nullable=False)
    kind = Column(String(32), nullable=False, comment="ops | memory | wave | general")


class BuzzMessageSchema(PostgresBaseModel):
    """A message, heartbeat, or event in a room."""

    __tablename__ = "buzz_messages"
    __table_args__ = (
        Index("ix_buzz_messages_room_created", "room_id", "created_at"),
        Index("ix_buzz_messages_identity_kind", "identity_id", "kind"),
    )

    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey("buzz_rooms.id"),
        nullable=False,
    )
    identity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("buzz_identities.id"),
        nullable=False,
    )
    body = Column(Text, nullable=False)
    kind = Column(String(32), nullable=False, comment="message | heartbeat | event")
    event_type = Column(
        String(32),
        nullable=True,
        comment="start | progress | stall | done",
    )
    payload = Column(JSONB, nullable=True)
