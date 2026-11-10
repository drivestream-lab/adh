"""PostgreSQL schema package — import tables so Alembic sees them."""

from src.database.postgres.schema.buzz_schema import (
    BuzzIdentitySchema,
    BuzzMessageSchema,
    BuzzRoomMemberSchema,
    BuzzRoomSchema,
    BuzzTaskEventSchema,
    BuzzTaskSchema,
)

__all__ = [
    "BuzzIdentitySchema",
    "BuzzMessageSchema",
    "BuzzRoomMemberSchema",
    "BuzzRoomSchema",
    "BuzzTaskEventSchema",
    "BuzzTaskSchema",
]
