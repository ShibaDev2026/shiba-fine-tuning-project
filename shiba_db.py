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
- journal_mode=DELETE：macOS Virtualization.framework（Docker bind mount）下 WAL SHM
  跨虛擬化層鎖定不一致；DELETE mode 無 SHM/WAL 檔案，根治 container malformed 問題
- synchronous=NORMAL：DELETE mode 下對 process crash 安全；FULL 在 macOS bind mount 過慢
- busy_timeout=30000：30s lock 等待，涵蓋 APScheduler job 最長持鎖窗口
- mmap_size=256MB：memory map 減少 syscall，macOS bind mount 下效果顯著
- check_same_thread=False：APScheduler 與 uvicorn 在不同 thread 使用同一連線時不拋錯
"""

import sqlite3
from contextlib import contextmanager
from typing import Generator, Literal

from shiba_config import CONFIG

# 全專案統一 PRAGMA；順序不可任意調換（journal_mode 須先設，其他才生效）
# journal_mode=DELETE：macOS Virtualization.framework（Docker bind mount）下
# WAL 模式的 SHM 鎖定跨虛擬化層不一致，導致 host integrity_check=ok 但 container
# 回報 malformed；DELETE mode 無 SHM/WAL 檔案，根治此問題。
_PRAGMAS = (
    "PRAGMA journal_mode=DELETE",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=30000",
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
