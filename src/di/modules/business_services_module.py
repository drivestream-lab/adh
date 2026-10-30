"""Business services DI module for adh."""

from injector import Binder, Module, singleton

from src.business_services.buzz_service import BuzzService
from src.business_services.hermes_service import HermesService
from src.business_services.orchestrator_service import OrchestratorService
from src.logging import get_logger

logger = get_logger()


class BusinessServicesModule(Module):
    def configure(self, binder: Binder) -> None:
        logger.info("Configuring business services module")
        binder.bind(BuzzService, to=BuzzService, scope=singleton)
        binder.bind(HermesService, to=HermesService, scope=singleton)
        binder.bind(OrchestratorService, to=OrchestratorService, scope=singleton)
