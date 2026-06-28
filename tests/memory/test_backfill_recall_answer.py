"""backfill_recall_answer：去重取最新 + 純問答納入。"""
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "layer_1_memory"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


def _seed(db_file: Path):
    schema = (Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql").read_text("utf-8")
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    # 1 session（schema 用 project_id NOT NULL，非 project_path；FK 在 plain connect 下不強制）
    conn.execute("INSERT INTO sessions (id, uuid, project_id) VALUES (1, 's-1', 1)")
    # messages：同問題兩答（舊/新）+ 一筆純問答
    # 注意：D4 問句加「一下」湊 >15 字（production 過濾 length(trim)>15，邊界 15 會被排除）
    rows = [
        (1, 'user', 'D4 灌水是什麼意思請詳細解釋一下'),
        (2, 'assistant', '舊答案：粗略說明'),
        (3, 'user', 'D4 灌水是什麼意思請詳細解釋一下'),
        (4, 'assistant', '新答案：branch membership 錯亂'),
        (5, 'user', '請說明 RAG 召回的整體流程設計'),
        (6, 'assistant', '召回流程：embed → cosine → 取 top-k'),
    ]
    for mid, role, content in rows:
        conn.execute(
            "INSERT INTO messages (id, session_id, uuid, role, content) VALUES (?,1,?,?,?)",
            (mid, f'm{mid}', role, content),
        )
    # exchanges：兩筆同問題（ended_at 舊→新）+ 一筆純問答
    ex = [
        (1, 1, 1, 2, '2026-01-01T00:00:00'),
        (2, 1, 3, 4, '2026-02-01T00:00:00'),
        (3, 1, 5, 6, '2026-03-01T00:00:00'),
    ]
    for eid, sess, um, am, ended in ex:
        conn.execute(
            """INSERT INTO exchanges
               (id, session_id, branch_id, exchange_idx, user_message_id,
                final_assistant_message_id, has_final_text, started_at, ended_at)
               VALUES (?, ?, 1, ?, ?, ?, 1, ?, ?)""",
            (eid, sess, eid, um, am, ended, ended),
        )
    conn.commit()
    conn.close()


def test_backfill_dedup_latest_and_pure_qa(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fake = SimpleNamespace(paths=SimpleNamespace(db=db_file))
    import backfill_recall_answer as bf
    with patch("shiba_db.CONFIG", fake), \
         patch.object(bf, "get_embedding", return_value=[0.1, 0.2]):
        bf.main()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    out = {r["instruction"]: r["answer"] for r in
           conn.execute("SELECT instruction, answer FROM exchange_embeddings").fetchall()}
    conn.close()

    # 同問題去重剩 1 筆、取最新答案
    assert out["D4 灌水是什麼意思請詳細解釋一下"] == "新答案：branch membership 錯亂"
    # 純問答納入
    assert out["請說明 RAG 召回的整體流程設計"] == "召回流程：embed → cosine → 取 top-k"
    assert len(out) == 2
