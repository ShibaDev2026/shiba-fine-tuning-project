#!/bin/bash
# 安裝 Shiba C.4 週度 E2E 品質 CI 排程（launchd）
# 用法：bash setup_c4_launchd.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$PROJECT_ROOT/com.shiba.ragas-c4.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.shiba.ragas-c4.plist"

# PROJECT_ROOT_PLACEHOLDER 替換成實際路徑
sed "s|PROJECT_ROOT_PLACEHOLDER|$PROJECT_ROOT|g" "$PLIST_SRC" > "$PLIST_DEST"

# 確保 log 目錄存在
mkdir -p "$PROJECT_ROOT/data/logs"

# 載入（若已載入先卸載）
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "✓ C.4 週度 CI 排程已安裝"
echo "  排程：每週日 22:00（本機 timezone）"
echo "  log：$PROJECT_ROOT/data/logs/c4_ci_{stdout,stderr}.log"
echo "  手動觸發測試：launchctl start com.shiba.ragas-c4"
