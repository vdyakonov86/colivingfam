#!/usr/bin/env bash
set -euo pipefail

# Usage: backup_sqlite.sh /path/to/app.db [/path/to/backup/dir]
# Requires: sqlite3 on the host running the script.
# Keeps backups for 14 days (mtime).

DB_PATH="${1:?Укажите путь к файлу SQLite (например /data/app.db внутри тома)}"
OUT_DIR="${2:-/var/backups/colivingfam-bot}"

mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
OUT_FILE="${OUT_DIR}/app-${TS}.db"

sqlite3 "$DB_PATH" ".backup ${OUT_FILE}"
echo "Backup written to ${OUT_FILE}"

find "$OUT_DIR" -type f -name 'app-*.db' -mtime +14 -print -delete 2>/dev/null || true
