"""Verify preflight — checks infra is up before running verify tests."""

import asyncio
import sys


async def check_postgres():
    import asyncpg
    from src.configs.postgres_settings import PostgresSettings

    s = PostgresSettings.get_instance()
    conn = await asyncpg.connect(
        host=s.host, port=s.port, user=s.user, password=s.password.get_secret_value(), database=s.db
    )
    await conn.close()
    print("✓ postgres reachable")


async def check_redis():
    import redis.asyncio as redis
    from src.configs.redis_settings import RedisSettings

    s = RedisSettings.get_instance()
    r = redis.Redis(**s.connection_params)
    await r.ping()
    await r.aclose()
    print("✓ redis reachable")


async def main():
    tasks = []

    tasks.append(check_postgres())

    tasks.append(check_redis())

    if not tasks:
        print("✓ no infra to preflight")
        return
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [r for r in results if isinstance(r, Exception)]
    if failures:
        for f in failures:
            print(f"✗ {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
