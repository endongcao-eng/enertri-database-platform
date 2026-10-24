#!/usr/bin/env bash
set -Eeuo pipefail

# Railway's trial topology intentionally keeps web and the database worker in
# one service so they can share one persistent volume. Start migrations via
# railway.json's preDeployCommand, never from FastAPI startup.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

worker_pid=""
web_pid=""

shutdown() {
  set +e
  [[ -n "$web_pid" ]] && kill -TERM "$web_pid" 2>/dev/null || true
  [[ -n "$worker_pid" ]] && kill -TERM "$worker_pid" 2>/dev/null || true
}
trap shutdown TERM INT EXIT

python scripts/task_worker.py &
worker_pid=$!

gunicorn \
  -k uvicorn.workers.UvicornWorker \
  -w "${WEB_CONCURRENCY:-2}" \
  -b "0.0.0.0:${PORT:-8000}" \
  app.main:app &
web_pid=$!

set +e
wait -n "$worker_pid" "$web_pid"
status=$?
set -e
shutdown
wait "$worker_pid" 2>/dev/null || true
wait "$web_pid" 2>/dev/null || true
exit "$status"
