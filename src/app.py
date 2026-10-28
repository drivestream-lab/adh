"""FastAPI application setup for adh."""

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.health.health_router import router as health_router
from src.api.internal import internal_router
from src.api.v1 import api_router
from src.common.auth.config import AuthConfig
from src.common.auth.middleware import AuthMiddleware
from src.configs.app_settings import AppSettings
from src.configs.jwt_settings import JWTSettings
from src.di.dependency_container import (
    close_all_services,
    configure_container,
    initialize_all_services,
)
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.telemetry_service import TelemetryService
from src.logging import LoggingContext, get_logger, setup_logging
from src.utils.correlation_id import CorrelationIdMiddleware

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_correlation_id = str(uuid.uuid4())
    with LoggingContext(startup_correlation_id):
        logger.info("Starting adh application")
        container = configure_container()
        app.state.container = container
        try:
            await initialize_all_services()
            container.get(TelemetryService).instrument_app(app)
            logger.info("All services initialized successfully")
        except Exception:
            logger.exception("Service initialization failed")
            raise
        logger.complete()
    yield
    with LoggingContext(startup_correlation_id):
        logger.info("Shutting down adh application")
        try:
            await close_all_services()
        except Exception as e:
            logger.error("Error during shutdown", error=str(e))


def create_app() -> FastAPI:
    settings = AppSettings.get_instance()
    setup_logging(settings)

    app = FastAPI(
        title="Adh API",
        description="ADH orchestrator, Buzz, and Hermes",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    jwt_settings = JWTSettings.get_instance()
    auth_config = AuthConfig(
        secret_key=jwt_settings.secret_key,
        issuer=jwt_settings.issuer,
        audience=jwt_settings.audience,
        public_paths=[
            "/",
            "/health",
            "/internal",
            "/buzz",
            "/api/v1/buzz",
            "/api/v1/hermes",
            "/docs",
            "/redoc",
            "/openapi.json",
        ],
        algorithm=jwt_settings.algorithm,
        private_key_path=jwt_settings.private_key_path,
        public_key_path=jwt_settings.public_key_path,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware, config=auth_config)
    app.add_middleware(CorrelationIdMiddleware)

    @app.exception_handler(BaseAppException)
    async def app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", "")
        logger.error(
            "Application error",
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                "metadata": {"timestamp": str(time.time()), "correlation_id": correlation_id},
            },
        )

    app.include_router(health_router)
    app.include_router(internal_router)
    app.include_router(api_router, prefix="/api/v1")

    ui_dir = Path(__file__).resolve().parent / "api" / "buzz_ui"
    if ui_dir.is_dir():
        app.mount("/buzz", StaticFiles(directory=str(ui_dir), html=True), name="buzz_ui")

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/buzz/")

    logger.info("FastAPI application configured")
    return app
