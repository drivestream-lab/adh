"""Alembic environment configuration for adh PostgreSQL migrations."""

import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.configs.postgres_settings import PostgresSettings
from src.database.postgres.schema.base_postgres_schema import postgres_metadata

target_metadata = postgres_metadata

config = context.config
if config.config_file_name is not None:
    from logging.config import fileConfig

    fileConfig(config.config_file_name)


def get_url() -> str:
    return PostgresSettings.get_instance().alembic_database_uri


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
