# Live verify: health with real postgres + redis

## Prerequisites

- `docker compose -f docker/docker-compose.yml up -d`
- `cp .env.example .env`
- `make setup && make run`

## Steps

1. Simple liveness: `curl -s http://localhost:8000/health` → `{"status":"ok"}`
2. Detailed health: `curl -s 'http://localhost:8000/health?detailed=true'`
   - Expect `postgres` and `redis` both `UP`
3. Protected route: `curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/v1/` → `401`
