#!/bin/bash
set -e

echo "[INFO] Starting adh with database migrations"

wait_for_db() {
    python -c "
import os, sys, time
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

def check_postgres():
    try:
        db_host = os.getenv('POSTGRES_HOST', 'localhost')
        db_port = os.getenv('POSTGRES_PORT', '5432')
        db_name = os.getenv('POSTGRES_DB', 'ds_adh_db')
        db_user = os.getenv('POSTGRES_USER', 'postgres')
        db_pass = os.getenv('POSTGRES_PASSWORD', 'postgres')
        db_pass_encoded = quote_plus(db_pass)
        connection_string = f'postgresql+psycopg2://{db_user}:{db_pass_encoded}@{db_host}:{db_port}/{db_name}'
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('[OK] PostgreSQL is ready')
        return True
    except Exception as e:
        print(f'[ERROR] PostgreSQL not ready: {e}')
        return False

for _ in range(60):
    if check_postgres():
        sys.exit(0)
    time.sleep(1)
print('[ERROR] Database not ready after 60 seconds')
sys.exit(1)
"
}

wait_for_db
./scripts/run_postgres_migration.sh
exec python -m src.main
