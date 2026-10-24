#!/usr/bin/env bash
set -euo pipefail
if [ $# -lt 1 ]; then
  echo "Usage: ./scripts/restore_db.sh backups/enertri_YYYYMMDD_HHMMSS.sql"
  exit 1
fi
SQL_FILE="$1"
if [ ! -f "$SQL_FILE" ]; then
  echo "File not found: $SQL_FILE"
  exit 1
fi
cat "$SQL_FILE" | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U enertri_user -d enertri
