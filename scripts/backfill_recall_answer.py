#!/usr/bin/env python3
"""一次性回填：從 exchanges 重建 exchange_embeddings 的答案側 payload。

來源 exchanges(has_final_text=1) → 同 instruction 去重取最新答案 → bge-m3 embed 問題 →
寫入新 exchange_embeddings（含 answer、含純問答）。歷史 commands 不回填（保留於
deprecated_exchange_embeddings_old），往後由 stop_hook 同步捕捉。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "layer_1_memory"))
from lib.db import get_connection, upsert_exchange_embedding  # noqa: E402
from lib.embedder import get_embedding  # noqa: E402

_MIN_INSTRUCTION_CHARS = 15
_ANSWER_CAP = 2000


def fetch_pairs(conn):
    """回傳問答對 rows，按 ended_at 升序（後者覆蓋前者＝保留最新）。"""
    return conn.execute(
        """
        SELECT um.content AS instruction,
               am.content AS answer,
               e.id       AS exchange_id,
               s.uuid     AS session_uuid,
               e.ended_at AS ended_at
        FROM exchanges e
        JOIN messages um ON um.id = e.user_message_id
        JOIN messages am ON am.id = e.final_assistant_message_id
        JOIN sessions s  ON s.id  = e.session_id
        WHERE e.has_final_text = 1
          AND um.content IS NOT NULL
          AND length(trim(um.content)) > ?
        ORDER BY e.ended_at ASC
        """,
        (_MIN_INSTRUCTION_CHARS,),
    ).fetchall()


def main() -> None:
    with get_connection() as conn:
        rows = fetch_pairs(conn)

    # 同 instruction 去重：升序遍歷讓最新 ended_at 覆蓋
    latest: dict[str, dict] = {}
    for r in rows:
        instr = r["instruction"].strip()[:300]
        latest[instr] = r

    written = skipped = 0
    for instr, r in latest.items():
        answer = ((r["answer"] or "").strip()[:_ANSWER_CAP]) or None
        vec = get_embedding(instr)
        if vec is None:
            skipped += 1
            continue
        upsert_exchange_embedding(
            session_uuid=r["session_uuid"],
            instruction=instr,
            commands="",            # 歷史 commands 不回填（見 docstring）
            answer=answer,
            embedding=vec,
            exchange_id=r["exchange_id"],
        )
        written += 1
    print(f"backfill done: written={written} skipped={skipped} distinct={len(latest)}")


if __name__ == "__main__":
    main()
