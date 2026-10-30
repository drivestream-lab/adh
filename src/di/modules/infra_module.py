"""Infrastructure services module for dependency injection."""

from injector import Module, singleton

from src.database.postgres.connection_manager import PostgresConnectionManager
from src.database.redis.connection_manager import RedisConnectionManager
from src.infra_services.buzz_http_service import BuzzHttpService
from src.infra_services.cursor_cli_service import CursorCliService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.hermes_store_service import HermesStoreService
from src.infra_services.litellm_service import LiteLLMService
from src.infra_services.pin_walker_service import PinWalkerService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.postgres_service import PostgresService
from src.infra_services.prompt_service import PromptService
from src.infra_services.redis_service import RedisService
from src.infra_services.telemetry_service import TelemetryService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.logging import get_logger

logger = get_logger()


class InfraModule(Module):
    """Register core infrastructure services."""

    def configure(self, binder) -> None:
        logger.info("Configuring infrastructure services module")
        binder.bind(PostgresConnectionManager, to=PostgresConnectionManager, scope=singleton)
        binder.bind(RedisConnectionManager, to=RedisConnectionManager, scope=singleton)
        binder.bind(PostgresService, to=PostgresService, scope=singleton)
        binder.bind(RedisService, to=RedisService, scope=singleton)
        binder.bind(LiteLLMService, to=LiteLLMService, scope=singleton)
        binder.bind(PromptService, to=PromptService, scope=singleton)
        binder.bind(HermesStoreService, to=HermesStoreService, scope=singleton)
        binder.bind(PinWalkerService, to=PinWalkerService, scope=singleton)
        binder.bind(GitHubAppService, to=GitHubAppService, scope=singleton)
        binder.bind(TenantRegistryService, to=TenantRegistryService, scope=singleton)
        binder.bind(PmWorkspaceService, to=PmWorkspaceService, scope=singleton)
        binder.bind(CursorCliService, to=CursorCliService, scope=singleton)
        binder.bind(BuzzHttpService, to=BuzzHttpService, scope=singleton)
        binder.bind(TelemetryService, scope=singleton)
        logger.debug("Infrastructure services module configured")
