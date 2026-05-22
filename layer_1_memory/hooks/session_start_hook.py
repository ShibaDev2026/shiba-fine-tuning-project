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
import os
import sys
import traceback
from pathlib import Path

# 將 lib/ 與專案根加入 sys.path
_HOOK_DIR = Path(__file__).parent
_LAYER1_DIR = _HOOK_DIR.parent

# 專案根：優先讀 SHIBA_PROJECT_ROOT env（hook 若被複製到 plugin 目錄，
# 只有 env 能指回真正的專案根）；未設時 fallback 到 _LAYER1_DIR.parent。
_PROJECT_ROOT = Path(
    os.environ.get("SHIBA_PROJECT_ROOT", str(_LAYER1_DIR.parent))
).resolve()

sys.path.insert(0, str(_LAYER1_DIR))
sys.path.insert(0, str(_PROJECT_ROOT))

import yaml
from shiba_config import CONFIG
from lib.db import init_db
from lib.rag import get_rag_context

# ============================================================
# 設定
# ============================================================

# config 必須跟 _PROJECT_ROOT 對齊 — 否則 hook 被複製到 plugin 目錄時，
# 即使 SHIBA_PROJECT_ROOT 指回真專案根，這條 path 還是會落在 plugin 副本的
# config.yaml 上，使用者改 repo config 的新欄位完全失效。
_CONFIG_PATH = _PROJECT_ROOT / "layer_1_memory" / "config.yaml"


def _load_config() -> dict:
    """讀 Layer 1 專屬邏輯參數（rag / decay / event_importance / logging.level）。

    路徑（DB / logs / queue）不在此檔，由 shiba_config.CONFIG 提供。
    """
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _setup_logging(config: dict) -> None:
    """初始化 file logger — log 檔路徑來自 CONFIG.paths.logs_dir"""
    log_path = CONFIG.paths.logs_dir / "memory.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level_name = (config.get("logging") or {}).get("level", "INFO")
    logging.basicConfig(
        filename=str(log_path),
        level=getattr(logging, level_name, logging.INFO),
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
# Debug echo（stderr 區塊，使用者可見、不進 Claude context）
# ============================================================

_ANSI_HEADER = "\033[1;36m"  # 粗體青
_ANSI_LABEL = "\033[1;33m"   # 粗體黃
_ANSI_RESET = "\033[0m"


def _infer_rag_source(memory_context: str | None) -> str:
    """從 memory_context 內容判斷召回路徑（vector / fts5 / none）"""
    if not memory_context:
        return "none"
    # _build_exchange_context 的 vector 路徑用「### 問題：」
    if "### 問題：" in memory_context:
        return "vector"
    # build_rag_output 的 FTS5 路徑用「### [」
    if "### [" in memory_context:
        return "fts5"
    return "unknown"


def _echo_to_stderr(
    combined: str,
    router_context: str | None,
    memory_context: str | None,
) -> None:
    """把召回內容以 ANSI 區塊寫到 stderr（exit 0，僅顯示給使用者）。

    side-effect only：任何 stderr 寫入失敗（BrokenPipe / 編碼錯誤）都不得
    冒泡，否則會把 main() 已備好的 additionalContext 一起連坐丟失。
    """
    try:
        rag_source = _infer_rag_source(memory_context)
        parts = []
        if router_context:
            parts.append("router")
        if memory_context:
            parts.append(f"rag={rag_source}")
        source_label = "+".join(parts) if parts else "empty"

        # 非 TTY（pipe / log file / SSH 無 TTY / CI）或 NO_COLOR 環境跳過色碼，
        # 否則使用者會在 transcript 看到 literal "\033[1;36m..." 雜訊
        use_color = sys.stderr.isatty() and not os.environ.get("NO_COLOR")
        header = "\033[1;36m" if use_color else ""
        reset = "\033[0m" if use_color else ""

        # 三段內容組成單一字串、一次 write — 避免並發 hook 進程下三段
        # syscall 交錯 + 終端機殘留色彩
        block = (
            f"{header}[=== 本地RAG召回：{source_label} ==={reset}\n"
            f"{combined.rstrip()}\n"
            f"{header}[=== END ==={reset}\n"
        )
        # 用 .buffer.write 強制 utf-8 + 'replace' 容錯，避免 ASCII stderr
        # 環境（LANG=C / launchd / CI runner）遇到中文或 emoji 拋 UnicodeEncodeError
        sys.stderr.buffer.write(block.encode("utf-8", errors="replace"))
        sys.stderr.buffer.flush()
    except Exception as exc:  # noqa: BLE001
        # debug echo 失敗不得影響主流程；只在 file logger 留痕
        logging.getLogger(__name__).warning("debug_echo 寫入 stderr 失敗：%s", exc)


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

        # 確保 DB 已初始化（session_start 可能先於 session_stop_hook 完成）
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
        debug_echo = bool(rag_config.get("debug_echo", False))

        # 執行 RAG 檢索
        memory_context = get_rag_context(
            query=query,
            project_path=project_path,
            top_n=top_n,
            token_budget=token_budget,
        )

        # 嘗試 Layer 0 路由（Ollama 離線時靜默跳過）
        router_context = None
        try:
            from layer_0_router.router import route
            router_context = route(
                prompt=query,
                rag_context=memory_context or "",
                session_id=payload.get("session_id"),
            )
        except Exception as e:
            logger.warning("Layer 0 router 失敗，跳過：%s", e)

        # 合併 router 建議 + RAG 記憶
        parts = []
        if router_context:
            parts.append(router_context)
        if memory_context:
            parts.append(memory_context)

        combined_context = "\n\n".join(parts) if parts else ""

        if combined_context:
            session_id = payload.get("session_id", "")
            router_label = "local" if router_context else "rag-only"
            logger.info(
                "context prepared %d 字元（session=%s，router=%s）",
                len(combined_context),
                session_id,
                router_label,
            )
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": combined_context,
                }
            }
            # 先保證主契約 stdout JSON 落地，再做 best-effort stderr echo；
            # 避免 echo blocking / 例外連坐毀掉 additionalContext。
            print(json.dumps(output, ensure_ascii=False))
            sys.stdout.flush()
            logger.info("context emitted（session=%s）", session_id)

            # debug_echo：把召回內容以 ANSI 色塊寫到 stderr，只給使用者看
            # （Claude Code 對 exit 0 的 stderr 不會回灌 model context，不計 token）
            if debug_echo:
                _echo_to_stderr(combined_context, router_context, memory_context)
        else:
            logger.debug("無 context，輸出空物件")
            print(empty_output)

    except json.JSONDecodeError as e:
        logger.error("payload JSON 解析失敗：%s", e)
        print(empty_output)
    except Exception as e:  # noqa: BLE001
        logger.error("session_start_hook 未預期錯誤：%s\n%s", e, traceback.format_exc())
        print(empty_output)


if __name__ == "__main__":
    main()
