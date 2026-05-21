"""multi_judge_v2 feature 隔離驗證（PR-O-5 Stage A / B）。

Stage A：feature off → 無 multi_judge_v2_* 表、無 judge_score hook，v1 可用
Stage B：feature on → multi_judge_v2_agreement_logs 存在 + hook 註冊為 v2

執行：
    python -m modules.multi_judge_v2.tests.verify_isolation
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
    get_hook,
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


def stage_a_all_off() -> None:
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.multi_judge_v2", None)
    importlib.import_module("modules.multi_judge_v2")

    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"multi_judge_v2": False},
            project_root=_PROJECT_ROOT,
        )
    assert applied == [], f"Stage A 不應套用 feature，實際：{applied}"
    assert "multi_judge_v2_agreement_logs" not in _tables(conn), \
        "Stage A 不應出現 multi_judge_v2_agreement_logs"
    assert get_hook("judge_score") is None, "Stage A 不應註冊 judge_score hook"
    print("✓ Stage A（multi_judge_v2 off）通過：v1 為核心 fallback")


def stage_b_only_v2() -> None:
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.multi_judge_v2", None)
    importlib.import_module("modules.multi_judge_v2")

    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"multi_judge_v2": True},
            project_root=_PROJECT_ROOT,
        )
    assert applied == ["multi_judge_v2"], f"Stage B 應套用 multi_judge_v2，實際：{applied}"
    assert "multi_judge_v2_agreement_logs" in _tables(conn), \
        "Stage B 應建立 multi_judge_v2_agreement_logs"
    assert get_hook("judge_score") is not None, "Stage B 應註冊 judge_score hook"
    print("✓ Stage B（only multi_judge_v2）通過：v2 strategy 注入")


if __name__ == "__main__":
    stage_a_all_off()
    stage_b_only_v2()
    print("\nmulti_judge_v2 隔離驗證通過 ✓")
