"""Pydantic models for health API responses."""

from enum import Enum

from pydantic import BaseModel, Field


class HealthLivenessType(str, Enum):
    """Minimal liveness response."""

    OK = "ok"


class HealthStatusType(str, Enum):
    """Dependency or aggregate health status."""

    UP = "up"
    DOWN = "down"


class HealthSimpleResponse(BaseModel):
    """Minimal health payload for load balancers."""

    status: HealthLivenessType = Field(
        default=HealthLivenessType.OK, description="Liveness indicator"
    )


class ServiceHealthDetailModel(BaseModel):
    """One dependency (Postgres, Redis, …) in detailed health."""

    status: HealthStatusType = Field(..., description="up or down")
    details: dict[str, bool] = Field(default_factory=dict, description="Diagnostic flags")


class HealthDetailedResponse(BaseModel):
    """Detailed health when ?detailed=true."""

    status: HealthStatusType = Field(..., description="Aggregate status: up or down")
    services: dict[str, ServiceHealthDetailModel] = Field(
        default_factory=dict,
        description="Per-dependency status",
    )
