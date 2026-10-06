#!/bin/sh
# Single uvicorn process: the job queue and SQLite assume exactly one process.
set -eu
alembic upgrade head
# Set IRIS_FORWARDED_ALLOW_IPS to your reverse proxy's IP so the login limiter sees real client IPs.
exec uvicorn app.main:app --host 0.0.0.0 --port "${IRIS_PORT:-8080}" \
  --proxy-headers --forwarded-allow-ips "${IRIS_FORWARDED_ALLOW_IPS:-127.0.0.1}"
