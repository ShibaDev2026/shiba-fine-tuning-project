#!/usr/bin/env bash
# setup_launchd.sh — 建立並載入 Layer 2 FastAPI LaunchD 常駐服務
# 用途：讓 APScheduler 在背景持續執行（避免評分任務因服務未啟動而停滯）
set -euo pipefail

LABEL="com.shiba.layer2"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_PATH="$HOME/.local-brain/layer2.log"
WORK_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON_BIN="$(which python3)"

mkdir -p "$HOME/.local-brain"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>layer_2_chamber.backend.main:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8000</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${WORK_DIR}</string>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_PATH}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_FLASH_ATTENTION</key>
        <string>1</string>
        <key>OLLAMA_MAX_LOADED_MODELS</key>
        <string>1</string>
        <key>OLLAMA_KV_CACHE_TYPE</key>
        <string>q8_0</string>
        <key>OLLAMA_KEEP_ALIVE</key>
        <string>10m</string>
    </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "✓ LaunchD 服務已建立並載入：${LABEL}"
echo "  plist：${PLIST}"
echo "  log  ：${LOG_PATH}"
echo "  查看 ：launchctl print gui/$(id -u)/${LABEL}"
echo "  停止 ：launchctl bootout gui/$(id -u)/${LABEL}"
