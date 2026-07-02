#!/usr/bin/env python3
"""一次性 schema 遷移：rename 舊 exchange_embeddings → deprecated_exchange_embeddings_old，
建含 answer 的新表。idempotent：偵測 deprecated_exchange_embeddings_old 表存在即跳過。

Guard 設計說明：
  舊 guard（answer 欄存在）已失準——另一個已修 bug 曾讓 init_db auto-ALTER 把
  answer 欄加到還沒 rename 的舊表，導致 guard 誤判「已遷移」而跳過 rename。
  新 guard 改用 deprecated_exchange_embeddings_old 表是否存在：該表只有本腳本會建，
  是「rename 真的發生過」的可靠訊號，與 answer 欄存在無關。

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


def _table_exists(conn, name: str) -> bool:
    """sqlite_master 查表是否存在；只有本腳本會建 deprecated 表，故為可靠 idempotency 訊號。"""
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def main() -> None:
    with get_connection() as conn:
        cols = _cols(conn, "exchange_embeddings")
        if not cols:
            # 分支 1：exchange_embeddings 不存在 → 建全新空表
            conn.executescript(_NEW_DDL)
            conn.execute("CREATE INDEX idx_exchange_embeddings_session ON exchange_embeddings(session_uuid)")
            conn.execute("CREATE INDEX idx_exchange_embeddings_exchange ON exchange_embeddings(exchange_id)")
            conn.commit()
            print("no existing table; created fresh new table")
            return
        if _table_exists(conn, "deprecated_exchange_embeddings_old"):
            # 分支 2：deprecated 表已存在 → rename 已發生過、跳過（可靠 idempotency guard）
            print("already migrated (deprecated_exchange_embeddings_old exists); skip")
            return
        # 分支 3：exchange_embeddings 存在但 deprecated 表不在 → 執行 rename + 建新表
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
