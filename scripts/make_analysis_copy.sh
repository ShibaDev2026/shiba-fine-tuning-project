#!/usr/bin/env bash
# make_analysis_copy.sh — 產生供 DBeaver 分析用的隔離副本
# 用法：bash scripts/make_analysis_copy.sh
# 副本路徑：data/shiba-brain-analysis.db（每次執行覆蓋舊檔）
# DBeaver 請連副本，不要連 data/shiba-brain.db（生產 DB）

set -e
cd "$(dirname "$0")/.."

PROD_DB="data/shiba-brain.db"
COPY_DB="data/shiba-brain-analysis.db"

echo "建立分析副本中…"
# VACUUM INTO：WAL 完整 checkpoint 後複製，產出的副本是乾淨的單一檔案（無 WAL/SHM）
sqlite3 "$PROD_DB" "VACUUM INTO '$COPY_DB'"
SIZE=$(du -sh "$COPY_DB" | cut -f1)
echo "完成：$COPY_DB（$SIZE）"
echo "在 DBeaver 請開啟此副本，不要連線 $PROD_DB"
