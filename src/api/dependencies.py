"""FastAPI dependencies for adh."""

from src.business_services.buzz_service import BuzzService
from src.infra_services.postgres_service import PostgresService
from src.infra_services.redis_service import RedisService


def get_postgres_service() -> PostgresService:
    from src.di.dependency_container import provide_service

    return provide_service(PostgresService)


def get_redis_service() -> RedisService:
    from src.di.dependency_container import provide_service

    return provide_service(RedisService)


def get_buzz_service() -> BuzzService:
    from src.di.dependency_container import provide_service

    return provide_service(BuzzService)
