#!/usr/bin/env bash
set -Eeuo pipefail
: "${BW_GUNICORN_BIND:=0.0.0.0:8080}"
: "${BW_GUNICORN_WORKERS:=2}"
: "${BW_GUNICORN_THREADS:=4}"
: "${BW_GUNICORN_TIMEOUT:=300}"
: "${BW_GUNICORN_GRACEFUL_TIMEOUT:=60}"
: "${BW_GUNICORN_KEEPALIVE:=5}"
: "${BW_GUNICORN_MAX_REQUESTS:=3000}"
: "${BW_GUNICORN_MAX_REQUESTS_JITTER:=300}"
: "${BW_GUNICORN_LOG_LEVEL:=info}"
: "${BW_GUNICORN_WORKER_TMP_DIR:=/dev/shm}"
exec /opt/bw-monitor/venv/bin/gunicorn \
  --chdir /opt/bw-monitor \
  --bind "$BW_GUNICORN_BIND" \
  --workers "$BW_GUNICORN_WORKERS" \
  --worker-class gthread \
  --threads "$BW_GUNICORN_THREADS" \
  --timeout "$BW_GUNICORN_TIMEOUT" \
  --graceful-timeout "$BW_GUNICORN_GRACEFUL_TIMEOUT" \
  --keep-alive "$BW_GUNICORN_KEEPALIVE" \
  --max-requests "$BW_GUNICORN_MAX_REQUESTS" \
  --max-requests-jitter "$BW_GUNICORN_MAX_REQUESTS_JITTER" \
  --access-logfile "${BW_GUNICORN_ACCESS_LOG:--}" \
  --error-logfile "${BW_GUNICORN_ERROR_LOG:--}" \
  --log-level "$BW_GUNICORN_LOG_LEVEL" \
  --worker-tmp-dir "$BW_GUNICORN_WORKER_TMP_DIR" \
  app:app
