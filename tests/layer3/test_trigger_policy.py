# tests/layer3/test_trigger_policy.py
"""trigger_policy 信號 C round-trip 測試（A2 修正後）"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "layer_1_memory"))

from layer_3_pipeline.trigger_policy import _signal_distribution_drift  # noqa: E402
from lib import db as memory_db  # noqa: E402

_SCHEMA_SQL = _ROOT / "layer_1_memory" / "db" / "schema.sql"


def _make_db(tmp_path: Path) -> Path:
    """建立臨時 DB 並載入完整 schema"""
    db_file = tmp_path / "shiba.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(_SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return db_file


def test_signal_c_round_trip_embedding_format(tmp_path):
    """upsert_exchange_embedding (json.dumps) → _signal_distribution_drift (json.loads)
    應能還原 vector 並計算出 cosine 距離（不報「embedding 解析失敗」）"""
    db_file = _make_db(tmp_path)

    with patch("lib.db.get_db_path", return_value=db_file):
        # 寫入 6 筆「舊」 + 6 筆「新」embedding，向量內容刻意不同以製造 drift
        for i in range(6):
            memory_db.upsert_exchange_embedding(
                session_uuid=f"old-{i}",
                instruction=f"舊指令 {i}",
                commands=f"echo old{i}",
                embedding=[1.0, 0.0, 0.0, 0.0],
            )
        for i in range(6):
            memory_db.upsert_exchange_embedding(
                session_uuid=f"new-{i}",
                instruction=f"新指令 {i}",
                commands=f"echo new{i}",
                embedding=[0.0, 1.0, 0.0, 0.0],
            )

    conn = sqlite3.connect(str(db_file))
    # 把前 6 筆 created_at 推到 30 天前；後 6 筆保持 now（在 7 天視窗內）
    conn.execute(
        "UPDATE exchange_embeddings SET created_at = datetime('now', '-30 days') "
        "WHERE session_uuid LIKE 'old-%'"
    )
    # 寫一筆已完成 finetune_run 作分界點（15 天前），讓 _last_finetune_run_start 有結果
    conn.execute(
        "INSERT INTO finetune_runs (adapter_block, status, started_at) "
        "VALUES (1, 'done', datetime('now', '-15 days'))"
    )
    conn.commit()

    triggered, reason = _signal_distribution_drift(conn, adapter_block=1)
    conn.close()

    assert "embedding 解析失敗" not in reason, f"格式對齊失敗：{reason}"
    assert "numpy 不可用" not in reason, "測試環境缺 numpy"
    assert "cosine_dist=" in reason, f"未進入 cosine 計算路徑：{reason}"
    # 兩組正交向量 → cos_dist ≈ 1.0，應觸發 drift
    assert triggered is True, f"正交向量未觸發 drift：{reason}"


# ── C2：Ebbinghaus 視窗模擬測試 ──────────────────────────────────────────

from layer_3_pipeline.trigger_policy import EBBINGHAUS_DAYS, EBBINGHAUS_WINDOW


def test_ebbinghaus_windows_covered_by_6h_scheduler():
    """
    C2 時序模擬：以 6h 間隔（0.25 天）掃描 0→31 天，確認每個 Ebbinghaus 間隔
    的視窗 [interval-WINDOW, interval+WINDOW] 內至少有一次 check 點落入。
    """
    check_interval = 0.25  # 6h = 0.25 天
    checks = [i * check_interval for i in range(int(31 / check_interval) + 1)]

    for interval in EBBINGHAUS_DAYS:
        lo, hi = interval - EBBINGHAUS_WINDOW, interval + EBBINGHAUS_WINDOW
        hit = any(lo <= t <= hi for t in checks)
        assert hit, (
            f"Ebbinghaus day={interval} 視窗 [{lo}, {hi}] 在 6h 排程下沒有任何 check 點，"
            f"請縮小 EBBINGHAUS_WINDOW 或加密 finetune_check 頻率"
        )


def test_ebbinghaus_windows_no_overlap():
    """
    C2 完整性：相鄰 Ebbinghaus 視窗不重疊（避免同一 elapsed 觸發兩次）。
    """
    windows = [(d - EBBINGHAUS_WINDOW, d + EBBINGHAUS_WINDOW) for d in EBBINGHAUS_DAYS]
    for i in range(len(windows) - 1):
        hi_prev = windows[i][1]
        lo_next = windows[i + 1][0]
        assert hi_prev <= lo_next, (
            f"Ebbinghaus day={EBBINGHAUS_DAYS[i]} 和 day={EBBINGHAUS_DAYS[i+1]} 視窗重疊："
            f"{windows[i]} vs {windows[i+1]}，EBBINGHAUS_WINDOW={EBBINGHAUS_WINDOW} 過寬"
        )
