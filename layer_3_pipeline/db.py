# layer_3_pipeline/db.py
"""finetune_runs 表 CRUD"""

import sqlite3
from pathlib import Path

from shiba_config import CONFIG

DB_PATH = CONFIG.paths.db


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def count_approved(conn: sqlite3.Connection, adapter_block: int) -> int:
    """回傳指定 block 的 approved 樣本數"""
    row = conn.execute(
        "SELECT COUNT(*) FROM training_samples WHERE status='approved' AND adapter_block=?",
        (adapter_block,),
    ).fetchone()
    return row[0]


def create_run(conn: sqlite3.Connection, adapter_block: int, sample_count: int, dataset_path: str) -> int:
    """建立新的 finetune_run，回傳 run_id"""
    cur = conn.execute(
        """INSERT INTO finetune_runs (adapter_block, status, sample_count, dataset_path, started_at)
           VALUES (?, 'running', ?, ?, datetime('now'))""",
        (adapter_block, sample_count, dataset_path),
    )
    conn.commit()
    return cur.lastrowid


def update_run(conn: sqlite3.Connection, run_id: int, **kwargs) -> None:
    """更新 run 欄位（adapter_path, gguf_path, ollama_model, status, error_msg, finished_at）"""
    sets = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(
        f"UPDATE finetune_runs SET {sets} WHERE id=?",
        (*kwargs.values(), run_id),
    )
    conn.commit()


def get_last_run_id(conn: sqlite3.Connection, adapter_block: int) -> int | None:
    """取得最近一次完成的 run 所涵蓋的最大 training_sample id，用於 since_id 計算"""
    row = conn.execute(
        """SELECT MAX(ts.id) FROM training_samples ts
           JOIN finetune_runs fr ON fr.adapter_block = ts.adapter_block
           WHERE fr.status = 'done' AND ts.adapter_block = ?""",
        (adapter_block,),
    ).fetchone()
    return row[0]
