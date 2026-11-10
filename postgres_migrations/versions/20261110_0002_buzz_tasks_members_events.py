"""Buzz tasks, room members, and task trajectory events.

Revision ID: 20261110_0002
Revises: 20261028_0001
Create Date: 2026-11-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261110_0002"
down_revision: Union[str, Sequence[str], None] = "20261028_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "buzz_room_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("member_role", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["buzz_identities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["buzz_rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "identity_id", name="uq_buzz_room_member"),
    )
    op.create_index("ix_buzz_room_members_room", "buzz_room_members", ["room_id"])

    op.create_table(
        "buzz_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("tenant_slug", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("hub_room_slug", sa.String(length=128), nullable=False),
        sa.Column("task_room_slug", sa.String(length=128), nullable=False),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("archived_by", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_slug", "task_id", name="uq_buzz_task_tenant_id"),
    )
    # Partial unique: only enforce source_ref when present (Postgres).
    op.create_index(
        "uq_buzz_task_source_ref",
        "buzz_tasks",
        ["tenant_slug", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_buzz_tasks_tenant_state",
        "buzz_tasks",
        ["tenant_slug", "state"],
    )

    op.create_table(
        "buzz_task_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("tenant_slug", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("role_id", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=128), nullable=False),
        sa.Column("token", sa.String(length=256), nullable=False),
        sa.Column("evidence_ref", sa.String(length=1024), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_slug", "task_id", "seq", name="uq_buzz_task_event_seq"),
    )
    op.create_index(
        "ix_buzz_task_events_task",
        "buzz_task_events",
        ["tenant_slug", "task_id", "seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_buzz_task_events_task", table_name="buzz_task_events")
    op.drop_table("buzz_task_events")
    op.drop_index("ix_buzz_tasks_tenant_state", table_name="buzz_tasks")
    op.drop_index("uq_buzz_task_source_ref", table_name="buzz_tasks")
    op.drop_table("buzz_tasks")
    op.drop_index("ix_buzz_room_members_room", table_name="buzz_room_members")
    op.drop_table("buzz_room_members")
