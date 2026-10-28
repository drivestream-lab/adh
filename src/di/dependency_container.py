"""Dependency injection container for adh."""

from typing import Any, Optional, Type, TypeVar

from injector import Injector

from src.business_services.buzz_service import BuzzService
from src.configs.app_settings import AppSettings
from src.infra_services.postgres_service import PostgresService
from src.infra_services.redis_service import RedisService
from src.infra_services.telemetry_service import TelemetryService
from src.logging import get_logger

T = TypeVar("T")
_injector: Optional[Injector] = None
logger = get_logger()

# Postgres first — business services depend on session factory from PostgresService.
_INFRA_SERVICE_TYPES: tuple[type, ...] = (
    PostgresService,
    RedisService,
    TelemetryService,
)

_BUSINESS_SERVICE_TYPES: tuple[type, ...] = (BuzzService,)


def configure_container() -> Injector:
    from src.di.modules.business_services_module import BusinessServicesModule
    from src.di.modules.config_module import ConfigModule
    from src.di.modules.infra_module import InfraModule
    from src.di.modules.repository_module import RepositoryModule

    settings = AppSettings.get_instance()
    global _injector
    if _injector is None:
        logger.info("Configuring DI container", environment=str(settings.environment))
        _injector = Injector(
            [
                ConfigModule(),
                InfraModule(),
                RepositoryModule(),
                BusinessServicesModule(),
            ]
        )
        logger.info("DI container configured successfully")
    return _injector


async def _close_service(injector: Injector, service_type: Type[Any]) -> None:
    try:
        await injector.get(service_type).close()
    except Exception as e:
        logger.warning("Error closing service", service_type=service_type.__name__, error=str(e))


async def initialize_all_services() -> None:
    logger.info("Initializing all application services")
    injector = get_container()
    for service_type in _INFRA_SERVICE_TYPES:
        await injector.get(service_type).initialize()
    for service_type in _BUSINESS_SERVICE_TYPES:
        await injector.get(service_type).initialize()
    logger.info("All application services initialized successfully")


async def close_all_services() -> None:
    logger.info("Closing all application services")
    injector = get_container()
    for service_type in reversed(_BUSINESS_SERVICE_TYPES):
        await _close_service(injector, service_type)
    for service_type in reversed(_INFRA_SERVICE_TYPES):
        await _close_service(injector, service_type)
    logger.info("All application services closed")


def get_container() -> Injector:
    global _injector
    if _injector is None:
        raise RuntimeError("Call configure_container() first")
    return _injector


def reset_container() -> None:
    global _injector
    _injector = None


def provide_service(cls: Type[T]) -> T:
    if _injector is None:
        configure_container()
    return get_container().get(cls)
