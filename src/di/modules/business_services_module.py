"""Business services DI module for adh."""

from injector import Binder, Module, singleton

from src.adh_agents.agents.kb_agent import KbAgent
from src.adh_agents.agents.pe_agent import PEAgent
from src.adh_agents.agents.pm_agent import PMAgent
from src.adh_agents.agents.read_agent import ReadAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.catalogue.navigator import HermesNavigatorService
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.execution.dispatch_service import HermesDispatchService
from src.adh_agents.programmes.kb.enrich import KbEnrichProgramme
from src.adh_agents.programmes.pe.review import PeReviewProgramme
from src.adh_agents.programmes.pm.authoring import AuthoringProgrammeService
from src.adh_agents.programmes.pm.http_lanes import PmHttpLanesService
from src.adh_agents.programmes.pm.meta_pm import MetaPmProgrammeService
from src.adh_agents.programmes.read.walk import ReadWalkProgramme
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.adh_agents.understanding.understand_service import HermesUnderstandService
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger

logger = get_logger()


class BusinessServicesModule(Module):
    def configure(self, binder: Binder) -> None:
        logger.info("Configuring business services module")
        binder.bind(BuzzService, to=BuzzService, scope=singleton)
        binder.bind(RedisBatonStore, to=RedisBatonStore, scope=singleton)
        binder.bind(HermesUnderstandService, to=HermesUnderstandService, scope=singleton)
        binder.bind(AgentWorkStore, to=AgentWorkStore, scope=singleton)
        binder.bind(HermesBriefService, to=HermesBriefService, scope=singleton)
        binder.bind(HermesNavigatorService, to=HermesNavigatorService, scope=singleton)
        binder.bind(HermesDispatchService, to=HermesDispatchService, scope=singleton)
        binder.bind(HermesBuzzPoster, to=HermesBuzzPoster, scope=singleton)
        binder.bind(Orchestrator, to=Orchestrator, scope=singleton)
        binder.bind(MetaPmProgrammeService, to=MetaPmProgrammeService, scope=singleton)
        binder.bind(AuthoringProgrammeService, to=AuthoringProgrammeService, scope=singleton)
        binder.bind(PeReviewProgramme, to=PeReviewProgramme, scope=singleton)
        binder.bind(ReadWalkProgramme, to=ReadWalkProgramme, scope=singleton)
        binder.bind(KbEnrichProgramme, to=KbEnrichProgramme, scope=singleton)
        binder.bind(PmHttpLanesService, to=PmHttpLanesService, scope=singleton)
        # Agents: bound for workers; only PM auto-inits with the API process.
        binder.bind(PMAgent, to=PMAgent, scope=singleton)
        binder.bind(PEAgent, to=PEAgent, scope=singleton)
        binder.bind(ReadAgent, to=ReadAgent, scope=singleton)
        binder.bind(KbAgent, to=KbAgent, scope=singleton)
