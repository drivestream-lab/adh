"""HTTP API for Hermes PM and after-PR lanes."""

from fastapi import APIRouter, Depends

from src.api.dependencies import get_hermes_service
from src.business_services.hermes_service import HermesService
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
    hermes: HermesService = Depends(get_hermes_service),
) -> HermesArtifactRead:
    return await hermes.run_pm_brief(payload or HermesBriefRequest())


@router.post("/eng/grade", response_model=HermesArtifactRead, status_code=201)
@handle_api_errors("run eng grade", "Hermes")
async def run_eng_grade(
    payload: HermesGradeRequest | None = None,
    hermes: HermesService = Depends(get_hermes_service),
) -> HermesArtifactRead:
    return await hermes.run_eng_grade(payload or HermesGradeRequest())


@router.get("/ledger", response_model=list[HermesArtifactRead])
@handle_api_errors("list ledger", "Hermes")
async def list_ledger(
    hermes: HermesService = Depends(get_hermes_service),
) -> list[HermesArtifactRead]:
    return await hermes.list_ledger()
