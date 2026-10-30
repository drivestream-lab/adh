"""API v1 — compose product routers here."""

from fastapi import APIRouter

from src.api.v1.buzz_router import router as buzz_router
from src.api.v1.hermes_router import router as hermes_router
from src.api.v1.orchestrator_router import router as orchestrator_router

api_router = APIRouter()
api_router.include_router(buzz_router)
api_router.include_router(hermes_router)
api_router.include_router(orchestrator_router)
