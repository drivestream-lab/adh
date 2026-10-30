"""OpenTelemetry infrastructure service for metrics and traces."""

from typing import Optional

from fastapi import FastAPI
from injector import inject
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)

from src.configs.app_settings import AppSettings
from src.configs.telemetry_settings import TelemetrySettings
from src.database.postgres.connection_manager import PostgresConnectionManager
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.telemetry_types import TracesSamplerType

logger = get_logger()


class TelemetryService(BaseInfraService):
    """Infra service that owns OpenTelemetry SDK lifecycle and instrumentation."""

    @inject
    def __init__(self, connection_manager: PostgresConnectionManager) -> None:
        super().__init__()
        self._connection_manager = connection_manager
        self._settings = TelemetrySettings.get_instance()
        self._app_settings = AppSettings.get_instance()
        self._tracer_provider: Optional[TracerProvider] = None
        self._meter_provider: Optional[MeterProvider] = None
        self._instrumented_app: Optional[FastAPI] = None
        self._initialized = False
        self._app_instrumented = False

    async def initialize(self) -> None:
        """Initialize OpenTelemetry providers and library instrumentors."""
        if self._initialized:
            return

        logger.info("Initializing TelemetryService")
        headers = self._parse_headers(self._settings.exporter_otlp_headers)

        span_exporter = OTLPSpanExporter(
            endpoint=self._build_signal_endpoint("traces"),
            headers=headers,
        )
        metric_exporter = OTLPMetricExporter(
            endpoint=self._build_signal_endpoint("metrics"),
            headers=headers,
        )

        resource = Resource.create(self._resource_attributes())
        tracer_provider = TracerProvider(
            resource=resource,
            sampler=self._build_sampler(),
        )
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        metric_reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        HTTPXClientInstrumentor().instrument()
        RedisInstrumentor().instrument()
        self._instrument_sqlalchemy_engine()

        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._initialized = True
        logger.info("TelemetryService initialized")

    async def close(self) -> None:
        """Shutdown telemetry providers and remove instrumentation."""
        if not self._initialized:
            return

        if self._app_instrumented and self._instrumented_app is not None:
            FastAPIInstrumentor().uninstrument_app(self._instrumented_app)
        SQLAlchemyInstrumentor().uninstrument()
        RedisInstrumentor().uninstrument()
        HTTPXClientInstrumentor().uninstrument()

        if self._meter_provider is not None:
            self._meter_provider.shutdown()
        if self._tracer_provider is not None:
            self._tracer_provider.shutdown()

        self._tracer_provider = None
        self._meter_provider = None
        self._instrumented_app = None
        self._app_instrumented = False
        self._initialized = False
        logger.info("TelemetryService closed")

    async def health_check(self) -> bool:
        """Check telemetry service health."""
        return self._initialized

    def instrument_app(self, app: FastAPI) -> None:
        """Instrument FastAPI app once."""
        if not self._initialized:
            raise RuntimeError("TelemetryService has not been initialized")
        if self._app_instrumented:
            return

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=self._tracer_provider,
            meter_provider=self._meter_provider,
        )
        # instrument_app patches build_middleware_stack; rebuild so OTEL ASGI
        # middleware (HTTP metrics + server spans) is active before traffic.
        app.middleware_stack = app.build_middleware_stack()
        self._instrumented_app = app
        self._app_instrumented = True
        logger.info("FastAPI app instrumentation enabled")

    def _instrument_sqlalchemy_engine(self) -> None:
        """Attach SQLAlchemy instrumentation to the initialized Postgres async engine."""
        engine = self._connection_manager.get_engine()
        if engine is None:
            raise RuntimeError(
                "Postgres engine must be initialized before TelemetryService "
                "(PostgresService before TelemetryService in _INFRA_SERVICE_TYPES)"
            )
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        logger.info("SQLAlchemy instrumentation enabled for Postgres engine")

    def _resource_attributes(self) -> dict[str, str]:
        attributes: dict[str, str] = {
            "service.name": self._settings.service_name,
        }
        if self._settings.service_version:
            attributes["service.version"] = self._settings.service_version
        if self._settings.deployment_environment:
            attributes["deployment.environment"] = self._settings.deployment_environment
        else:
            attributes["deployment.environment"] = self._app_settings.environment.value
        return attributes

    def _build_sampler(self) -> Sampler:
        sampler = self._settings.traces_sampler
        if sampler == TracesSamplerType.PARENTBASED_TRACEIDRATIO:
            return ParentBased(TraceIdRatioBased(self._settings.traces_sampler_arg))
        if sampler == TracesSamplerType.ALWAYS_OFF:
            return ALWAYS_OFF
        if sampler == TracesSamplerType.ALWAYS_ON:
            return ALWAYS_ON
        raise ValueError(f"Unsupported OTEL traces sampler: {sampler!r}")

    def _build_signal_endpoint(self, signal: str) -> str:
        endpoint = self._settings.exporter_otlp_endpoint.rstrip("/")
        if endpoint.endswith("/v1/traces") or endpoint.endswith("/v1/metrics"):
            return endpoint
        return f"{endpoint}/v1/{signal}"

    def _parse_headers(self, raw_headers: Optional[str]) -> dict[str, str]:
        if not raw_headers:
            return {}
        parsed: dict[str, str] = {}
        for pair in raw_headers.split(","):
            chunk = pair.strip()
            if not chunk:
                continue
            if "=" not in chunk:
                raise ValueError("OTEL_EXPORTER_OTLP_HEADERS must contain key=value pairs")
            key, value = chunk.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                raise ValueError("OTEL_EXPORTER_OTLP_HEADERS key cannot be empty")
            parsed[key] = value
        return parsed
