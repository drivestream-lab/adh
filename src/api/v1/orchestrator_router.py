"""HTTP API for the host orchestrator. Spawn is disabled in Docker by default."""

from fastapi import APIRouter, Depends

from src.api.dependencies import get_orchestrator_service
from src.business_services.orchestrator_service import OrchestratorService
from src.configs.orchestrator_settings import OrchestratorSettings
from src.exceptions.app_exceptions import ServiceUnavailableError
from src.models.orchestrator_models import MergeRequest, PinDocument, SpawnResult
from src.utils.api_helpers import handle_api_errors

router = APIRouter(prefix="/orchestrator", tags=["Orchestrator"])


@router.get("/pin", response_model=PinDocument)
@handle_api_errors("read pin", "Orchestrator")
async def read_pin(
    orch: OrchestratorService = Depends(get_orchestrator_service),
) -> PinDocument:
    return await orch.pin()


@router.post("/spawn", response_model=SpawnResult, status_code=201)
@handle_api_errors("spawn coder", "Orchestrator")
async def spawn_coder(
    orch: OrchestratorService = Depends(get_orchestrator_service),
) -> SpawnResult:
    settings = OrchestratorSettings.get_instance()
    if not settings.enable_spawn:
        raise ServiceUnavailableError(
            "orchestrator",
            "spawn is host-only; run `make orch-spawn` on the laptop",
        )
    return await orch.spawn_next()


@router.post("/merge")
@handle_api_errors("merge wave", "Orchestrator")
async def merge_wave(
    payload: MergeRequest | None = None,
    orch: OrchestratorService = Depends(get_orchestrator_service),
) -> dict[str, str]:
    await orch.merge_wave(payload or MergeRequest())
    return {"status": "merged"}
