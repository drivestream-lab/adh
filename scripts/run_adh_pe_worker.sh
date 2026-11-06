#!/usr/bin/env bash
# Host ADH pe worker against local Docker Buzz / Postgres / Redis / LiteLLM.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WORKSPACE_ROOT="${ORCH_WORKSPACE_ROOT:-$(cd "$ROOT/.." && pwd)}"

export APP_ENVIRONMENT="${APP_ENVIRONMENT:-development}"
export APP_LOG_LEVEL="${APP_LOG_LEVEL:-INFO}"
export APP_LOG_FORMAT="${APP_LOG_FORMAT:-text}"
export APP_LOG_TO_CONSOLE="${APP_LOG_TO_CONSOLE:-true}"

export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_USER="${POSTGRES_USER:-adh}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-adh}"
export POSTGRES_DB="${POSTGRES_DB:-buzz}"

export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export REDIS_PREFIX="${REDIS_PREFIX:-adh_buzz:}"

export BUZZ_SEED_ON_START="${BUZZ_SEED_ON_START:-false}"
export BUZZ_PUBLISH_SYSTEM_HEARTBEAT="${BUZZ_PUBLISH_SYSTEM_HEARTBEAT:-false}"

export HERMES_LITELLM_BASE_URL="${HERMES_LITELLM_BASE_URL:-http://localhost:4000/v1}"
export HERMES_LITELLM_API_KEY="${HERMES_LITELLM_API_KEY:-sk-adh-local-master}"
export HERMES_MODEL="${HERMES_MODEL:-qwen}"
export HERMES_PM_MODEL="${HERMES_PM_MODEL:-sonnet}"
export HERMES_ENG_MODEL="${HERMES_ENG_MODEL:-qwen}"
export HERMES_PG_HOST="${HERMES_PG_HOST:-localhost}"
export HERMES_PG_PORT="${HERMES_PG_PORT:-5432}"
export HERMES_PG_USER="${HERMES_PG_USER:-adh}"
export HERMES_PG_PASSWORD="${HERMES_PG_PASSWORD:-adh}"
export HERMES_PG_DB="${HERMES_PG_DB:-hermes}"
export HERMES_LEDGER_DB="${HERMES_LEDGER_DB:-ledger}"
export HERMES_LISTEN_OPS="${HERMES_LISTEN_OPS:-true}"
export HERMES_RUN_BOOT_JOBS="${HERMES_RUN_BOOT_JOBS:-false}"
export HERMES_PM_SKILL_RUNNER_ENABLED="${HERMES_PM_SKILL_RUNNER_ENABLED:-true}"
export HERMES_WAIT_STEP_SECONDS="${HERMES_WAIT_STEP_SECONDS:-90}"
export HERMES_PROGRESS_SECONDS="${HERMES_PROGRESS_SECONDS:-90}"
export HERMES_WAIT_STEPS="${HERMES_WAIT_STEPS:-40}"
export HERMES_TIMEOUT_SECONDS="${HERMES_TIMEOUT_SECONDS:-3600}"
export HERMES_PM_MAX_THINK_RUNS="${HERMES_PM_MAX_THINK_RUNS:-4}"
export HERMES_REPO_ROOT="${HERMES_REPO_ROOT:-$ROOT}"
export HERMES_PRAYOG_SKILLS_ROOT="${HERMES_PRAYOG_SKILLS_ROOT:-$ROOT/prayog-skills}"

export ORCH_WORKSPACE_ROOT="$WORKSPACE_ROOT"
export ORCH_META_ROOT="${ORCH_META_ROOT:-$WORKSPACE_ROOT/adh-meta}"
export ORCH_BUZZ_BASE_URL="${ORCH_BUZZ_BASE_URL:-http://localhost:8080}"
export ORCH_CURSOR_BIN="${ORCH_CURSOR_BIN:-agent}"
export ORCH_CURSOR_TIMEOUT_SECONDS="${ORCH_CURSOR_TIMEOUT_SECONDS:-3600}"
export ORCH_HEARTBEAT_SECONDS="${ORCH_HEARTBEAT_SECONDS:-90}"
export ORCH_GITHUB_ORG="${ORCH_GITHUB_ORG:-drivestream-lab}"

# JWT unused by the worker (no HTTP), but settings may still load elsewhere.
export JWT_ALGORITHM="${JWT_ALGORITHM:-HS256}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-adh-local-jwt}"
export JWT_ISSUER="${JWT_ISSUER:-adh}"
export JWT_AUDIENCE="${JWT_AUDIENCE:-drivestream}"

if ! command -v "${ORCH_CURSOR_BIN}" >/dev/null 2>&1; then
  echo "ERROR: Cursor agent binary not on PATH: ${ORCH_CURSOR_BIN}" >&2
  exit 1
fi

curl -sf "${ORCH_BUZZ_BASE_URL}/health" >/dev/null || {
  echo "ERROR: Buzz not healthy at ${ORCH_BUZZ_BASE_URL}/health — start with make buzz-up in adh-iac-local" >&2
  exit 1
}

exec .venv/bin/python -m src.adh_pe_worker
