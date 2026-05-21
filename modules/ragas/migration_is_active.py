"""幂等 migration：ragas_retrieval_golden_set 新增 is_active 欄位 + 標記低分題目為 deprecated。

12 筆汰換清單（雙模型 mean ≤ 4.5）：
  id=11 你有閱讀過那四份論文嗎              (Qwen 0 / Claude 0) — 主語不明
  id=12 Layer 0/1/3 選用何種模型             (Qwen 0 / Claude 0) — context 不在 RAG 範圍
  id=29 模型的實際用途是否會造成理解混淆    (Qwen 0 / Claude 4) — 抽象概念題
  id=27 系統區域命令未有列印資訊            (Qwen 4 / Claude 3) — 語意斷裂
  id=28 何處可查詢全部接口資訊              (Qwen 4 / Claude 3) — 指涉過於模糊
  id=9  調整投入層級至宜中水平              (Qwen 4 / Claude 4) — 翻譯腔
  id=15 bypass permissions 推薦哪個 model    (Qwen 4 / Claude 4) — 主觀推薦
  id=17 提取位置第一及第二的 y               (Qwen 4 / Claude 4) — 缺上下文
  id=22 只讀 DB 的什麼表跟哪個欄位           (Qwen 4 / Claude 4) — 太泛
  id=25 先把 A5 執行完就立刻中止             (Qwen 4 / Claude 4) — A5 不明
  id=4  掛鉤的兩個程式是否啟動               (Qwen 7 / Claude 1) — 時態依賴
  id=6  啟動最深層次思考與滿載輸出           (Qwen 8 / Claude 0) — meta-prompt
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shiba_db import open_connection  # noqa: E402

DEPRECATED_IDS = [4, 6, 9, 11, 12, 15, 17, 22, 25, 27, 28, 29]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def run() -> None:
    conn = open_connection("writer")
    try:
        if not _column_exists(conn, "ragas_retrieval_golden_set", "is_active"):
            conn.execute(
                "ALTER TABLE ragas_retrieval_golden_set "
                "ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )
            print("[migration] ragas_retrieval_golden_set.is_active 欄位已新增")
        else:
            print("[migration] ragas_retrieval_golden_set.is_active 欄位已存在")

        placeholders = ",".join("?" for _ in DEPRECATED_IDS)
        cursor = conn.execute(
            f"UPDATE ragas_retrieval_golden_set "
            f"SET is_active = 0, "
            f"    notes = COALESCE(notes || ' | ', '') || "
            f"            'deprecated-low-score-2026-05-21' "
            f"WHERE id IN ({placeholders}) AND is_active = 1",
            DEPRECATED_IDS,
        )
        conn.commit()
        print(f"[migration] 已標記 {cursor.rowcount} 筆為 deprecated（is_active=0）")

        active = conn.execute(
            "SELECT COUNT(*) FROM ragas_retrieval_golden_set WHERE is_active = 1"
        ).fetchone()[0]
        print(f"[verify] 剩餘 active 樣本：{active} 筆")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
