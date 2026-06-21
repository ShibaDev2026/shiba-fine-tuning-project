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
from lib.rag import (
    get_rag_context_with_hits,
    is_low_signal_query,
    is_short_query,
    is_system_meta_query,
)

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
    # UserPromptSubmit hook 含 prompt 欄位：只要欄位存在就一律用真實 prompt。
    # 不再用長度門檻擋短 prompt——短的同意詞（如「不用」）由 is_low_signal_query
    # 在查詢側資料驅動判斷，不該在這裡被偷換成專案名（曾導致「不用」→ 專案名亂查）。
    if "prompt" in payload:
        # 取前 150 字元作為查詢（避免過長）；空字串照樣回空，呼叫端會跳過召回
        return (payload.get("prompt") or "").strip()[:150]

    # 無 prompt 欄位的其他 hook（PreToolUse 等）才 fallback 用 project path 目錄名
    project_path = payload.get("cwd") or payload.get("projectPath") or ""
    if project_path:
        return Path(project_path).name

    return ""


def get_project_path(payload: dict) -> str | None:
    """從 payload 取得 project 路徑（用於 FTS5 同專案優先）"""
    return payload.get("cwd") or payload.get("projectPath") or None


# ============================================================
# Echo 寫檔（使用者側邊 `tail -F` 可見、不進 Claude context）
# ============================================================

def _write_echo_file(
    echo_path: Path,
    combined: str,
    router_context: str | None,
    rag_source: str,
    count: int,
) -> None:
    """把召回內容「覆寫」到 echo 檔，供使用者側邊 `tail -F` 查看。

    取代舊的 stderr echo：Claude Code 2.x 起 exit-0 hook 的 stderr 只進 debug log、
    正常 UI 與 transcript 皆不顯示（官方 hooks 文件），stderr 通道對使用者已死。
    改寫檔這條不依賴 Claude Code UI、跨改版穩定。

    覆寫（非追加）：每次 prompt 只保留最新一筆召回，避免檔案無限長大；使用者用
    `tail -F`（大寫 F，截斷/重建時自動重開）跟看。
    side-effect only：任何寫檔失敗都不得冒泡，否則會連坐丟失 main() 的 stdout 契約。
    """
    try:
        from datetime import datetime

        # caller 已確保至少一邊有內容（或無召回時顯式傳 none/0）
        parts = []
        if router_context:
            parts.append("router")
        if rag_source != "none":
            parts.append(f"rag={rag_source}")
        source_label = "+".join(parts) or "none"

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 首行寫機器可讀 metadata（statusLine 解析 rag_count）；其後為人類可讀區塊。
        # 用 rstrip("\n") 而非 rstrip()，保留 markdown 內可能有意義的尾隨空白。
        block = (
            f"<!-- rag_count={count} source={source_label} ts={ts} -->\n"
            f"[=== 本地RAG召回：{source_label} @ {ts} ===]\n"
            f"{combined.rstrip(chr(10))}\n"
            f"[=== END ===]\n"
        )
        echo_path.parent.mkdir(parents=True, exist_ok=True)
        echo_path.write_text(block, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        # echo 寫檔失敗不得影響主流程；只在 file logger 留痕
        logging.getLogger(__name__).warning("echo 寫檔失敗：%s", exc)


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

        # 查詢側結構性 gate（最前、零 DB）：harness/remember 外掛 spawn 的系統 prompt
        # （daily 摘要 / 壓縮 / 子任務通知 / context 續接）非 Shiba 查詢，一刀攔下——
        # 不召回、不寫 log、不通知、不寫 pending（杜絕孤兒 pending 的主要來源）。
        if is_system_meta_query(query):
            logger.debug("session_start_hook: query 判定為系統 prompt，略過 RAG/log/notify")
            print(empty_output)
            return

        # 查詢側最短長度閘（結構性、零 DB，置於 divergence gate 之前）：過短 query
        # （控制詞/決策選項/步驟碎片）召回價值低，且 is_low_signal_query 的 divergence
        # 啟發式對一致性控制詞永遠到不了閾值。與 ingestion 門檻對稱。
        # ⚠ 「零功能損失」前提＝feed_model=false（recall 只進 audit、不餵 Claude）。本閘
        #   位於 feed_model 讀取之前、無條件跳過召回；且比另兩個 gate 鈍——也會擋短但
        #   有意義的 query（如「D4 是什麼」「bge-m3 維度?」）。若回滾 feed_model=true，
        #   這些短 query 會靜默失去 RAG augmentation → 屆時需把本閘改為 feed_model-aware。
        if is_short_query(query):
            logger.debug("session_start_hook: query 過短，略過 RAG/log/notify")
            print(empty_output)
            return

        # 查詢側資料驅動 gate：已學會的同意詞（高發散、無指向性）直接跳過——
        # vector / FTS5 兩條路都不走，亦不寫 recall_log、不彈通知（資料驅動、累積後學）。
        if is_low_signal_query(query):
            logger.debug("session_start_hook: query 判定為同意詞，略過 RAG/log/notify")
            print(empty_output)
            return

        project_path = get_project_path(payload)

        # 讀取 RAG 設定
        rag_config = config.get("rag", {})
        top_n = rag_config.get("top_n", 3)
        token_budget = rag_config.get("token_budget", 500)
        # echo 寫檔開關 + 目標路徑（相對專案根；絕對路徑也可，Path 自動處理）
        echo_to_file = bool(rag_config.get("echo_to_file", False))
        echo_path = (
            _PROJECT_ROOT / rag_config.get("echo_file", ".remember/rag_echo.md")
        ).resolve()
        # Option 3（2026-06-20）：預設不把本地召回/路由結果注入 Claude context，
        # 改 echo 給使用者參考；feed_model=true 才回復舊的注入行為（可回滾）。
        feed_model = bool(rag_config.get("feed_model", False))
        # recall_log（每日 append 稽核日誌）+ macOS 通知開關
        recall_log_enabled = bool(rag_config.get("recall_log", False))
        recall_log_dir = (
            _PROJECT_ROOT / rag_config.get("recall_log_dir", "recall_logs")
        ).resolve()
        recall_log_retention_days = int(rag_config.get("recall_log_retention_days", 30))
        notify_macos = bool(rag_config.get("notify_macos", False))

        # 執行 RAG 檢索（with_hits：額外回結構化 hits 供 recall_log 記「召回原因」）
        memory_context, rag_source, hits = get_rag_context_with_hits(
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
        session_id = payload.get("session_id", "")
        # 「有召回」＝memory 真的撈到（len(hits)>0）；Layer 0 router 草擬單獨存在不算。
        mem_count = len(hits)
        has_recall = mem_count > 0

        # --- stdout 契約：feed_model 決定是否注入 model（基於 combined_context，含 router）---
        # stdout 無論如何都須輸出恰好一個合法 JSON。
        if combined_context and feed_model:
            router_label = "local" if router_context else "rag-only"
            logger.info(
                "context injected %d 字元（session=%s，router=%s）",
                len(combined_context), session_id, router_label,
            )
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": combined_context,
                }
            }
            print(json.dumps(output, ensure_ascii=False))
        else:
            if combined_context:
                logger.info(
                    "context withheld from model（feed_model=false）%d 字元 → 使用者通道（session=%s）",
                    len(combined_context), session_id,
                )
            print(empty_output)
        sys.stdout.flush()

        # --- 使用者通道：echo / recall_log / notify。scrub 一次共用；不可用→fail-closed ---
        scrub_fn = None
        try:
            from layer_2_chamber.backend.services.grading_harness import (
                scrub_for_export,
            )
            scrub_fn = scrub_for_export
        except Exception as exc:  # noqa: BLE001
            logger.warning("scrub 不可用，fail-closed 跳過 echo / recall_log：%s", exc)

        if has_recall:
            # echo：覆寫最新召回，給使用者 `tail -F` + statusLine 解析 rag_count
            if echo_to_file and scrub_fn:
                safe_context = scrub_fn(combined_context)
                if safe_context:
                    _write_echo_file(
                        echo_path, safe_context, router_context, rag_source, mem_count
                    )
            # recall_log：append cause + 寫 pending（供 Stop hook 補回答）
            if recall_log_enabled and scrub_fn:
                from lib.recall_log import append_cause
                append_cause(
                    recall_log_dir, session_id, query, rag_source, hits,
                    scrub=scrub_fn, retention_days=recall_log_retention_days,
                )
            # macOS 通知（side-effect only，失敗不冒泡）
            # 格式：標題「yyyy/MM/dd HH:mm RAG 召回次數:N次」、內文＝議題（問題，截 40 字）
            if notify_macos:
                from datetime import datetime
                from lib.notify import macos_notify
                topic = scrub_fn(query) if scrub_fn else query
                if len(topic) > 40:
                    topic = topic[:40] + "…"
                title = f"{datetime.now():%Y/%m/%d %H:%M} RAG 召回次數:{mem_count}次"
                macos_notify(title, topic)
        else:
            # 無召回：echo 歸零（維持 statusLine 即時歸 0），不寫 recall_log、不通知
            logger.debug("無召回（mem_count=0），echo 歸零")
            if echo_to_file:
                _write_echo_file(echo_path, "（本次無召回）", None, "none", 0)

    except json.JSONDecodeError as e:
        logger.error("payload JSON 解析失敗：%s", e)
        print(empty_output)
    except Exception as e:  # noqa: BLE001
        logger.error("session_start_hook 未預期錯誤：%s\n%s", e, traceback.format_exc())
        print(empty_output)


if __name__ == "__main__":
    main()
