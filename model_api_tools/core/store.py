"""store.py — search_model_list / model_local_detail 持久層（DIP：抓取邏輯不碰 SQL）。

職責（SRP）：只負責「把 record 寫進 DB」與「讀回」，不負責抓取/掃描。

寫入契約：
- **append-only**：每次觸發寫一批新列；同批共用 scrape_run_id + scraped_at。
- 一筆 ModelRecord = search_model_list 一列；若帶 local_raw_metadata（deep），
  額外寫一列 model_local_detail（以剛插入的 rowid 關聯）。
- 單一事務：整批寫入，任一步失敗整體 rollback（不留半批）。

使用範例：

    import sqlite3
    from model_api_tools.core.store import (
        init_search_model_list, write_batch, get_latest, ModelRecord,
    )

    conn = sqlite3.connect(CONFIG.paths.db)
    init_search_model_list(conn)
    n = write_batch(conn, [ModelRecord(source="ollama", name="qwen3",
                                       detail_level="shallow")], scrape_run_id="<uuid>")
    rows = get_latest(conn, source="ollama")   # list[dict]
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from shiba_config import CONFIG

# schema 檔位置：走 CONFIG.paths.project_root 抽象，不硬編相對層數
_SCHEMA_PATH: Path = (
    CONFIG.paths.project_root / "config" / "db" / "schema_search_model_list.sql"
)


# ----------------------------------------------------------------
# Record 型別（scrapers / scanner 共同填充的契約）
# ----------------------------------------------------------------


@dataclass
class ModelRecord:
    """search_model_list 一列的內容欄位（id / scraped_at / scrape_run_id 由 store 指派）。

    必填：source / name / detail_level（對應 schema NOT NULL）。其餘缺值即 None/0。
    local_raw_metadata：僅 deep 列帶（本機 ollama show / GGUF metadata 全量 JSON），
    由 store 路由到 model_local_detail 子表。
    """

    source: str                                   # 'ollama' | 'huggingface'
    name: str
    detail_level: str                             # 'shallow' | 'deep'
    author: str | None = None
    source_url: str | None = None
    description: str | None = None
    usage: str | None = None
    tags: str | None = None                       # JSON array 字串
    updated_at: str | None = None
    download_count: int | None = None
    download_metric: str | None = None            # 'cumulative' | '30d'
    model_format: str | None = None               # 'gguf' | 'mlx' | 'safetensors' | 'other'
    param_size: str | None = None
    context_length: int | None = None
    file_size_bytes: int | None = None
    quantization: str | None = None
    is_local_installed: int = 0
    local_raw_metadata: str | None = None         # deep 才有；路由到 model_local_detail


# ----------------------------------------------------------------
# 初始化
# ----------------------------------------------------------------


def init_search_model_list(conn: sqlite3.Connection) -> None:
    """執行 schema_search_model_list.sql；CREATE ... IF NOT EXISTS 故冪等。"""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


# ----------------------------------------------------------------
# helpers
# ----------------------------------------------------------------


def _now_utc() -> str:
    """UTC 時戳字串，格式與 schema DEFAULT (datetime('now')) 一致。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _rows_to_dicts(cur: sqlite3.Cursor) -> list[dict]:
    """cursor → list[dict]，不依賴 conn.row_factory（self-contained）。"""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# 主表欄位順序（INSERT 用；id/scraped_at/scrape_run_id 另外處理）
_CONTENT_COLS = (
    "source", "name", "author", "source_url", "description", "usage", "tags",
    "updated_at", "download_count", "download_metric", "model_format", "param_size",
    "context_length", "file_size_bytes", "quantization", "is_local_installed",
    "detail_level",
)


# ----------------------------------------------------------------
# 寫入
# ----------------------------------------------------------------


def write_batch(
    conn: sqlite3.Connection,
    records: list[ModelRecord],
    scrape_run_id: str,
    scraped_at: str | None = None,
) -> int:
    """append 一批 record（共用 scrape_run_id / scraped_at），回傳寫入列數。

    deep 列若帶 local_raw_metadata，額外寫 model_local_detail。整批單一事務。
    CHECK 約束由 DB 把關（壞 source / detail_level / download_metric 直接 raise）。
    """
    if scraped_at is None:
        scraped_at = _now_utc()

    placeholders = ",".join(["?"] * (len(_CONTENT_COLS) + 2))  # +scraped_at +scrape_run_id
    insert_sql = (
        f"INSERT INTO search_model_list "
        f"({','.join(_CONTENT_COLS)},scraped_at,scrape_run_id) "
        f"VALUES ({placeholders})"
    )

    try:
        conn.execute("BEGIN")
        for rec in records:
            values = tuple(getattr(rec, col) for col in _CONTENT_COLS) + (
                scraped_at,
                scrape_run_id,
            )
            cur = conn.execute(insert_sql, values)
            if rec.local_raw_metadata is not None:
                conn.execute(
                    "INSERT INTO model_local_detail (model_id, raw_metadata, scraped_at) "
                    "VALUES (?,?,?)",
                    (cur.lastrowid, rec.local_raw_metadata, scraped_at),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return len(records)


# ----------------------------------------------------------------
# 讀取
# ----------------------------------------------------------------


def get_latest(conn: sqlite3.Connection, source: str | None = None) -> list[dict]:
    """每 (source,name) 最新一批（走 v_search_model_latest）；可選 source 過濾。

    注意：跨來源的 download_count 單位不同（見 download_metric），故先按 source 分組排序。
    """
    sql = "SELECT * FROM v_search_model_latest"
    params: tuple = ()
    if source is not None:
        sql += " WHERE source=?"
        params = (source,)
    sql += " ORDER BY source, download_count DESC"
    return _rows_to_dicts(conn.execute(sql, params))


def _latest_filter(
    source: str | None,
    model_format: str | None,
    author: str | None,
    keyword: str | None,
) -> tuple[str, tuple]:
    """組 v_search_model_latest 的 WHERE 片段 + 參數（DIP：搜尋 SQL 收斂在 store）。

    search_models / count_models 共用，確保兩者過濾條件一致。keyword 對 name 模糊比對。
    """
    clauses: list[str] = []
    params: list = []
    if source is not None:
        clauses.append("source=?")
        params.append(source)
    if model_format is not None:
        clauses.append("model_format=?")
        params.append(model_format)
    if author is not None:
        clauses.append("author=?")
        params.append(author)
    if keyword:
        clauses.append("name LIKE ?")
        params.append(f"%{keyword}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, tuple(params)


def search_models(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    model_format: str | None = None,
    author: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """條件查詢 v_search_model_latest（搜尋 API 用）；分頁 limit/offset。

    排序與 get_latest 一致（先 source 分組、組內 download_count 降序），
    因跨來源 download 單位不同。
    """
    where, params = _latest_filter(source, model_format, author, keyword)
    sql = (
        "SELECT * FROM v_search_model_latest" + where
        + " ORDER BY source, download_count DESC LIMIT ? OFFSET ?"
    )
    return _rows_to_dicts(conn.execute(sql, params + (limit, offset)))


def count_models(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    model_format: str | None = None,
    author: str | None = None,
    keyword: str | None = None,
) -> int:
    """符合條件的最新模型總數（搜尋 API 分頁用，與 search_models 同條件）。"""
    where, params = _latest_filter(source, model_format, author, keyword)
    row = conn.execute(
        "SELECT COUNT(*) FROM v_search_model_latest" + where, params
    ).fetchone()
    return int(row[0])


def list_by_run(conn: sqlite3.Connection, scrape_run_id: str) -> list[dict]:
    """某次觸發批次寫入的全部列。"""
    return _rows_to_dicts(
        conn.execute(
            "SELECT * FROM search_model_list WHERE scrape_run_id=?", (scrape_run_id,)
        )
    )


def get_local_detail(conn: sqlite3.Connection, model_id: int) -> dict | None:
    """取某主列最新的本機深層 metadata（raw_metadata 解析成 dict）；無則 None。"""
    rows = _rows_to_dicts(
        conn.execute(
            "SELECT * FROM model_local_detail WHERE model_id=? ORDER BY id DESC LIMIT 1",
            (model_id,),
        )
    )
    if not rows:
        return None
    d = rows[0]
    if d.get("raw_metadata"):
        try:
            d["raw_metadata"] = json.loads(d["raw_metadata"])
        except (json.JSONDecodeError, TypeError):
            pass  # 非 JSON 則保留原字串
    return d


__all__ = [
    "ModelRecord",
    "init_search_model_list",
    "write_batch",
    "get_latest",
    "search_models",
    "count_models",
    "list_by_run",
    "get_local_detail",
]
