#!/bin/sh
# Single uvicorn process: the job queue and SQLite assume exactly one process.
set -eu
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${IRIS_PORT:-8080}"
