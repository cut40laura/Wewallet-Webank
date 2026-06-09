#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/runtime/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
mkdir -p "$ROOT/runtime/app_data" "$ROOT/runtime/ui_data"

tar -czf "$BACKUP_DIR/wewallet-data-$STAMP.tar.gz" \
  -C "$ROOT" \
  runtime/app_data \
  runtime/ui_data

find "$BACKUP_DIR" -name 'wewallet-data-*.tar.gz' -mtime +"$RETENTION_DAYS" -delete

echo "$BACKUP_DIR/wewallet-data-$STAMP.tar.gz"
