"""OpenTelemetry settings for application metrics and traces."""

from typing import ClassVar, Optional

from pydantic import Field

from src.configs.base_settings import BaseSettings
from src.models.telemetry_types import ExporterOtlpProtocolType, TracesSamplerType


class TelemetrySettings(BaseSettings):
    """Settings for OpenTelemetry SDK/exporters."""

    PREFIX: ClassVar[str] = "OTEL"

    service_name: str = Field(
        default="adh",
        description="OpenTelemetry service.name resource attribute",
    )
    service_version: Optional[str] = Field(
        default=None,
        description="OpenTelemetry service.version resource attribute",
    )
    deployment_environment: Optional[str] = Field(
        default=None,
        description="OpenTelemetry deployment.environment resource attribute",
    )
    exporter_otlp_endpoint: str = Field(
        default="http://localhost:4318",
        description="OTLP HTTP endpoint (Alloy receiver)",
    )
    exporter_otlp_protocol: ExporterOtlpProtocolType = Field(
        default=ExporterOtlpProtocolType.HTTP_PROTOBUF,
        description="OTLP protocol",
    )
    exporter_otlp_headers: Optional[str] = Field(
        default=None,
        description="Comma-separated OTLP headers in key=value format",
    )
    traces_sampler: TracesSamplerType = Field(
        default=TracesSamplerType.PARENTBASED_TRACEIDRATIO,
        description="OpenTelemetry traces sampler",
    )
    traces_sampler_arg: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Sampling ratio for parentbased_traceidratio sampler",
    )
