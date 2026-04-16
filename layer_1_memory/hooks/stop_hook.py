#!/usr/bin/env python3
"""
stop_hook.py — Claude Code Stop Hook（session 結束時觸發）
職責：
1. 從 stdin 讀取 hook payload（session UUID / transcript path）
2. 解析 .jsonl 對話檔
3. 分類事件類型
4. 寫入 SQLite（project / session / branches / messages / FTS5）
5. 背景執行（fire-and-forget），不阻塞 Claude session 結束

Phase 1 直接走 db.py，不透過 HTTP（FastAPI 尚未存在）。
錯誤時寫入 queue 供後續重試（Phase 4 Chamber 啟動後自動補同步）。

安裝方式（~/.claude/settings.json）：
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/stop_hook.py"
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
from datetime import datetime, timezone
from pathlib import Path

# 將 lib/ 加入 sys.path（無論從哪裡執行）
_HOOK_DIR = Path(__file__).parent
_LAYER1_DIR = _HOOK_DIR.parent
sys.path.insert(0, str(_LAYER1_DIR))

import yaml
from lib.classifier import classify_session
from lib.db import (
    deactivate_old_branches,
    get_connection,
    init_db,
    insert_branch_message,
    insert_message,
    upsert_branch,
    upsert_project,
    upsert_session,
    upsert_sessions_fts,
    update_session_stats,
)
from lib.parser import parse_jsonl

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
# Fallback Queue（Chamber 未啟動時的備援）
# ============================================================

def _write_to_queue(payload: dict, config: dict) -> None:
    """
    寫入 fallback queue，Chamber 啟動後自動補同步。
    queue 路徑：~/.local-brain/queue/<session-uuid>.json
    """
    try:
        queue_dir = Path(config["queue"]["path"]).expanduser()
        queue_dir.mkdir(parents=True, exist_ok=True)
        session_uuid = payload.get("session_uuid", "unknown")
        queue_file = queue_dir / f"{session_uuid}.json"
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logging.getLogger(__name__).info("已寫入 fallback queue：%s", queue_file)
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).error("寫入 queue 失敗：%s", e)


# ============================================================
# 核心同步邏輯
# ============================================================

def sync_session(payload: dict, config: dict) -> None:
    """
    解析並寫入 session 資料到 SQLite。
    這是 stop_hook 的主要業務邏輯。
    """
    logger = logging.getLogger(__name__)

    session_uuid = payload.get("session_id") or payload.get("session_uuid")
    transcript_path = payload.get("transcript_path")

    if not session_uuid:
        logger.warning("payload 缺少 session_id，略過")
        return

    # 找到 .jsonl 檔案
    if transcript_path:
        jsonl_path = Path(transcript_path)
    else:
        # 嘗試從 Claude projects 目錄自動尋找
        jsonl_path = _find_jsonl(session_uuid)

    if not jsonl_path or not jsonl_path.exists():
        logger.warning("找不到 jsonl 檔案：session=%s", session_uuid)
        return

    # 解析 .jsonl
    parsed = parse_jsonl(jsonl_path)
    if not parsed:
        logger.warning("jsonl 解析失敗或為空：%s", jsonl_path)
        return

    # 事件分類
    event_types = classify_session(parsed)
    logger.info(
        "session=%s event_types=%s exchanges=%d",
        session_uuid, event_types, parsed.exchange_count,
    )

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        # 1. 確保 project 存在
        project_name = Path(parsed.project_path).name or "unknown"
        project_id = upsert_project(
            conn,
            name=project_name,
            path=parsed.project_path,
            hash_=parsed.project_hash,
        )

        # 2. 確保 session 存在
        session_id = upsert_session(conn, project_id=project_id, uuid=session_uuid)

        # 3. 更新 session 統計
        update_session_stats(
            conn,
            session_id=session_id,
            exchange_count=parsed.exchange_count,
            files_modified=parsed.files_modified,
            commits=parsed.commits,
            tool_counts=parsed.tool_counts,
            event_types=event_types,
            ended_at=now,
        )

        # 4. 寫入所有訊息
        uuid_to_msg_id: dict[str, int] = {}
        for msg in parsed.all_messages:
            msg_id = insert_message(
                conn,
                session_id=session_id,
                uuid=msg.uuid,
                parent_uuid=msg.parent_uuid,
                role=msg.role,
                content=msg.content,
                has_tool_use=msg.has_tool_use,
                tool_names=msg.tool_names,
            )
            uuid_to_msg_id[msg.uuid] = msg_id

        # 5. 寫入 branches（先將舊分支設為非活躍）
        deactivate_old_branches(conn, session_id)

        for branch in parsed.branches:
            branch_id = upsert_branch(
                conn,
                session_id=session_id,
                branch_idx=branch.branch_idx,
                is_active=branch.is_active,
                leaf_uuid=branch.leaf_uuid,
                exchange_count=branch.exchange_count,
                files_modified=len(branch.files_modified),
                commits=branch.commits,
            )
            # 6. 建立 branch-message 橋接
            for seq, msg in enumerate(branch.messages):
                if msg.uuid in uuid_to_msg_id:
                    insert_branch_message(
                        conn,
                        branch_id=branch_id,
                        message_id=uuid_to_msg_id[msg.uuid],
                        seq=seq,
                    )

        # 7. 更新 FTS5 索引
        active_branch = next((b for b in parsed.branches if b.is_active), None)
        content_summary = _build_fts_summary(parsed, active_branch, event_types)
        files_list = ", ".join(active_branch.files_modified) if active_branch else ""

        upsert_sessions_fts(
            conn,
            session_uuid=session_uuid,
            project_path=parsed.project_path,
            event_types=event_types,
            content_summary=content_summary,
            files_list=files_list,
            ended_at=now,
        )

    logger.info("session 同步完成：%s", session_uuid)


def _build_fts_summary(parsed, active_branch, event_types: list[str] | None = None) -> str:
    """
    建立 FTS5 可搜尋的內容摘要（三層來源，確保 tool-heavy session 不再空殼）。
    Layer 1：工具名稱清單（terminal_ops 等 tool-heavy session 的主力）
    Layer 2：文字訊息摘要（一般對話 session）
    Layer 3：最低保底（兩層皆空時，用 event_types + 統計數字填充）
    """
    if not active_branch:
        return ""

    # Layer 1：收集所有 tool_names（最多 50 個，避免超長）
    tool_names: list[str] = []
    for msg in active_branch.messages:
        if msg.has_tool_use and msg.tool_names:
            tool_names.extend(msg.tool_names)
    tool_summary = " ".join(tool_names[:50])

    # Layer 2：文字訊息摘要（保留原有邏輯）
    parts: list[str] = []
    for msg in active_branch.messages[:20]:
        if msg.content:
            parts.append(msg.content[:200])
    text_summary = " ".join(parts)[:1000]

    combined = "\n".join(filter(None, [tool_summary, text_summary]))

    # Layer 3：保底字串，確保 FTS5 不寫入空值
    if not combined.strip():
        project_name = Path(parsed.project_path).name if parsed.project_path else ""
        event_str = " ".join(event_types or [])
        combined = f"{event_str} {parsed.exchange_count} exchanges {project_name}".strip()

    return combined[:1500]


def _find_jsonl(session_uuid: str) -> Path | None:
    """嘗試在 Claude projects 目錄中找到對應的 .jsonl 檔案"""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return None
    for jsonl in claude_dir.rglob(f"{session_uuid}.jsonl"):
        return jsonl
    return None


# ============================================================
# Hook 入口
# ============================================================

def main() -> None:
    """
    Stop Hook 主入口。
    從 stdin 讀取 Claude Code 的 hook payload（JSON）。
    背景執行，不阻塞主流程。
    """
    config = _load_config()
    _setup_logging(config)
    logger = logging.getLogger(__name__)

    try:
        # 讀取 stdin payload
        raw = sys.stdin.read()
        if not raw.strip():
            logger.debug("stop_hook: stdin 為空，略過")
            return

        payload = json.loads(raw)
        logger.info("stop_hook 觸發：%s", json.dumps(payload, ensure_ascii=False)[:200])

        # 初始化 DB（CREATE IF NOT EXISTS，安全重複執行）
        init_db()

        # 同步 session
        sync_session(payload, config)

    except json.JSONDecodeError as e:
        logger.error("payload JSON 解析失敗：%s", e)
        # JSON 錯誤無法建立有效 payload，無法寫 queue
    except Exception as e:  # noqa: BLE001
        logger.error("stop_hook 未預期錯誤：%s\n%s", e, traceback.format_exc())
        # 寫入 fallback queue
        try:
            raw_payload = json.loads(raw) if raw.strip() else {}
            _write_to_queue(raw_payload, config)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
