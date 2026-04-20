"""
dataset_formatter.py — 訓練資料集 Alpaca JSONL 輸出

輸出格式（每行一個 JSON）：
{"instruction": "...", "input": "...", "output": "...", "adapter_block": 1}

訓練資料比例（FOREVER 校準後）：
  70%：當次新 approved 樣本（since_id 之後），依 weight 加權採樣
  20%：歷史 Ebbinghaus 分桶 replay（{1,2,4,7,15,30} 日，各桶均等取樣）
  10%：保留給通用指令集（由 Layer 3 pipeline 外部注入，此處不處理）

P1-3 隱性標籤 weight 語意：
  1.0 = Router 採納（正常）
  1.5 = Router 被拒絕（重點學習）
  2.0 = Claude 完全接手（最失敗狀況）
"""

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlite3

logger = logging.getLogger(__name__)

# Ebbinghaus 分桶（FOREVER 論文間隔，單位：天）
_EBBINGHAUS_BUCKETS = [1, 2, 4, 7, 15, 30]
_STABLE_SCORE_MIN = 8.5  # 歷史樣本最低分數門檻


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
    replay_samples = _fetch_ebbinghaus_replay(conn, adapter_block, since_id)

    # 70/20 比例（weight 加權展開 new_samples；10% 通用指令集由外部注入）
    new_count = len(new_samples)
    replay_target = _calc_replay_target(new_count)
    replay_samples = replay_samples[:replay_target]

    # P1-3：依 weight 展開 new_samples（weight=1.5 → 出現 1-2 次；weight=2.0 → 出現 2 次）
    expanded_new = _expand_by_weight(new_samples)

    all_samples = expanded_new + replay_samples
    random.shuffle(all_samples)

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
        "new_expanded": len(expanded_new),
        "replay": len(replay_samples),
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
    """當次新 approved 樣本（id >= since_id），含 weight 欄位。"""
    sql = """
        SELECT instruction, input, output, adapter_block,
               COALESCE(weight, 1.0) as weight
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


def _fetch_ebbinghaus_replay(
    conn: sqlite3.Connection,
    adapter_block: int | None,
    since_id: int,
) -> list[sqlite3.Row]:
    """
    FOREVER 式 Ebbinghaus 分桶 replay：
    按 {1,2,4,7,15,30} 天間隔，各桶各取若干，均等混入。
    只取 score >= STABLE_SCORE_MIN 的歷史樣本（id < since_id）。
    """
    now = datetime.now(timezone.utc)
    all_samples: list[sqlite3.Row] = []

    for days in _EBBINGHAUS_BUCKETS:
        bucket_start = (now - timedelta(days=days + 1)).isoformat()
        bucket_end = (now - timedelta(days=max(days - 1, 0))).isoformat()

        sql = """
            SELECT instruction, input, output, adapter_block,
                   COALESCE(weight, 1.0) as weight
              FROM training_samples
             WHERE status = 'approved'
               AND score >= ?
               AND created_at BETWEEN ? AND ?
               AND id < ?
        """
        params: list = [_STABLE_SCORE_MIN, bucket_start, bucket_end, since_id]
        if adapter_block is not None:
            sql += " AND adapter_block = ?"
            params.append(adapter_block)
        sql += " ORDER BY score DESC LIMIT 10"

        rows = conn.execute(sql, params).fetchall()
        all_samples.extend(rows)

    return all_samples


def _expand_by_weight(samples: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """
    P1-2/P1-3：依 weight 決定納入方式。
      weight < 1.0（soft label 0.5）→ 按概率納入（50% 機率）
      weight == 1.0 → 1 次（正常採納）
      1.0 < weight ≤ 1.5 → 2 次（Router 拒絕，重點學習）
      weight > 1.5 → 3 次（Claude 完全接手，最失敗狀況）
    """
    expanded = []
    for s in samples:
        w = s["weight"] if s["weight"] is not None else 1.0
        if w < 1.0:
            if random.random() < w:  # soft label：按 weight 概率納入
                expanded.append(s)
        elif w <= 1.0:
            expanded.append(s)
        elif w <= 1.5:
            expanded.extend([s, s])
        else:
            expanded.extend([s, s, s])
    return expanded


def _calc_replay_target(new_count: int) -> int:
    """目標 replay 數 = new 樣本的 2/7（維持 70/20 比例）。最少 0。"""
    return max(0, round(new_count * 2 / 7))


def _calc_stable_target(new_count: int) -> int:
    """
    依 70/20/10 比例計算穩定樣本目標數量。
    new_count 視為 70 份，推算 20 份對應數量。
    """
    if new_count == 0:
        return 0
    return round(new_count * 20 / 70)
