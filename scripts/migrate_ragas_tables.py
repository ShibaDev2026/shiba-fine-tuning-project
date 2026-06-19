#!/usr/bin/env python3
"""scripts/migrate_ragas_tables.py — 一次性：建 ragas_ 前綴表 + 搬舊資料。

背景：PR-O 模組化把 ragas code 改用 `ragas_` 前綴表 + feature_registry，但
`apply_features` 從未接線到啟動流程（feature_registry.py 自注「尚未接線」）→
`ragas_` 表從沒建、`migrate_legacy` 從沒跑，舊資料滯留無前綴舊表
（`retrieval_golden_set` 111 / `evaluation_results` 909），runner 查 `ragas_` 新表查無
→ RAGAS 評估跑不動。所有 active code（builder/runner/c2/layer2_eval）已寫 `ragas_` 前綴、
無人寫舊名 → 舊表為 pre-PR-O vestigial，搬移無雙寫衝突。

本 script 補那一次性 init：套 `ragas.sql` schema + 跑 `migrate_legacy` 搬舊資料。
idempotent（`CREATE IF NOT EXISTS` + `INSERT...SELECT WHERE id NOT IN`）可重跑。

⚠ 誠實邊界：本 script 只修「RAGAS 資料存取」；`apply_features` 無呼叫者的架構債**未解**
（把 feature_registry 接線到 main/server 啟動仍 open，本 script 不碰、不完成 PR-O）。

用法：python3 scripts/migrate_ragas_tables.py [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from shiba_config import CONFIG  # noqa: E402
from modules.ragas.migrations import migrate_legacy  # noqa: E402

_SCHEMA = _ROOT / "modules" / "ragas" / "db" / "ragas.sql"


def migrate(db_path=None) -> dict:
    """套 ragas schema（建 ragas_ 表）+ 搬舊表資料；回傳搬移筆數與新表 row count。"""
    conn = sqlite3.connect(str(db_path or CONFIG.paths.db))
    try:
        conn.executescript(_SCHEMA.read_text(encoding="utf-8"))  # 建 ragas_ 表（冪等）
        moved = migrate_legacy(conn)                              # 搬舊資料（冪等 id NOT IN）
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("ragas_retrieval_golden_set", "ragas_evaluation_results")
        }
        return {"moved": moved, "counts": counts}
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一次性建 ragas_ 表 + 搬舊資料")
    parser.add_argument("--db", default=None, help="DB 路徑（預設 CONFIG.paths.db）")
    args = parser.parse_args()
    res = migrate(db_path=args.db)
    print(f"搬移筆數：{res['moved']}")
    print(f"新表 row count：{res['counts']}")
