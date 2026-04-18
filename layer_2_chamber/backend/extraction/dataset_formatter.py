"""
dataset_formatter.py — 訓練資料集 Alpaca JSONL 輸出

輸出格式（每行一個 JSON）：
{"instruction": "...", "input": "...", "output": "...", "adapter_block": 1}

訓練資料比例（FOREVER / CLAUDE.md 規範）：
  70%：當次新 approved 樣本（since_id 之後）
  20%：歷史 score >= 8.5 且 > 30 天的穩定老樣本
  10%：保留給通用指令集（由 Layer 3 pipeline 外部注入，此處不處理）
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlite3

logger = logging.getLogger(__name__)

# 歷史穩定樣本門檻
_STABLE_SCORE_MIN = 8.5
_STABLE_AGE_DAYS = 30


def export_dataset(
    conn: sqlite3.Connection,
    output_path: Path,
    adapter_block: int | None = None,
    since_id: int = 0,
) -> dict:
    """
    將 approved 訓練樣本匯出為 Alpaca JSONL 檔案。

    Args:
        conn: DB connection
        output_path: 輸出 .jsonl 檔案路徑
        adapter_block: 1 或 2；None 代表全部輸出
        since_id: 新樣本的 id 下限（>= since_id 視為「當次新樣本」）

    Returns:
        {'new': int, 'stable': int, 'total': int, 'path': str}
    """
    new_samples = _fetch_new_samples(conn, adapter_block, since_id)
    stable_samples = _fetch_stable_samples(conn, adapter_block, since_id)

    # 70/20 比例計算（10% 通用指令集由外部注入）
    new_count = len(new_samples)
    stable_target = _calc_stable_target(new_count)
    stable_samples = stable_samples[:stable_target]

    all_samples = new_samples + stable_samples

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for sample in all_samples:
            record = {
                "instruction": sample["instruction"],
                "input": sample["input"] or "",
                "output": sample["output"],
                "adapter_block": sample["adapter_block"],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    stats = {
        "new": new_count,
        "stable": len(stable_samples),
        "total": len(all_samples),
        "path": str(output_path),
    }
    logger.info("Dataset 匯出完成：%s", stats)
    return stats


def get_export_stats(conn: sqlite3.Connection) -> dict:
    """
    回傳目前 training_samples 的統計摘要（供 API 使用）。
    """
    rows = conn.execute(
        """SELECT status, adapter_block, COUNT(*) as cnt
           FROM training_samples
           GROUP BY status, adapter_block"""
    ).fetchall()

    stats: dict = {"by_status": {}, "by_block": {1: 0, 2: 0}, "total": 0}
    for row in rows:
        status = row["status"]
        block = row["adapter_block"] or 0
        cnt = row["cnt"]

        stats["by_status"][status] = stats["by_status"].get(status, 0) + cnt
        stats["by_block"][block] = stats["by_block"].get(block, 0) + cnt
        stats["total"] += cnt

    return stats


# ── 內部查詢 ─────────────────────────────────────────────────────────────

def _fetch_new_samples(
    conn: sqlite3.Connection,
    adapter_block: int | None,
    since_id: int,
) -> list[sqlite3.Row]:
    """當次新 approved 樣本（id >= since_id）"""
    sql = """
        SELECT instruction, input, output, adapter_block
        FROM training_samples
        WHERE status = 'approved'
          AND id >= ?
    """
    params: list = [since_id]

    if adapter_block is not None:
        sql += " AND adapter_block = ?"
        params.append(adapter_block)

    sql += " ORDER BY id"
    return conn.execute(sql, params).fetchall()


def _fetch_stable_samples(
    conn: sqlite3.Connection,
    adapter_block: int | None,
    since_id: int,
) -> list[sqlite3.Row]:
    """歷史穩定樣本：score >= 8.5 且 created_at > 30 天前，排除當次新樣本"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_STABLE_AGE_DAYS)).isoformat()

    sql = """
        SELECT instruction, input, output, adapter_block
        FROM training_samples
        WHERE status = 'approved'
          AND score >= ?
          AND created_at <= ?
          AND id < ?
    """
    params: list = [_STABLE_SCORE_MIN, cutoff, since_id]

    if adapter_block is not None:
        sql += " AND adapter_block = ?"
        params.append(adapter_block)

    # decay_score 高的優先（branches 資訊已在 pipeline 層篩選，這裡按 score 排序）
    sql += " ORDER BY score DESC"
    return conn.execute(sql, params).fetchall()


def _calc_stable_target(new_count: int) -> int:
    """
    依 70/20/10 比例計算穩定樣本目標數量。
    new_count 視為 70 份，推算 20 份對應數量。
    """
    if new_count == 0:
        return 0
    return round(new_count * 20 / 70)
