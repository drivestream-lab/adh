"""Health check router for adh."""

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_postgres_service, get_redis_service
from src.infra_services.postgres_service import PostgresService
from src.infra_services.redis_service import RedisService
from src.logging import get_logger
from src.models.health_models import (
    HealthDetailedResponse,
    HealthSimpleResponse,
    HealthStatusType,
    ServiceHealthDetailModel,
)

logger = get_logger()
router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthSimpleResponse | HealthDetailedResponse)
async def health_check(
    detailed: bool = Query(default=False, description="Return detailed dependency health"),
    postgres_service: PostgresService = Depends(get_postgres_service),
    redis_service: RedisService = Depends(get_redis_service),
) -> HealthSimpleResponse | HealthDetailedResponse:
    if not detailed:
        return HealthSimpleResponse()

    postgres_healthy = False
    try:
        postgres_healthy = await postgres_service.health_check()
    except Exception as e:
        logger.error("Error checking PostgreSQL health", error=str(e))

    redis_healthy = False
    try:
        redis_healthy = await redis_service.health_check()
    except Exception as e:
        logger.error("Error checking Redis health", error=str(e))

    all_healthy = postgres_healthy and redis_healthy
    agg = HealthStatusType.UP if all_healthy else HealthStatusType.DOWN
    return HealthDetailedResponse(
        status=agg,
        services={
            "postgres": ServiceHealthDetailModel(
                status=HealthStatusType.UP if postgres_healthy else HealthStatusType.DOWN,
                details={"healthy": postgres_healthy},
            ),
            "redis": ServiceHealthDetailModel(
                status=HealthStatusType.UP if redis_healthy else HealthStatusType.DOWN,
                details={"healthy": redis_healthy},
            ),
        },
    )
