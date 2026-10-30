"""OpenTelemetry domain enums for Parichay."""

from enum import Enum


class TracesSamplerType(str, Enum):
    """Supported OpenTelemetry head samplers for Parichay."""

    PARENTBASED_TRACEIDRATIO = "parentbased_traceidratio"
    ALWAYS_ON = "always_on"
    ALWAYS_OFF = "always_off"


class ExporterOtlpProtocolType(str, Enum):
    """Supported OTLP exporter protocols for Parichay."""

    HTTP_PROTOBUF = "http/protobuf"
