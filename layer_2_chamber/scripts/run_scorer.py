"""
run_scorer.py — 獨立 Scorer CLI（不依賴 FastAPI / APScheduler）

執行：
    python layer_2_chamber/scripts/run_scorer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.core.config import DB_PATH, init_layer2_db
from layer_2_chamber.backend.core.background import score_pending_samples


def main():
    print(f"=== Shiba Scorer（{DB_PATH}）===")

    conn = init_layer2_db()
    pending = conn.execute(
        "SELECT COUNT(*) FROM training_samples WHERE status='pending'"
    ).fetchone()[0]
    conn.close()

    if pending == 0:
        print("目前沒有 pending 樣本。")
        return

    print(f"發現 {pending} 筆 pending 樣本，開始評分...\n")

    total_scored = 0
    total_failed = 0
    batch_no = 0

    while True:
        conn = init_layer2_db()
        remaining = conn.execute(
            "SELECT COUNT(*) FROM training_samples WHERE status='pending'"
        ).fetchone()[0]
        conn.close()

        if remaining == 0:
            break

        batch_no += 1
        print(f"  批次 {batch_no}（剩餘 {remaining} 筆）...", end=" ", flush=True)
        result = score_pending_samples(init_layer2_db)
        total_scored += result["scored"]
        total_failed += result["failed"]
        print(f"scored={result['scored']}, failed={result['failed']}")

        if result["scored"] == 0 and result["failed"] == 0:
            print("  → 所有 Teacher 配額已滿或無可用 Teacher，停止。")
            break

    print(f"\n完成：共評分 {total_scored} 筆，失敗 {total_failed} 筆。")

    conn = init_layer2_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM training_samples GROUP BY status ORDER BY status"
    ).fetchall()
    conn.close()

    print("\n[最終狀態分布]")
    for r in rows:
        print(f"  {r[0]:<14}: {r[1]} 筆")


if __name__ == "__main__":
    main()
