"""backfill_bge_m3.py — exchange_embeddings 從 nomic-embed-text 重 embed 到 bge-m3

切換流程：
  1. 備份 ./data/shiba-brain.db → ./data/<DATE>_shiba-brain.db.bge-m3-backfill.bak
  2. SELECT 全表 (id, instruction) 到記憶體
  3. DELETE FROM exchange_embeddings（schema 不變，但 dim 從 768 → 1024）
  4. 逐筆 get_embedding(instruction) + 寫回（model='bge-m3'）；每筆 commit 可中斷續跑
  5. 失敗（Ollama 離線）→ 該筆 skip 並印 warning，不中止整批

驗證：
  python -m evaluation.backfill_bge_m3
  sqlite3 ./data/shiba-brain.db "SELECT model, COUNT(*) FROM exchange_embeddings GROUP BY model"
"""

import json
import shutil
import time
from datetime import date
from pathlib import Path

from layer_1_memory.lib import db as l1_db
from layer_1_memory.lib.embedder import get_embedding, EMBED_MODEL


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "shiba-brain.db"


def _backup_db() -> Path:
    """切換前備份 DB（防 backfill 失敗回滾）"""
    bak = DB_PATH.with_name(f"{date.today().isoformat()}_shiba-brain.db.bge-m3-backfill.bak")
    shutil.copy2(DB_PATH, bak)
    return bak


def main() -> None:
    assert EMBED_MODEL == "bge-m3", f"embedder.py EMBED_MODEL 應為 bge-m3，實際 {EMBED_MODEL}"
    print(f"[1/4] 備份 DB → {_backup_db().name}")

    with l1_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, session_uuid, instruction, source_instruction, commands "
            "FROM exchange_embeddings ORDER BY id"
        ).fetchall()
        print(f"[2/4] 讀出 {len(rows)} 筆舊 embedding（nomic-embed-text）")

        conn.execute("DELETE FROM exchange_embeddings")
        conn.commit()
        print(f"[3/4] DELETE 完成")

    print(f"[4/4] 開始 backfill（bge-m3, dim=1024）...")
    ok, fail, t0 = 0, 0, time.time()
    for i, row in enumerate(rows, 1):
        vec = get_embedding(row["instruction"])
        if vec is None:
            fail += 1
            print(f"  ⚠ id={row['id']} Ollama 失敗，skip")
            continue
        l1_db.upsert_exchange_embedding(
            session_uuid=row["session_uuid"],
            instruction=row["instruction"],
            commands=row["commands"],
            embedding=vec,
            model="bge-m3",
            source_instruction=row["source_instruction"],
        )
        ok += 1
        if i % 100 == 0:
            elapsed = time.time() - t0
            eta = elapsed / i * (len(rows) - i)
            print(f"  {i}/{len(rows)}  ok={ok} fail={fail}  elapsed={elapsed:.0f}s  eta={eta:.0f}s")

    elapsed = time.time() - t0
    print(f"\n完成：ok={ok}, fail={fail}, total={len(rows)}, 耗時 {elapsed:.0f}s")


if __name__ == "__main__":
    main()
