# layer_3_pipeline/trigger_policy.py
"""
P1-1 動態訓練觸發策略（取代固定 approved≥30 門檻）。

三個信號，任一觸發 + approved ≥ MIN_SAMPLES → 開始訓練：
  A. Ebbinghaus 模型時間：壁鐘天數落在間隔 {1,2,4,7,15,30} 的容許窗口
  B. 採納退化：近 200 筆 local 決策採納率 < 7 日基線 - 10 pp
  C. 分布偏移：近 7 天 prompt embedding centroid 與上次訓練集 cosine > 0.35
"""

import logging
import math
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_SAMPLES = 30                          # 安全下限，保留原值
EBBINGHAUS_DAYS = [1, 2, 4, 7, 15, 30]  # FOREVER 論文間隔
EBBINGHAUS_WINDOW = 0.5                  # ±0.5 天的容許窗口
ADOPTION_WINDOW = 200                    # 信號 B 滑動視窗
ADOPTION_DROP_THRESHOLD = 0.10           # 跌幅門檻
DRIFT_THRESHOLD = 0.35                   # 信號 C cosine 距離門檻


@dataclass
class TriggerDecision:
    should_train: bool
    reason: str
    approved_count: int
    signal_a: bool = False
    signal_b: bool = False
    signal_c: bool = False


def should_trigger(conn: sqlite3.Connection, adapter_block: int) -> TriggerDecision:
    """
    評估三個信號，回傳 TriggerDecision。
    任一信號為 True 且 approved ≥ MIN_SAMPLES → should_train = True。
    """
    approved = _count_approved(conn, adapter_block)
    if approved < MIN_SAMPLES:
        return TriggerDecision(
            should_train=False,
            reason=f"approved={approved} < MIN_SAMPLES={MIN_SAMPLES}",
            approved_count=approved,
        )

    sig_a, reason_a = _signal_ebbinghaus(conn, adapter_block)
    sig_b, reason_b = _signal_adoption_drop(conn)
    sig_c, reason_c = _signal_distribution_drift(conn, adapter_block)

    triggered_reasons = [r for flag, r in [(sig_a, reason_a), (sig_b, reason_b), (sig_c, reason_c)] if flag]
    should_train = sig_a or sig_b or sig_c

    reason = " | ".join(triggered_reasons) if triggered_reasons else (
        f"無觸發（approved={approved}，等待信號）"
    )

    return TriggerDecision(
        should_train=should_train,
        reason=reason,
        approved_count=approved,
        signal_a=sig_a,
        signal_b=sig_b,
        signal_c=sig_c,
    )


# ── 信號 A：Ebbinghaus 模型時間 ─────────────────────────────────────────

def _signal_ebbinghaus(conn: sqlite3.Connection, adapter_block: int) -> tuple[bool, str]:
    """
    距上次 done run 的壁鐘天數，若落在 Ebbinghaus 間隔的 ±WINDOW 窗口 → 觸發。
    若從未跑過訓練 → 立即觸發（首次）。
    """
    last_dt = _last_finetune_datetime(conn, adapter_block)
    if last_dt is None:
        return True, "signal_a: 首次訓練"

    import datetime as dt
    elapsed = (dt.datetime.now(dt.timezone.utc) - last_dt).total_seconds() / 86400

    for interval in EBBINGHAUS_DAYS:
        if abs(elapsed - interval) <= EBBINGHAUS_WINDOW:
            return True, f"signal_a: Ebbinghaus {interval}d（elapsed={elapsed:.1f}d）"

    return False, f"signal_a: elapsed={elapsed:.1f}d，不在間隔窗口"


def _last_finetune_datetime(conn: sqlite3.Connection, adapter_block: int):
    """取最近一次 done run 的 finished_at（UTC aware），若無回 None。"""
    import datetime as dt
    row = conn.execute(
        "SELECT finished_at FROM finetune_runs "
        "WHERE adapter_block=? AND status='done' "
        "ORDER BY id DESC LIMIT 1",
        (adapter_block,),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        ts = row[0].replace("Z", "+00:00")
        return dt.datetime.fromisoformat(ts)
    except (ValueError, AttributeError):
        return None


# ── 信號 B：採納退化 ──────────────────────────────────────────────────

def _signal_adoption_drop(conn: sqlite3.Connection) -> tuple[bool, str]:
    """
    近 ADOPTION_WINDOW 筆 local 決策的採納率 vs 近 7 日基線。
    跌幅 > ADOPTION_DROP_THRESHOLD → 觸發。
    資料不足（< 50 筆已判定）→ 不觸發。
    """
    from layer_0_router.telemetry import get_acceptance_rate
    baseline_7d = get_acceptance_rate(days=7)
    if baseline_7d is None:
        return False, "signal_b: 採納率資料不足"

    # 近 ADOPTION_WINDOW 筆滑動視窗
    row = conn.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN user_accepted=1 THEN 1 ELSE 0 END) as accepted
             FROM (
               SELECT user_accepted FROM router_decisions
                WHERE classification='local'
                  AND user_accepted IS NOT NULL
                ORDER BY id DESC
                LIMIT ?
             )""",
        (ADOPTION_WINDOW,),
    ).fetchone()

    if not row or row["total"] < 50:
        return False, f"signal_b: 滑動視窗樣本不足（{row['total'] if row else 0}）"

    recent_rate = row["accepted"] / row["total"]
    drop = baseline_7d - recent_rate

    if drop > ADOPTION_DROP_THRESHOLD:
        return True, (
            f"signal_b: 採納率退化 {recent_rate:.2%} vs 基線 {baseline_7d:.2%}"
            f"（跌幅={drop:.2%}）"
        )

    return False, f"signal_b: 採納率正常（recent={recent_rate:.2%}，baseline={baseline_7d:.2%}）"


# ── 信號 C：分布偏移 ──────────────────────────────────────────────────

def _signal_distribution_drift(conn: sqlite3.Connection, adapter_block: int) -> tuple[bool, str]:
    """
    比較近 7 天 exchange_embeddings centroid 與上次訓練集涵蓋樣本 centroid。
    cosine distance > DRIFT_THRESHOLD → 觸發。
    embedding 不足（< 5 筆）→ 不觸發。
    """
    try:
        import numpy as np
    except ImportError:
        return False, "signal_c: numpy 不可用"

    # 近 7 天新進 embeddings
    new_rows = conn.execute(
        "SELECT embedding FROM exchange_embeddings "
        "WHERE created_at >= datetime('now', '-7 days') AND embedding IS NOT NULL",
    ).fetchall()

    if len(new_rows) < 5:
        return False, f"signal_c: 近 7 天 embedding 不足（{len(new_rows)}）"

    last_run_dt = _last_finetune_run_start(conn, adapter_block)
    if last_run_dt is None:
        return False, "signal_c: 尚無訓練歷史，跳過漂移檢測"

    # 上次訓練前的歷史 embeddings
    old_rows = conn.execute(
        "SELECT embedding FROM exchange_embeddings "
        "WHERE created_at < ? AND embedding IS NOT NULL",
        (last_run_dt,),
    ).fetchall()

    if len(old_rows) < 5:
        return False, f"signal_c: 歷史 embedding 不足（{len(old_rows)}）"

    def to_matrix(rows):
        vecs = []
        for r in rows:
            blob = r[0]
            v = np.frombuffer(blob, dtype=np.float32)
            if v.size > 0:
                vecs.append(v)
        return np.stack(vecs) if vecs else None

    new_mat = to_matrix(new_rows)
    old_mat = to_matrix(old_rows)
    if new_mat is None or old_mat is None:
        return False, "signal_c: embedding 解析失敗"

    new_centroid = new_mat.mean(axis=0)
    old_centroid = old_mat.mean(axis=0)

    cos_sim = float(np.dot(new_centroid, old_centroid) / (
        np.linalg.norm(new_centroid) * np.linalg.norm(old_centroid) + 1e-8
    ))
    cos_dist = 1.0 - cos_sim

    if cos_dist > DRIFT_THRESHOLD:
        return True, f"signal_c: 分布偏移 cosine_dist={cos_dist:.3f} > {DRIFT_THRESHOLD}"

    return False, f"signal_c: 分布穩定（cosine_dist={cos_dist:.3f}）"


def _last_finetune_run_start(conn: sqlite3.Connection, adapter_block: int) -> str | None:
    row = conn.execute(
        "SELECT started_at FROM finetune_runs "
        "WHERE adapter_block=? AND status='done' "
        "ORDER BY id DESC LIMIT 1",
        (adapter_block,),
    ).fetchone()
    return row[0] if row else None


# ── 工具 ─────────────────────────────────────────────────────────────────

def _count_approved(conn: sqlite3.Connection, adapter_block: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM training_samples WHERE status='approved' AND adapter_block=?",
        (adapter_block,),
    ).fetchone()
    return row[0]
