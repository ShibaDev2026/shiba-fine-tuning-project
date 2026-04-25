#!/usr/bin/env bash
# db_backup.sh — SQLite 備份（.backup 指令確保 WAL 一致性）
# 路徑從 config/shiba.yaml 讀（使用 grep + sed，不依賴 python 環境）
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YAML="${PROJECT_ROOT}/config/shiba.yaml"

# 取相對路徑欄位並展開為絕對路徑
_rel_db=$(grep '^\s*db:' "$YAML" | head -1 | sed 's/.*db:[[:space:]]*//' | cut -d'#' -f1 | xargs)
_rel_bk=$(grep '^\s*backups_dir:' "$YAML" | head -1 | sed 's/.*backups_dir:[[:space:]]*//' | cut -d'#' -f1 | xargs)

DB="${PROJECT_ROOT}/${_rel_db}"
OUT_DIR="${PROJECT_ROOT}/${_rel_bk}"

mkdir -p "$OUT_DIR"
TS=$(date +%Y%m%d_%H%M%S)
DEST="${OUT_DIR}/shiba-brain-${TS}.db"

sqlite3 "$DB" ".backup '${DEST}'"
echo "備份完成：${DEST}"
