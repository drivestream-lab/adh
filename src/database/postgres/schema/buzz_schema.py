"""PostgreSQL tables for the Buzz conversation plane."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    """A named room humans and agents share (hub ops or per-task)."""

    __tablename__ = "buzz_rooms"

    slug = Column(String(128), unique=True, nullable=False)
    title = Column(String(256), nullable=False)
    kind = Column(String(32), nullable=False, comment="ops | task | memory | wave | general")


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


class BuzzRoomMemberSchema(PostgresBaseModel):
    """Membership of an identity in a room (hub hire or task assignment)."""

    __tablename__ = "buzz_room_members"
    __table_args__ = (
        UniqueConstraint("room_id", "identity_id", name="uq_buzz_room_member"),
        Index("ix_buzz_room_members_room", "room_id"),
    )

    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey("buzz_rooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("buzz_identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_role = Column(String(64), nullable=False, default="participant")


class BuzzTaskSchema(PostgresBaseModel):
    """Canonical durable task (init / bug / enhancement) — not Redis SSOT."""

    __tablename__ = "buzz_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_slug", "task_id", name="uq_buzz_task_tenant_id"),
        Index("ix_buzz_tasks_tenant_state", "tenant_slug", "state"),
    )

    tenant_slug = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False)
    task_id = Column(String(128), nullable=False)
    title = Column(String(512), nullable=False)
    state = Column(String(32), nullable=False, default="bound")
    source = Column(String(32), nullable=False, default="buzz")
    source_ref = Column(String(512), nullable=True)
    hub_room_slug = Column(String(128), nullable=False)
    task_room_slug = Column(String(128), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(String(128), nullable=True)


class BuzzTaskEventSchema(PostgresBaseModel):
    """Append-only trajectory / monitor events for a task (god + army hops)."""

    __tablename__ = "buzz_task_events"
    __table_args__ = (
        UniqueConstraint("tenant_slug", "task_id", "seq", name="uq_buzz_task_event_seq"),
        Index("ix_buzz_task_events_task", "tenant_slug", "task_id", "seq"),
    )

    tenant_slug = Column(String(64), nullable=False)
    task_id = Column(String(128), nullable=False)
    seq = Column(Integer, nullable=False)
    kind = Column(String(32), nullable=False)
    role_id = Column(String(128), nullable=False, default="")
    purpose = Column(String(128), nullable=False, default="")
    token = Column(String(256), nullable=False, default="")
    evidence_ref = Column(String(1024), nullable=False, default="")
    payload = Column(JSONB, nullable=True)
