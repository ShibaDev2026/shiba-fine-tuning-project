#!/usr/bin/env python3
"""
session_start_hook.py — Claude Code SessionStart Hook（新 session 開始時觸發）
職責：
1. 從 stdin 讀取 hook payload（session UUID / project path）
2. 從 FTS5 檢索最相關的歷史記憶（top-3）
3. 輸出 hookSpecificOutput JSON（注入 context）

輸出格式（符合 Claude Code UserPromptSubmit Hook 規範）：
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## 相關歷史記憶（top 3）\n..."
  }
}

若無相關記憶或 DB 尚未初始化，輸出空物件 {}（hookSpecificOutput 一旦存在即強制要求 hookEventName）。

安裝方式（~/.claude/settings.json）：
{
  "hooks": {
    "PreToolUse": [...],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/session_start_hook.py"
          }
        ]
      }
    ]
  }
}
"""

import json
import logging
import sys
import traceback
from pathlib import Path

# 將 lib/ 加入 sys.path
_HOOK_DIR = Path(__file__).parent
_LAYER1_DIR = _HOOK_DIR.parent
sys.path.insert(0, str(_LAYER1_DIR))

import yaml
from lib.db import init_db
from lib.rag import get_rag_context

# ============================================================
# 設定
# ============================================================

_CONFIG_PATH = _LAYER1_DIR / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _setup_logging(config: dict) -> None:
    """初始化 file logger"""
    log_path = Path(config["logging"]["path"]).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ============================================================
# RAG 查詢邏輯
# ============================================================

def build_rag_query(payload: dict) -> str:
    """
    從 hook payload 建立 FTS5 查詢字串。
    優先使用 user prompt 內容；fallback 用 project name。
    """
    # UserPromptSubmit hook 含 prompt 欄位
    prompt = payload.get("prompt", "")
    if prompt and len(prompt.strip()) >= 3:
        # 取前 150 字元作為查詢（避免過長）
        return prompt.strip()[:150]

    # 其他 hook（PreToolUse 等）用 project path 的目錄名
    project_path = payload.get("cwd") or payload.get("projectPath") or ""
    if project_path:
        return Path(project_path).name

    return ""


def get_project_path(payload: dict) -> str | None:
    """從 payload 取得 project 路徑（用於 FTS5 同專案優先）"""
    return payload.get("cwd") or payload.get("projectPath") or None


# ============================================================
# Hook 入口
# ============================================================

def main() -> None:
    """
    SessionStart Hook 主入口。
    從 stdin 讀取 payload，輸出 hookSpecificOutput 到 stdout。
    """
    config = _load_config()
    _setup_logging(config)
    logger = logging.getLogger(__name__)

    # 預設輸出（無記憶時回傳空物件，避免 hookSpecificOutput 缺 hookEventName 觸發驗證錯誤）
    empty_output = "{}"

    try:
        # 讀取 stdin payload
        raw = sys.stdin.read()
        if not raw.strip():
            print(empty_output)
            return

        payload = json.loads(raw)
        logger.info("session_start_hook 觸發：session=%s", payload.get("session_id", ""))

        # 確保 DB 已初始化（session_start 可能先於 stop_hook 完成）
        try:
            init_db()
        except Exception as e:  # noqa: BLE001
            logger.warning("DB 初始化失敗（無害，繼續）：%s", e)

        # 建立查詢
        query = build_rag_query(payload)
        if not query:
            logger.debug("session_start_hook: 無有效 query，略過 RAG")
            print(empty_output)
            return

        project_path = get_project_path(payload)

        # 讀取 RAG 設定
        rag_config = config.get("rag", {})
        top_n = rag_config.get("top_n", 3)
        token_budget = rag_config.get("token_budget", 500)

        # 執行 RAG 檢索
        memory_context = get_rag_context(
            query=query,
            project_path=project_path,
            top_n=top_n,
            token_budget=token_budget,
        )

        if memory_context:
            logger.info(
                "RAG 注入 %d 字元（session=%s）",
                len(memory_context),
                payload.get("session_id", ""),
            )
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": memory_context,
                }
            }
            print(json.dumps(output, ensure_ascii=False))
        else:
            logger.debug("RAG 無相關記憶，輸出空物件")
            print(empty_output)

    except json.JSONDecodeError as e:
        logger.error("payload JSON 解析失敗：%s", e)
        print(empty_output)
    except Exception as e:  # noqa: BLE001
        logger.error("session_start_hook 未預期錯誤：%s\n%s", e, traceback.format_exc())
        print(empty_output)


if __name__ == "__main__":
    main()
