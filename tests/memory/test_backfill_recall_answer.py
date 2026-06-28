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


def _seed_with_noise(db_file: Path):
    """seed：2 筆雜訊 + 2 筆乾淨資料。"""
    schema = (Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql").read_text("utf-8")
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    conn.execute("INSERT INTO sessions (id, uuid, project_id) VALUES (1, 's-noise', 1)")
    # messages：系統注入 instruction / slash command / 限流錯誤 answer + 2 筆乾淨
    rows = [
        # id, role, content
        (1, 'user',      '<system-reminder>這是系統注入的內容，不是使用者提問</system-reminder>'),
        (2, 'assistant', '正常回應但 instruction 是雜訊'),
        (3, 'user',      '/resume'),  # slash command
        (4, 'assistant', '正常回應但 instruction 是 slash'),
        (5, 'user',      '請說明如何設定 RAG 門檻值與評分邏輯'),
        (6, 'assistant', "You've hit your session limit · resets at midnight"),
        (7, 'user',      '請詳細說明 Layer 1 記憶層的 bge-m3 嵌入流程'),
        (8, 'assistant', '嵌入流程：stop_hook → get_embedding → upsert'),
    ]
    for mid, role, content in rows:
        conn.execute(
            "INSERT INTO messages (id, session_id, uuid, role, content) VALUES (?,1,?,?,?)",
            (mid, f'm{mid}', role, content),
        )
    # exchanges：4 筆
    ex = [
        (1, 1, 2, '2026-01-01T00:00:00'),  # (exchange_id, user_msg_id, asst_msg_id, ended_at)
        (2, 3, 4, '2026-02-01T00:00:00'),
        (3, 5, 6, '2026-03-01T00:00:00'),
        (4, 7, 8, '2026-04-01T00:00:00'),
    ]
    for eid, um, am, ended in ex:
        conn.execute(
            """INSERT INTO exchanges
               (id, session_id, branch_id, exchange_idx, user_message_id,
                final_assistant_message_id, has_final_text, started_at, ended_at)
               VALUES (?, 1, 1, ?, ?, ?, 1, ?, ?)""",
            (eid, eid, um, am, ended, ended),
        )
    conn.commit()
    conn.close()


def test_backfill_skips_system_noise(tmp_path):
    """雜訊過濾：系統注入 instruction / slash command / 限流 answer 均不寫入 exchange_embeddings。"""
    db_file = tmp_path / "noise.db"
    _seed_with_noise(db_file)
    fake = SimpleNamespace(paths=SimpleNamespace(db=db_file))
    import backfill_recall_answer as bf
    with patch("shiba_db.CONFIG", fake), \
         patch.object(bf, "get_embedding", return_value=[0.1, 0.2]):
        bf.main()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT instruction, answer FROM exchange_embeddings").fetchall()
    conn.close()
    instructions = {r["instruction"] for r in rows}

    # 雜訊列不得出現
    assert not any(i.startswith("<") for i in instructions), \
        "系統注入 instruction (<…) 不應寫入"
    assert not any(i.startswith("/") for i in instructions), \
        "slash command instruction (/…) 不應寫入"
    # 限流 answer 那列也不得出現（instruction 本身乾淨，但 answer 含錯誤訊息）
    assert "請說明如何設定 RAG 門檻值與評分邏輯" not in instructions, \
        "answer 含限流錯誤的列不應寫入"

    # 乾淨列須寫入
    assert "請詳細說明 Layer 1 記憶層的 bge-m3 嵌入流程" in instructions, \
        "乾淨問答應寫入"
    assert len(rows) == 1, f"應只有 1 筆乾淨列，實際={len(rows)}"
