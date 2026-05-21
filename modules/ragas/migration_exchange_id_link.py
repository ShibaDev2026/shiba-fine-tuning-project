"""幂等 migration：exchange_embeddings 補 exchange_id 外鍵 + backfill 對碰 exchanges。

目的：
  原本 exchange_embeddings 只記錄 (session_uuid, instruction, commands, embedding)，
  召回後拿不到所屬 exchange 在 branch 內的位置（exchange_idx），
  無法做「鄰居 ±K exchange」上下文擴展。

  此 migration 加上 exchange_id 連結，並用 (session_uuid, user_text_preview 前 100 字)
  對碰 exchanges 表 backfill。失敗者保持 NULL，召回端 fallback 單 exchange 行為。

驗證：
  python -m evaluation.migration_exchange_id_link
  sqlite3 data/shiba-brain.db "SELECT count(*), count(exchange_id) FROM exchange_embeddings;"

通過條件：匹配率 ≥ 80%。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shiba_db import open_connection  # noqa: E402


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _index_exists(conn: sqlite3.Connection, index: str) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index,),
    ).fetchall()
    return bool(rows)


def run() -> None:
    conn = open_connection("writer")
    try:
        # Step 1：補欄位（idempotent）
        if not _column_exists(conn, "exchange_embeddings", "exchange_id"):
            conn.execute(
                "ALTER TABLE exchange_embeddings "
                "ADD COLUMN exchange_id INTEGER REFERENCES exchanges(id)"
            )
            print("[migration] exchange_embeddings.exchange_id 欄位已新增")
        else:
            print("[migration] exchange_embeddings.exchange_id 欄位已存在")

        # Step 2：補 index（idempotent）
        if not _index_exists(conn, "idx_exchange_embeddings_exchange"):
            conn.execute(
                "CREATE INDEX idx_exchange_embeddings_exchange "
                "ON exchange_embeddings(exchange_id)"
            )
            print("[migration] idx_exchange_embeddings_exchange 索引已建立")
        else:
            print("[migration] idx_exchange_embeddings_exchange 索引已存在")

        conn.commit()

        # Step 3a：原始 instruction backfill — (session_uuid, user_text_preview 前 100 字) 對碰
        # 只更新尚未配對 + 非 paraphrase 的 row
        cursor = conn.execute(
            """
            UPDATE exchange_embeddings
            SET exchange_id = (
                SELECT e.id FROM exchanges e
                JOIN sessions s ON s.id = e.session_id
                WHERE s.uuid = exchange_embeddings.session_uuid
                  AND substr(e.user_text_preview, 1, 100)
                      = substr(exchange_embeddings.instruction, 1, 100)
                ORDER BY e.exchange_idx
                LIMIT 1
            )
            WHERE exchange_id IS NULL
              AND source_instruction IS NULL
            """
        )
        conn.commit()
        print(f"[backfill-original] 嘗試配對 {cursor.rowcount} 筆")

        # Step 3b：paraphrase backfill — 繼承 source_instruction 對應原始那筆的 exchange_id
        # paraphrase 是合成資料，無法直接對 exchanges；改用「同 source_instruction
        # 的原始 row 已配對」推導；避免無限展開，只查 source_instruction IS NULL 的原始 row
        cursor_p = conn.execute(
            """
            UPDATE exchange_embeddings
            SET exchange_id = (
                SELECT orig.exchange_id FROM exchange_embeddings orig
                WHERE orig.source_instruction IS NULL
                  AND orig.instruction = exchange_embeddings.source_instruction
                  AND orig.session_uuid = exchange_embeddings.session_uuid
                  AND orig.exchange_id IS NOT NULL
                LIMIT 1
            )
            WHERE exchange_id IS NULL
              AND source_instruction IS NOT NULL
            """
        )
        conn.commit()
        print(f"[backfill-paraphrase] 嘗試配對 {cursor_p.rowcount} 筆")

        # Step 4：驗證匹配率（分原始 / paraphrase）
        orig_total, orig_matched = conn.execute(
            "SELECT count(*), count(exchange_id) FROM exchange_embeddings "
            "WHERE source_instruction IS NULL"
        ).fetchone()
        para_total, para_matched = conn.execute(
            "SELECT count(*), count(exchange_id) FROM exchange_embeddings "
            "WHERE source_instruction IS NOT NULL"
        ).fetchone()
        total = orig_total + para_total
        matched = orig_matched + para_matched

        def _rate(m: int, t: int) -> str:
            return f"{m / t * 100:.1f}%" if t else "n/a"

        print(f"[verify] 原始    : {orig_matched}/{orig_total} = {_rate(orig_matched, orig_total)}")
        print(f"[verify] paraphrase: {para_matched}/{para_total} = {_rate(para_matched, para_total)}")
        print(f"[verify] 總計    : {matched}/{total} = {_rate(matched, total)}")

        if orig_matched / orig_total < 0.8 if orig_total else False:
            print(f"[warn] 原始 instruction 匹配率 < 80%，召回品質可能受影響")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
