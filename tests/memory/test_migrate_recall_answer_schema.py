"""migrate_recall_answer_schema：舊表改名保留 + 新表含 answer。"""
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


def test_rename_old_and_create_new(tmp_path):
    db_file = tmp_path / "t.db"
    # 種一張舊 schema（無 answer）的表 + 1 筆資料
    conn = sqlite3.connect(str(db_file))
    conn.execute("""CREATE TABLE exchange_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_uuid TEXT NOT NULL,
        instruction TEXT NOT NULL, commands TEXT NOT NULL, embedding BLOB NOT NULL)""")
    conn.execute("CREATE INDEX idx_exchange_embeddings_session ON exchange_embeddings(session_uuid)")
    conn.execute("CREATE INDEX idx_exchange_embeddings_exchange ON exchange_embeddings(id)")  # M-3：補第二個索引讓兩條 DROP 都被觸發
    conn.execute("INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding)"
                 " VALUES ('s1', 'q', 'c', '[]')")
    conn.commit(); conn.close()

    fake = SimpleNamespace(paths=SimpleNamespace(db=db_file))
    import migrate_recall_answer_schema as mig
    with patch("shiba_db.CONFIG", fake):
        mig.main()

    conn = sqlite3.connect(str(db_file)); conn.row_factory = sqlite3.Row
    old_rows = conn.execute("SELECT COUNT(*) c FROM deprecated_exchange_embeddings_old").fetchone()["c"]
    new_cols = [r[1] for r in conn.execute("PRAGMA table_info(exchange_embeddings)").fetchall()]
    new_rows = conn.execute("SELECT COUNT(*) c FROM exchange_embeddings").fetchone()["c"]
    conn.close()

    assert old_rows == 1                 # 舊資料保留
    assert "answer" in new_cols          # 新表有 answer
    assert new_rows == 0                 # 新表空、待回填


def test_idempotent_skip(tmp_path):
    """I-1：新表已有 answer 欄時，main() 必須安全跳過，不執行 RENAME。"""
    db_file = tmp_path / "t2.db"
    # 種一張已含 answer 欄的表 + 1 筆資料（模擬已遷移狀態）
    conn = sqlite3.connect(str(db_file))
    conn.execute("""CREATE TABLE exchange_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_uuid TEXT NOT NULL,
        instruction TEXT NOT NULL, commands TEXT NOT NULL,
        answer TEXT, embedding BLOB NOT NULL)""")
    conn.execute("INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding)"
                 " VALUES ('s1', 'q', 'c', '[]')")
    conn.commit(); conn.close()

    fake = SimpleNamespace(paths=SimpleNamespace(db=db_file))
    import migrate_recall_answer_schema as mig
    with patch("shiba_db.CONFIG", fake):
        mig.main()  # 第一次呼叫
        mig.main()  # 第二次呼叫：確保 idempotent

    conn = sqlite3.connect(str(db_file)); conn.row_factory = sqlite3.Row
    # RENAME 從未發生：deprecated 表不應存在
    deprecated_exists = conn.execute(
        "SELECT COUNT(*) c FROM sqlite_master WHERE type='table'"
        " AND name='deprecated_exchange_embeddings_old'"
    ).fetchone()["c"]
    row_count = conn.execute("SELECT COUNT(*) c FROM exchange_embeddings").fetchone()["c"]
    conn.close()

    assert deprecated_exists == 0  # RENAME 從未發生
    assert row_count == 1          # 資料未被動
