"""shiba_db.py — 全專案統一 SQLite 連線 helper

跨 Layer 0/1/2/3 共用同一套 PRAGMA，消除三層 PRAGMA 不一致導致的 WAL race。

呼叫方統一入口：

    from shiba_db import open_connection, get_connection

    # 一次性操作
    conn = open_connection()
    conn.execute("SELECT 1")
    conn.close()

    # context manager（自動 commit/rollback/close）
    with get_connection() as conn:
        conn.execute("INSERT INTO ...")

設計原則：
- PRAGMA 集中在 open_connection，呼叫方不得自行設 PRAGMA
- synchronous=NORMAL：WAL 模式下對 process crash 安全；macOS bind mount 上 FULL 過慢
- busy_timeout=30000：30s lock 等待，涵蓋 APScheduler job 最長持鎖窗口
- wal_autocheckpoint=1000：約 4MB 自動 checkpoint，避免 WAL 無限膨脹
- mmap_size=256MB：memory map 減少 syscall，macOS bind mount 下效果顯著
- check_same_thread=False：APScheduler 與 uvicorn 在不同 thread 使用同一連線時不拋錯
"""

import sqlite3
from contextlib import contextmanager
from typing import Generator, Literal

from shiba_config import CONFIG

# 全專案統一 PRAGMA；順序不可任意調換（journal_mode 須先設，其他才生效）
_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=30000",
    "PRAGMA wal_autocheckpoint=1000",
    "PRAGMA mmap_size=268435456",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA foreign_keys=ON",
)


def open_connection(
    role: Literal["writer", "reader"] = "writer",
    timeout: float = 30.0,
) -> sqlite3.Connection:
    """取得套好全套 PRAGMA 的 SQLite connection。

    role 為文件用途，目前兩者行為相同；
    未來可在此加 advisory file lock 或 WAL reader/writer 差異化。
    呼叫方須負責 conn.close()。
    """
    conn = sqlite3.connect(
        str(CONFIG.paths.db),
        timeout=timeout,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


@contextmanager
def get_connection(
    role: Literal["writer", "reader"] = "writer",
) -> Generator[sqlite3.Connection, None, None]:
    """context manager 版：自動 commit / rollback / close。

    with get_connection() as conn:
        conn.execute("INSERT INTO ...")
    # 離開 with 自動 commit；exception 自動 rollback
    """
    conn = open_connection(role)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
