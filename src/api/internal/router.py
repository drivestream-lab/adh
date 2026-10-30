"""Internal API router — service-to-service endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/internal/v1", tags=["Internal"])

# Add internal routes here as product spec defines S2S contracts.
