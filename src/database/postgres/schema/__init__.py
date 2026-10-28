"""PostgreSQL schema package — import tables so Alembic sees them."""

from src.database.postgres.schema.buzz_schema import (
    BuzzIdentitySchema,
    BuzzMessageSchema,
    BuzzRoomSchema,
)

__all__ = [
    "BuzzIdentitySchema",
    "BuzzMessageSchema",
    "BuzzRoomSchema",
]
