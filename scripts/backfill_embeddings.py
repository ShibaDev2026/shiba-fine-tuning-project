#!/usr/bin/env python3
"""
backfill_embeddings.py — 補齊 exchange_embeddings 歷史覆蓋率

找出尚無任何 embedding 的 session，從 exchanges 重建指令對並生成向量。
指令內容以 tool_names 作為 proxy（原始 bash 指令已不可重建，不影響向量搜尋品質）。

用法：
    python scripts/backfill_embeddings.py [--dry-run] [--batch 20] [--delay 0.1]
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 讓 root 層可被 import
sys.path.insert(0, str(Path(__file__).parent.parent))

from shiba_db import open_connection
from layer_1_memory.lib.embedder import get_embedding


def fetch_uncovered_sessions(conn) -> list[str]:
    """回傳尚無任何 embedding 的 session uuid 清單"""
    rows = conn.execute("""
        SELECT DISTINCT s.uuid
        FROM sessions s
        JOIN exchanges e ON e.session_id = s.id
        WHERE e.has_tool_use = 1
          AND e.has_final_text = 1
          AND e.has_error = 0
          AND e.user_text_preview IS NOT NULL
          AND s.uuid NOT IN (SELECT DISTINCT session_uuid FROM exchange_embeddings)
        ORDER BY s.id DESC
    """).fetchall()
    return [r[0] for r in rows]


def fetch_exchanges_for_session(conn, session_uuid: str) -> list[dict]:
    """取得指定 session 中有工具執行的 exchange 列表"""
    rows = conn.execute("""
        SELECT e.user_text_preview, e.tool_names
        FROM exchanges e
        JOIN sessions s ON s.id = e.session_id
        WHERE s.uuid = ?
          AND e.has_tool_use = 1
          AND e.has_final_text = 1
          AND e.has_error = 0
          AND e.user_text_preview IS NOT NULL
        ORDER BY e.id
    """, (session_uuid,)).fetchall()
    return [{"instruction": r[0], "tool_names": r[1]} for r in rows]


def format_commands(tool_names_json: str) -> str:
    """把 tool_names JSON 陣列格式化成可讀字串"""
    try:
        names = json.loads(tool_names_json or "[]")
        return ", ".join(names) if names else "unknown"
    except Exception:
        return tool_names_json or "unknown"


def backfill(dry_run: bool = False, batch_size: int = 20, delay: float = 0.1):
    conn = open_connection("writer")
    try:
        sessions = fetch_uncovered_sessions(conn)
        total_sessions = len(sessions)
        print(f"找到 {total_sessions} 個 session 尚未有 embedding")

        if dry_run:
            for uuid in sessions[:5]:
                exs = fetch_exchanges_for_session(conn, uuid)
                print(f"  {uuid[:8]}… → {len(exs)} exchanges")
            print("[dry-run] 結束，未寫入任何資料")
            return

        inserted = 0
        skipped = 0
        failed = 0

        for s_idx, session_uuid in enumerate(sessions):
            exchanges = fetch_exchanges_for_session(conn, session_uuid)
            session_inserted = 0

            target = exchanges[:batch_size] if batch_size > 0 else exchanges
            for ex in target:
                instruction = ex["instruction"][:300].strip()
                if not instruction:
                    skipped += 1
                    continue

                vec = get_embedding(instruction)
                if vec is None:
                    print(f"  [警告] Ollama 離線，session {session_uuid[:8]} 中止")
                    failed += 1
                    continue

                commands = format_commands(ex["tool_names"])
                conn.execute(
                    """INSERT INTO exchange_embeddings
                       (session_uuid, instruction, source_instruction, commands, embedding, model)
                       VALUES (?, ?, NULL, ?, ?, 'nomic-embed-text')""",
                    (session_uuid, instruction, commands, json.dumps(vec)),
                )
                session_inserted += 1
                inserted += 1

                if delay > 0:
                    time.sleep(delay)

            conn.commit()

            if s_idx % 10 == 0 or s_idx == total_sessions - 1:
                print(
                    f"  [{s_idx + 1}/{total_sessions}] session {session_uuid[:8]}… "
                    f"+{session_inserted} | 累計 inserted={inserted} failed={failed}"
                )

        print(f"\n完成：inserted={inserted}, skipped={skipped}, failed={failed}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill exchange_embeddings")
    parser.add_argument("--dry-run", action="store_true", help="只印出統計，不寫入")
    parser.add_argument("--batch", type=int, default=0, help="每 session 最多處理幾筆（0=不限，預設 0）")
    parser.add_argument("--delay", type=float, default=0.1, help="每次 embed 間隔秒數（預設 0.1）")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, batch_size=args.batch, delay=args.delay)
