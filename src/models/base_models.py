"""Base Pydantic models for Parichay."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class BaseTimestampModel(BaseModel):
    """Base model with timestamp fields for PostgreSQL entities."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )

    created_at: Optional[datetime] = Field(
        default=None, description="UTC timestamp when record was created"
    )
    updated_at: Optional[datetime] = Field(
        default=None, description="UTC timestamp when record was last updated"
    )


class BaseUUIDModel(BaseModel):
    """Base model with UUID primary key."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )

    id: Optional[UUID] = Field(default=None, description="Unique identifier for the record")


class BasePostgresModel(BaseUUIDModel, BaseTimestampModel):
    """Base model for PostgreSQL entities with UUID and timestamps."""

    pass


class BaseCreateModel(BaseModel):
    """Base model for create operations."""

    model_config = ConfigDict(
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )


class BaseUpdateModel(BaseModel):
    """Base model for update operations with optional fields."""

    model_config = ConfigDict(
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )
