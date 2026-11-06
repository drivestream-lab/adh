"""Business services DI module for adh."""

from injector import Binder, Module, singleton

from src.business_services.buzz_service import BuzzService
from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.execution.dispatch_service import HermesDispatchService
from src.business_services.hermes.programmes.authoring_programme import (
    AuthoringProgrammeService,
)
from src.business_services.hermes.programmes.meta_pm_programme import MetaPmProgrammeService
from src.business_services.hermes.runtime.navigator_service import HermesNavigatorService
from src.business_services.hermes.runtime.orchestrator_service import HermesCollaboratorService
from src.business_services.hermes.runtime.session_store import HermesSessionStoreService
from src.business_services.hermes.surface.buzz_poster import HermesBuzzPoster
from src.business_services.hermes.understanding.understand_service import (
    HermesUnderstandService,
)
from src.business_services.hermes_service import HermesService
from src.business_services.orchestrator_service import OrchestratorService
from src.adh_agents.agents.pm_agent import PMAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.logging import get_logger

logger = get_logger()


class BusinessServicesModule(Module):
    def configure(self, binder: Binder) -> None:
        logger.info("Configuring business services module")
        binder.bind(BuzzService, to=BuzzService, scope=singleton)
        binder.bind(RedisBatonStore, to=RedisBatonStore, scope=singleton)
        binder.bind(HermesUnderstandService, to=HermesUnderstandService, scope=singleton)
        binder.bind(HermesSessionStoreService, to=HermesSessionStoreService, scope=singleton)
        binder.bind(HermesBriefService, to=HermesBriefService, scope=singleton)
        binder.bind(HermesNavigatorService, to=HermesNavigatorService, scope=singleton)
        binder.bind(HermesDispatchService, to=HermesDispatchService, scope=singleton)
        binder.bind(HermesBuzzPoster, to=HermesBuzzPoster, scope=singleton)
        binder.bind(HermesCollaboratorService, to=HermesCollaboratorService, scope=singleton)
        binder.bind(MetaPmProgrammeService, to=MetaPmProgrammeService, scope=singleton)
        binder.bind(AuthoringProgrammeService, to=AuthoringProgrammeService, scope=singleton)
        binder.bind(HermesService, to=HermesService, scope=singleton)
        binder.bind(PMAgent, to=PMAgent, scope=singleton)
        binder.bind(OrchestratorService, to=OrchestratorService, scope=singleton)
