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
    """I-1：deprecated_exchange_embeddings_old 表已存在時，main() 必須安全跳過，不再執行 RENAME。
    Guard 已改用 deprecated 表存在作訊號（answer 欄訊號已失準，見腳本說明）。"""
    db_file = tmp_path / "t2.db"
    # 種「已完成遷移」的狀態：deprecated 舊表已存在 + 新 exchange_embeddings（含 answer）
    conn = sqlite3.connect(str(db_file))
    conn.execute("""CREATE TABLE deprecated_exchange_embeddings_old (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_uuid TEXT NOT NULL,
        instruction TEXT NOT NULL, commands TEXT NOT NULL, embedding BLOB NOT NULL)""")
    conn.execute("INSERT INTO deprecated_exchange_embeddings_old (session_uuid, instruction, commands, embedding)"
                 " VALUES ('s1', 'q', 'c', '[]')")
    conn.execute("""CREATE TABLE exchange_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_uuid TEXT NOT NULL,
        instruction TEXT NOT NULL, commands TEXT NOT NULL,
        answer TEXT, embedding BLOB NOT NULL)""")
    conn.execute("INSERT INTO exchange_embeddings (session_uuid, instruction, commands, embedding)"
                 " VALUES ('s2', 'q2', 'c2', '[]')")
    conn.commit(); conn.close()

    fake = SimpleNamespace(paths=SimpleNamespace(db=db_file))
    import migrate_recall_answer_schema as mig
    with patch("shiba_db.CONFIG", fake):
        mig.main()  # 第一次呼叫
        mig.main()  # 第二次呼叫：確保 idempotent

    conn = sqlite3.connect(str(db_file)); conn.row_factory = sqlite3.Row
    # RENAME 沒有再發生：exchange_embeddings 資料仍存在（未被改名或清空）
    row_count = conn.execute("SELECT COUNT(*) c FROM exchange_embeddings").fetchone()["c"]
    conn.close()

    assert row_count == 1  # exchange_embeddings 資料未被動（RENAME 未再發生）


def test_proceeds_when_answer_col_but_no_deprecated(tmp_path):
    """I-2（核心新測試）：production 現況——exchange_embeddings 有 answer 欄但 deprecated 表不存在。
    舊 guard 誤判 skip；新 guard 必須正確執行 rename。"""
    db_file = tmp_path / "t3.db"
    # 種「answer 欄已被 init_db auto-ALTER 加入、但 rename 從未發生」的 production 現況
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
        mig.main()  # rename 必須發生

    conn = sqlite3.connect(str(db_file)); conn.row_factory = sqlite3.Row
    # deprecated 表存在且含舊資料（rename 真的發生了）
    deprecated_rows = conn.execute(
        "SELECT COUNT(*) c FROM deprecated_exchange_embeddings_old"
    ).fetchone()["c"]
    new_cols = [r[1] for r in conn.execute("PRAGMA table_info(exchange_embeddings)").fetchall()]
    new_rows = conn.execute("SELECT COUNT(*) c FROM exchange_embeddings").fetchone()["c"]
    conn.close()

    assert deprecated_rows == 1    # 舊資料保留在 deprecated 表（rename 發生）
    assert "answer" in new_cols    # 新表有 answer 欄
    assert new_rows == 0           # 新表空、待回填
