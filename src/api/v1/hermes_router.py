"""HTTP API for PM brief / eng grade / ledger (not Team OS control plane)."""

from fastapi import APIRouter, Depends

from src.api.dependencies import get_pm_http_lanes
from src.adh_agents.programmes.pm.http_lanes import PmHttpLanesService
from src.models.hermes_models import (
    HermesArtifactRead,
    HermesBriefRequest,
    HermesGradeRequest,
)
from src.utils.api_helpers import handle_api_errors

router = APIRouter(prefix="/hermes", tags=["Hermes"])


@router.post("/pm/brief", response_model=HermesArtifactRead, status_code=201)
@handle_api_errors("run PM brief", "Hermes")
async def run_pm_brief(
    payload: HermesBriefRequest | None = None,
    lanes: PmHttpLanesService = Depends(get_pm_http_lanes),
) -> HermesArtifactRead:
    return await lanes.run_pm_brief(payload or HermesBriefRequest())


@router.post("/eng/grade", response_model=HermesArtifactRead, status_code=201)
@handle_api_errors("run eng grade", "Hermes")
async def run_eng_grade(
    payload: HermesGradeRequest | None = None,
    lanes: PmHttpLanesService = Depends(get_pm_http_lanes),
) -> HermesArtifactRead:
    return await lanes.run_eng_grade(payload or HermesGradeRequest())


@router.get("/ledger", response_model=list[HermesArtifactRead])
@handle_api_errors("list ledger", "Hermes")
async def list_ledger(
    lanes: PmHttpLanesService = Depends(get_pm_http_lanes),
) -> list[HermesArtifactRead]:
    return await lanes.list_ledger()
