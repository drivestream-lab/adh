# Multi-stage build for adh.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*
RUN pip install poetry

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && \
    poetry install --only=main --no-root --no-interaction --no-ansi

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN groupadd -r app && useradd -r -g app app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --chown=app:app src/ ./src/
COPY --chown=app:app postgres_migrations/ ./postgres_migrations/
COPY --chown=app:app scripts/ ./scripts/
COPY docker/adh/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh && chmod +x scripts/*.sh
RUN mkdir -p logs && chown app:app logs

USER app
EXPOSE 8080

HEALTHCHECK --interval=300s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
