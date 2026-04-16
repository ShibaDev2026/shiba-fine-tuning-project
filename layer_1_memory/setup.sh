#!/bin/bash
# layer_1_memory/setup.sh
# 換機或重設環境時，一鍵部署 Layer 1 記憶層

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$HOME/.local-brain/venv"
BRAIN_DIR="$HOME/.local-brain"
SETTINGS="$HOME/.claude/settings.json"

echo "==> 建立資料目錄"
mkdir -p "$BRAIN_DIR/logs" "$BRAIN_DIR/queue"

echo "==> 建立 Python venv：$VENV_DIR"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
echo "    依賴安裝完成"

echo "==> 初始化 SQLite schema"
"$VENV_DIR/bin/python3" - <<PYEOF
import sys
sys.path.insert(0, "$SCRIPT_DIR")
from lib.db import init_db
init_db()
print("    DB 初始化完成")
PYEOF

echo "==> 更新 ~/.claude/settings.json hooks"
"$VENV_DIR/bin/python3" - <<PYEOF
import json, sys
from pathlib import Path

settings_path = Path("$SETTINGS")
settings = {}
if settings_path.exists():
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        pass

# 定義目標 hooks（以絕對路徑指向本專案）
stop_cmd = "$VENV_DIR/bin/python3 $SCRIPT_DIR/hooks/stop_hook.py"
start_cmd = "$VENV_DIR/bin/python3 $SCRIPT_DIR/hooks/session_start_hook.py"

new_hooks = {
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": stop_cmd}]}],
    "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command", "command": start_cmd}]}],
}

# 合併：保留現有其他 hook，覆寫 Stop / UserPromptSubmit
existing = settings.get("hooks", {})
for event, config in new_hooks.items():
    existing[event] = config
settings["hooks"] = existing

settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("    hooks 已寫入 settings.json")
PYEOF

echo ""
echo "✅ Layer 1 記憶層部署完成"
echo "   venv：$VENV_DIR"
echo "   DB  ：$BRAIN_DIR/shiba-brain.db"
echo "   Log ：$BRAIN_DIR/logs/memory.log"
echo ""
echo "下一步：重啟 Claude Code 讓 hooks 生效"
