#!/usr/bin/env bash

# Run PostgreSQL migrations with Alembic (project .venv preferred).
# Usage: ./scripts/run_postgres_migration.sh [target]
# Examples:
#   ./scripts/run_postgres_migration.sh         # Run all migrations to head
#   ./scripts/run_postgres_migration.sh head    # Run all migrations to head
#   ./scripts/run_postgres_migration.sh +1      # Run one migration forward
#   ./scripts/run_postgres_migration.sh -1      # Roll back one migration
#
# Human-owned apply step after create_postgres_migration.sh (autogenerate).
# Prefers .venv/bin/alembic; falls back to alembic on PATH (e.g. Docker system install).
# For local use: run `make setup` first. Do not rely on conda PATH.
# Policy: python-services-rules database-migrations.mdc (v0.5.12+). Agents must not run this unless explicitly asked.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

TARGET=${1:-head}

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

COMMAND="upgrade"

if [[ "${TARGET}" == -1 ]]; then
    # Roll back one migration: resolve current revision and downgrade to its parent
    COMMAND="downgrade"
    CURRENT_REV=$("${ALEMBIC}" -c "${ALEMBIC_CONFIG}" current 2>/dev/null | awk '{print $1}' || echo "")
    if [ -z "${CURRENT_REV}" ] || [ "${CURRENT_REV}" = "None" ]; then
        echo "No current revision; nothing to downgrade."
        exit 1
    fi
    # Parent = first column of the history line that has "-> current_rev" (format: "parent -> child")
    TARGET=$("${ALEMBIC}" -c "${ALEMBIC_CONFIG}" history 2>/dev/null | grep -E -- "->.*${CURRENT_REV}" | head -1 | awk '{print $1}' || echo "")
    if [ -z "${TARGET}" ] || [[ ! "${TARGET}" =~ ^[a-f0-9]+$ ]]; then
        echo "Could not determine parent revision for downgrade (current: ${CURRENT_REV})."
        exit 1
    fi
    echo "Downgrading one step: ${CURRENT_REV} -> ${TARGET}"
elif [[ "${TARGET}" =~ ^-[0-9]+$ ]]; then
    echo "Only -1 (roll back one) is supported. Use: ./scripts/run_postgres_migration.sh <revision> to downgrade to a specific revision."
    exit 1
elif [[ "${TARGET}" != "head" && "${TARGET}" != "+"* ]]; then
    # Explicit revision: downgrade if it's an ancestor of current (target is in the past)
    CURRENT_REV=$("${ALEMBIC}" -c "${ALEMBIC_CONFIG}" current 2>/dev/null | awk '{print $1}' || echo "")
    if [ -n "${CURRENT_REV}" ] && [ "${CURRENT_REV}" != "None" ] && [ "${CURRENT_REV}" != "${TARGET}" ]; then
        REV="${CURRENT_REV}"
        while [ -n "${REV}" ]; do
            [ "${REV}" = "${TARGET}" ] && COMMAND="downgrade" && break
            PARENT=$("${ALEMBIC}" -c "${ALEMBIC_CONFIG}" history 2>/dev/null | grep -E -- "->.*${REV}" | head -1 | awk '{print $1}' || echo "")
            [ -z "${PARENT}" ] || [ "${PARENT}" = "<base>" ] && break
            REV="${PARENT}"
        done
    fi
fi

echo "Running PostgreSQL migrations: ${COMMAND} to target: ${TARGET}"
echo "Using: ${ALEMBIC}"
"${ALEMBIC}" -c "${ALEMBIC_CONFIG}" "${COMMAND}" "${TARGET}"

echo "PostgreSQL migration completed successfully!"
