#!/usr/bin/env bash
# setup_layer3_launchd.sh
# 安裝 Layer 3 launchd 服務（host 常駐）
# 用法：bash setup_layer3_launchd.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="${SCRIPT_DIR}/com.shiba.layer3.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/com.shiba.layer3.plist"
LABEL="com.shiba.layer3"

# 找有 uvicorn 的 python：優先用 ~/.local-brain/venv（layer 2/3 共用 venv），其次 which python3
if [ -x "${HOME}/.local-brain/venv/bin/python" ] && "${HOME}/.local-brain/venv/bin/python" -c "import uvicorn" 2>/dev/null; then
    PYTHON3_PATH="${HOME}/.local-brain/venv/bin/python"
elif python3 -c "import uvicorn" 2>/dev/null; then
    PYTHON3_PATH="$(which python3)"
else
    echo "ERROR：找不到含 uvicorn 的 python，請先執行："
    echo "  ${HOME}/.local-brain/venv/bin/pip install uvicorn fastapi pyyaml"
    exit 1
fi
echo "使用 Python：${PYTHON3_PATH}"

# 確認 logs 目錄存在
mkdir -p "${SCRIPT_DIR}/data/logs"

# 將 plist 的 PROJECT_ROOT_PLACEHOLDER 替換為真實路徑，同時換入正確 python 路徑
sed "s|PROJECT_ROOT_PLACEHOLDER|${SCRIPT_DIR}|g; s|/opt/homebrew/opt/python@3.14/bin/python3|${PYTHON3_PATH}|g" \
    "${PLIST_SRC}" > "${PLIST_DEST}"

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
