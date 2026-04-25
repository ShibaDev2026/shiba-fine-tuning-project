#!/usr/bin/env bash
# setup_layer3_launchd.sh
# 安裝 Layer 3 launchd 服務（host 常駐）
# 用法：bash setup_layer3_launchd.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="${SCRIPT_DIR}/com.shiba.layer3.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/com.shiba.layer3.plist"
LABEL="com.shiba.layer3"

# 確認 python3 可找到 uvicorn（專案 venv 或系統 pip install）
if ! python3 -c "import uvicorn" 2>/dev/null; then
    echo "ERROR：找不到 uvicorn，請先執行 pip install uvicorn fastapi"
    exit 1
fi

# 確認 logs 目錄存在
mkdir -p "${SCRIPT_DIR}/data/logs"

# 將 plist 的 PROJECT_ROOT_PLACEHOLDER 替換為真實路徑
sed "s|PROJECT_ROOT_PLACEHOLDER|${SCRIPT_DIR}|g" "${PLIST_SRC}" > "${PLIST_DEST}"

# 替換 python3 路徑為 which python3 的結果
PYTHON3_PATH="$(which python3)"
sed -i '' "s|/opt/homebrew/opt/python@3.14/bin/python3|${PYTHON3_PATH}|g" "${PLIST_DEST}"

echo "已安裝 plist → ${PLIST_DEST}"

# 若已載入則先 unload
if launchctl list | grep -q "${LABEL}"; then
    launchctl unload "${PLIST_DEST}" 2>/dev/null || true
    echo "已 unload 舊服務"
fi

launchctl load "${PLIST_DEST}"
echo "Layer 3 服務已啟動"

sleep 1
echo "健康檢查："
curl -sf http://127.0.0.1:8001/health && echo "" || echo "WARNING：服務尚未就緒，請稍後再試 curl http://127.0.0.1:8001/health"
