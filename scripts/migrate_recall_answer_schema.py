#!/usr/bin/env python3
"""一次性 schema 遷移：rename 舊 exchange_embeddings → deprecated_exchange_embeddings_old，
建含 answer 的新表。idempotent：偵測新表已有 answer 欄即跳過。

非原子性限制：`executescript` 會隱式 COMMIT，RENAME+DROP 與 CREATE 並非單一交易。
若 CREATE 失敗，舊資料安全留在 deprecated_exchange_embeddings_old；重跑會走
fresh 分支建空新表，原資料需人工確認是否需回填。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "layer_1_memory"))
from lib.db import get_connection  # noqa: E402

_NEW_DDL = """
CREATE TABLE exchange_embeddings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid       TEXT NOT NULL,
    instruction        TEXT NOT NULL,
    source_instruction TEXT,
    commands           TEXT NOT NULL DEFAULT '',
    answer             TEXT,
    embedding          BLOB NOT NULL,
    model              TEXT NOT NULL DEFAULT 'bge-m3',
    exchange_id        INTEGER REFERENCES exchanges(id),
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _cols(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def main() -> None:
    with get_connection() as conn:
        cols = _cols(conn, "exchange_embeddings")
        if not cols:
            conn.executescript(_NEW_DDL)
            conn.execute("CREATE INDEX idx_exchange_embeddings_session ON exchange_embeddings(session_uuid)")
            conn.execute("CREATE INDEX idx_exchange_embeddings_exchange ON exchange_embeddings(exchange_id)")
            conn.commit()
            print("no existing table; created fresh new table")
            return
        if "answer" in cols:
            print("already migrated (answer column present); skip")
            return
        conn.execute("ALTER TABLE exchange_embeddings RENAME TO deprecated_exchange_embeddings_old")
        # RENAME 後舊索引名仍佔用命名空間，故在此 DROP 後再於新表 CREATE 同名索引
        conn.execute("DROP INDEX IF EXISTS idx_exchange_embeddings_session")
        conn.execute("DROP INDEX IF EXISTS idx_exchange_embeddings_exchange")
        conn.executescript(_NEW_DDL)
        conn.execute("CREATE INDEX idx_exchange_embeddings_session ON exchange_embeddings(session_uuid)")
        conn.execute("CREATE INDEX idx_exchange_embeddings_exchange ON exchange_embeddings(exchange_id)")
        conn.commit()
        print("migrated: old → deprecated_exchange_embeddings_old; new table created")


if __name__ == "__main__":
    main()
