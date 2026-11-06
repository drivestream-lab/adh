"""Programme runner protocol + in-process registry for the control plane."""

from __future__ import annotations

from typing import Optional, Protocol

from src.adh_agents.runtime.work_models import AgentWorkSession
from src.models.tenant_models import TenantContext


class ProgrammeRunner(Protocol):
    """Hook that walks a programme once the Orchestrator has bound an entrypoint."""

    programme_id: str

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None: ...

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None: ...

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None: ...

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]: ...


class ProgrammeRunnerRegistry:
    """Role-local registry of programmes this agent process can run."""

    def __init__(self) -> None:
        self._runners: dict[str, ProgrammeRunner] = {}

    def register(self, runner: ProgrammeRunner) -> None:
        pid = (getattr(runner, "programme_id", None) or "").strip()
        if not pid:
            raise ValueError("ProgrammeRunner.programme_id is required")
        self._runners[pid] = runner

    def get(self, programme_id: str) -> Optional[ProgrammeRunner]:
        return self._runners.get((programme_id or "").strip())

    def all(self) -> list[ProgrammeRunner]:
        return list(self._runners.values())

    def programme_ids(self) -> frozenset[str]:
        return frozenset(self._runners)

    def primary(self) -> Optional[ProgrammeRunner]:
        """Single-runner convenience (PM meta-pm, PE, …)."""
        runners = self.all()
        return runners[0] if len(runners) == 1 else None

    def resolve_for_session(self, session: AgentWorkSession) -> Optional[ProgrammeRunner]:
        if session.programme:
            return self.get(session.programme)
        return self.primary()
