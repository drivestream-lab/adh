"""API v1 — compose product routers here."""

from fastapi import APIRouter

from src.api.v1.buzz_router import router as buzz_router

api_router = APIRouter()
api_router.include_router(buzz_router)
