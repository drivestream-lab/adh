"""Business services DI module for adh."""

from injector import Binder, Module, singleton

from src.adh_agents.agents.dev_agent import DevAgent
from src.adh_agents.agents.kb_agent import KbAgent
from src.adh_agents.agents.pe_agent import PEAgent
from src.adh_agents.agents.pm_agent import PMAgent
from src.adh_agents.agents.read_agent import ReadAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.catalogue.navigator import HermesNavigatorService
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.execution.dispatch_service import HermesDispatchService
from src.adh_agents.programmes.dev.programme import DevEnggProgramme
from src.adh_agents.programmes.kb.enrich import KbEnrichProgramme
from src.adh_agents.programmes.pe.engg_handoff import PeEnggHandoff
from src.adh_agents.programmes.pe.review import PeReviewProgramme
from src.adh_agents.programmes.pm.authoring import AuthoringProgrammeService
from src.adh_agents.programmes.pm.http_lanes import PmHttpLanesService
from src.adh_agents.programmes.pm.meta_pm import MetaPmProgrammeService
from src.adh_agents.programmes.pm.pe_answers import PmPeAnswersProgramme
from src.adh_agents.programmes.pm.pe_glue import PmPeGlueProgramme
from src.adh_agents.programmes.pm.rewind_coach import RewindCoachProgramme
from src.adh_agents.programmes.pm.rewind_execute import RewindExecuteService
from src.adh_agents.programmes.pm.task_lifecycle import TaskLifecycleProgramme
from src.adh_agents.programmes.pm.traj_coach import TrajCoachProgramme
from src.adh_agents.programmes.read.walk import ReadWalkProgramme
from src.adh_agents.ingress.github_ingress import GitHubIngressService
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.gate_opener import GateOpener
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
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
        binder.bind(PresenceService, to=PresenceService, scope=singleton)
        binder.bind(AutonomyPolicy, to=AutonomyPolicy, scope=singleton)
        binder.bind(GateOpener, to=GateOpener, scope=singleton)
        binder.bind(TaskLifecycleProgramme, to=TaskLifecycleProgramme, scope=singleton)
        binder.bind(RewindExecuteService, to=RewindExecuteService, scope=singleton)
        binder.bind(RewindCoachProgramme, to=RewindCoachProgramme, scope=singleton)
        binder.bind(TrajCoachProgramme, to=TrajCoachProgramme, scope=singleton)
        binder.bind(GitHubIngressService, to=GitHubIngressService, scope=singleton)
        binder.bind(Orchestrator, to=Orchestrator, scope=singleton)
        binder.bind(PmPeAnswersProgramme, to=PmPeAnswersProgramme, scope=singleton)
        binder.bind(PmPeGlueProgramme, to=PmPeGlueProgramme, scope=singleton)
        binder.bind(MetaPmProgrammeService, to=MetaPmProgrammeService, scope=singleton)
        binder.bind(AuthoringProgrammeService, to=AuthoringProgrammeService, scope=singleton)
        binder.bind(PeEnggHandoff, to=PeEnggHandoff, scope=singleton)
        binder.bind(PeReviewProgramme, to=PeReviewProgramme, scope=singleton)
        binder.bind(ReadWalkProgramme, to=ReadWalkProgramme, scope=singleton)
        binder.bind(KbEnrichProgramme, to=KbEnrichProgramme, scope=singleton)
        binder.bind(DevEnggProgramme, to=DevEnggProgramme, scope=singleton)
        binder.bind(PmHttpLanesService, to=PmHttpLanesService, scope=singleton)
        # Agents: bound for workers; only PM auto-inits with the API process.
        binder.bind(PMAgent, to=PMAgent, scope=singleton)
        binder.bind(PEAgent, to=PEAgent, scope=singleton)
        binder.bind(ReadAgent, to=ReadAgent, scope=singleton)
        binder.bind(KbAgent, to=KbAgent, scope=singleton)
        binder.bind(DevAgent, to=DevAgent, scope=singleton)
