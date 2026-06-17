#!/usr/bin/env python3
"""
scripts/freeze_golden_set.py — 一次性執行：凍結歷史高分樣本為 gatekeeper_golden_samples。

挑選條件：
  - status='approved' AND score >= 9.0
  - 各 event_type 均勻配額（各 ~7 筆），上限 50 筆
  - 已凍結的 source_sample_id 不重複寫入

執行方式：
  python3 scripts/freeze_golden_set.py [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from shiba_config import CONFIG

EVENT_TYPES = [
    "git_ops", "terminal_ops", "code_gen",
    "debugging", "architecture", "knowledge_qa", "fine_tuning_ops",
]
MAX_TOTAL = 50
PER_TYPE = MAX_TOTAL // len(EVENT_TYPES) + 1  # 各 event_type 上限（略高於平均，讓均勻截斷）
MIN_SCORE = 9.0


def main(dry_run: bool = False, db_path=None):
    conn = sqlite3.connect(str(db_path or CONFIG.paths.db))
    conn.row_factory = sqlite3.Row

    # 確保 gatekeeper_golden_samples 表存在（初次執行 migration 可能不會跑到）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gatekeeper_golden_samples (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            source_sample_id INTEGER NOT NULL REFERENCES training_samples(id),
            instruction      TEXT NOT NULL,
            input            TEXT NOT NULL DEFAULT '',
            expected_output  TEXT NOT NULL,
            event_type       TEXT NOT NULL,
            score            REAL NOT NULL,
            frozen_at        TEXT NOT NULL DEFAULT (datetime('now')),
            is_active        INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gatekeeper_golden_event ON gatekeeper_golden_samples(event_type, is_active)"
    )
    conn.commit()

    # 已凍結的 source_sample_id（避免重複）
    existing_ids = {
        r[0] for r in conn.execute("SELECT source_sample_id FROM gatekeeper_golden_samples").fetchall()
    }

    total_inserted = 0
    stats: dict[str, int] = {}

    for event_type in EVENT_TYPES:
        rows = conn.execute(
            """SELECT id, instruction, input,
                      COALESCE(expected_answer, output) AS expected_output, score
               FROM training_samples
               WHERE status = 'approved'
                 AND score >= ?
                 AND event_type = ?
               ORDER BY score DESC, id DESC
               LIMIT ?""",
            (MIN_SCORE, event_type, PER_TYPE),
        ).fetchall()

        inserted = 0
        for row in rows:
            if total_inserted >= MAX_TOTAL:
                break
            if row["id"] in existing_ids:
                continue
            if not dry_run:
                conn.execute(
                    """INSERT INTO gatekeeper_golden_samples
                       (source_sample_id, instruction, input, expected_output, event_type, score)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"],
                        row["instruction"],
                        row["input"] or "",
                        row["expected_output"],
                        event_type,
                        row["score"],
                    ),
                )
            existing_ids.add(row["id"])
            inserted += 1
            total_inserted += 1

        stats[event_type] = inserted

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}凍結完成：共 {total_inserted} 筆")
    for et, cnt in stats.items():
        if cnt > 0:
            print(f"  {et}: {cnt} 筆")
    if total_inserted == 0:
        print("  ⚠ 無符合條件的樣本（score >= 9.0 + approved），稍後有足夠高分樣本後再執行")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="凍結 gatekeeper_golden_samples")
    parser.add_argument("--dry-run", action="store_true", help="只顯示統計，不寫入")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
