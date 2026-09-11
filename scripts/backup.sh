#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "[1/2] Backing up PostgreSQL..."
docker compose exec -T db pg_dump -U enertri_user -d enertri > "$BACKUP_DIR/enertri_${STAMP}.sql"

echo "[2/2] Backing up uploads..."
tar -czf "$BACKUP_DIR/uploads_${STAMP}.tar.gz" uploads

echo "Backup completed: $BACKUP_DIR"
