"""ragas feature 隔離驗證（PR-O-6 Stage A / B）。

Stage A：feature off → 無 ragas_* 表，核心路徑不受影響
Stage B：feature on（含 depends_on=multi_judge_v2）→ ragas_evaluation_results /
        ragas_retrieval_golden_set 建立完成

執行：
    python -m modules.ragas.tests.verify_isolation
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))

from core.feature_registry import (  # noqa: E402
    apply_features,
    reset_hooks,
    reset_registry,
)


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = (_PROJECT_ROOT / "config" / "db" / "schema_core.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _bootstrap() -> None:
    reset_registry()
    reset_hooks()
    # ragas depends_on=multi_judge_v2 → 先載入被依賴方再載入本身
    for mod in ("modules.multi_judge_v2", "modules.ragas"):
        sys.modules.pop(mod, None)
        importlib.import_module(mod)


def stage_a_all_off() -> None:
    _bootstrap()
    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"ragas_eval": False, "multi_judge_v2": False},
            project_root=_PROJECT_ROOT,
        )
    assert applied == [], f"Stage A 不應套用 feature，實際：{applied}"
    tables = _tables(conn)
    for t in ("ragas_evaluation_results", "ragas_retrieval_golden_set"):
        assert t not in tables, f"Stage A 不應出現 {t}"
    print("✓ Stage A（ragas off）通過：核心路徑無 ragas_* 表")


def stage_b_only_ragas() -> None:
    _bootstrap()
    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"ragas_eval": True, "multi_judge_v2": True},
            project_root=_PROJECT_ROOT,
        )
    assert set(applied) == {"ragas", "multi_judge_v2"}, \
        f"Stage B 應套用 ragas + multi_judge_v2，實際：{applied}"
    tables = _tables(conn)
    for t in ("ragas_evaluation_results", "ragas_retrieval_golden_set"):
        assert t in tables, f"Stage B 應建立 {t}"
    print("✓ Stage B（ragas + multi_judge_v2 on）通過：ragas_* 表已建立")


def stage_c_dep_violation() -> None:
    """ragas on 但 multi_judge_v2 off → 應 fail fast。"""
    _bootstrap()
    conn = _fresh_db()
    try:
        with conn:
            apply_features(
                conn,
                enabled_flags={"ragas_eval": True, "multi_judge_v2": False},
                project_root=_PROJECT_ROOT,
            )
    except Exception as e:
        print(f"✓ Stage C（dep violation）通過：{type(e).__name__}: {e}")
        return
    raise AssertionError("Stage C 應拋錯但未拋")


if __name__ == "__main__":
    stage_a_all_off()
    stage_b_only_ragas()
    stage_c_dep_violation()
    print("\nragas 隔離驗證通過 ✓")
