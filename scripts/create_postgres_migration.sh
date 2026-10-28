#!/usr/bin/env bash

# Create a new PostgreSQL migration revision with Alembic (project .venv preferred).
# Usage: ./scripts/create_postgres_migration.sh "Description of the migration"
#
# Runs alembic revision --autogenerate to materialize postgres_migrations/versions/.
# Agents/implementers run this after schema/env.py updates. Humans apply with
# run_postgres_migration.sh (agents must not run apply).
# Prefers .venv/bin/alembic; falls back to alembic on PATH (e.g. Docker system install).
# For local use: run `make setup` first. Do not rely on conda PATH.
# Policy: python-services-rules database-migrations.mdc (v0.5.12+).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [ -z "${1:-}" ]; then
    echo "[ERROR] Migration description is required"
    echo "Usage: $0 \"Description of the migration\""
    exit 1
fi

DESCRIPTION="$1"

if [ -x "${REPO_ROOT}/.venv/bin/alembic" ]; then
    ALEMBIC="${REPO_ROOT}/.venv/bin/alembic"
elif command -v alembic >/dev/null 2>&1; then
    ALEMBIC="$(command -v alembic)"
else
    echo "[ERROR] Alembic not found at ${REPO_ROOT}/.venv/bin/alembic and not on PATH"
    echo "        Create the project venv first: make setup"
    echo "        (Do not use conda — this repo uses Python 3.12 + .venv only.)"
    exit 1
fi

ALEMBIC_CONFIG="${REPO_ROOT}/postgres_migrations/alembic.ini"
if [ ! -f "${ALEMBIC_CONFIG}" ]; then
    echo "[ERROR] Missing Alembic config: ${ALEMBIC_CONFIG}"
    exit 1
fi

if [ -f .env ]; then
    echo "Loading environment variables from .env file"
    while IFS='=' read -r key value || [ -n "${key:-}" ]; do
        [[ -z "${key}" || "${key}" =~ ^# ]] && continue
        case "${key}" in
            POSTGRES_*|DATABASE_*|DB_*)
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                export "${key}=${value}"
                ;;
        esac
    done < .env
fi

# Check if database is up to date before creating new migration
CURRENT_REV=$("${ALEMBIC}" -c "${ALEMBIC_CONFIG}" current 2>/dev/null | awk '{print $1}' || echo "")
HEAD_REV=$("${ALEMBIC}" -c "${ALEMBIC_CONFIG}" heads 2>/dev/null | awk 'NR==1 {print $1}' || echo "")

if [ -n "${HEAD_REV}" ] && [ "${CURRENT_REV}" != "${HEAD_REV}" ]; then
    echo "[ERROR] Target database is not up to date."
    echo "  Current revision: ${CURRENT_REV:-None}"
    echo "  Head revision:   ${HEAD_REV}"
    echo ""
    echo "Run existing migrations first (human-owned apply):"
    echo "  ./scripts/run_postgres_migration.sh head"
    echo ""
    exit 1
fi

echo "Creating new PostgreSQL migration: ${DESCRIPTION}"
echo "Using: ${ALEMBIC}"
# Autogenerate from registered postgres_metadata (python-services-rules v0.5.12+).
"${ALEMBIC}" -c "${ALEMBIC_CONFIG}" revision --autogenerate -m "${DESCRIPTION}"

echo "Migration created successfully!"
echo "The new migration file can be found in postgres_migrations/versions/"
echo ""
echo "IMPORTANT: Review the generated migration file to ensure:"
echo "1. All table dependencies are correctly managed"
echo "2. Tables are created in the correct order"
echo "3. upgrade/downgrade match the intended DDL (adjust when autogenerate is wrong)"
echo ""
echo "Apply is human-owned (do not run from agent sessions unless asked):"
echo "  ./scripts/run_postgres_migration.sh head"
echo ""
echo "Do not invent revision files outside this script. Do not write DDL-NOTE substitutes."
