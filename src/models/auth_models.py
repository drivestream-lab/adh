"""Auth context models for JWT middleware."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuthContext(BaseModel):
    """Authenticated request context set by JWT middleware."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID = Field(description="Authenticated user identifier")
    tenant_id: Optional[UUID] = Field(default=None, description="Tenant scope when present")
    role: str = Field(description="Role code from JWT")
    owner_id: Optional[UUID] = Field(default=None, description="Owner identifier when applicable")
