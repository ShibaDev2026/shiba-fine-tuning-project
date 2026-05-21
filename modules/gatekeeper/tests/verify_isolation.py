"""gatekeeper feature 隔離驗證（PR-O-3 Stage A / B）。

執行兩階段驗證，符合 spec §6.0：
- Stage A：所有 feature flag 全關，核心 schema 套用後不得出現 gatekeeper_* 表
- Stage B：只開 shadow_gatekeeper + golden_retention，核心仍可運作，
  且 "gate" hook 已註冊、gatekeeper_golden_samples 表存在

直接執行：
    python -m modules.gatekeeper.tests.verify_isolation
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
    """in-memory DB + 核心 schema。"""
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
    """所有 flag 全關：apply_features 不得套用任何 feature schema。"""
    reset_registry()
    reset_hooks()
    # 觸發 gatekeeper 自我登記（reset_registry 後重新 import 才會重跑 register()）
    sys.modules.pop("modules.gatekeeper", None)
    importlib.import_module("modules.gatekeeper")

    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"shadow_gatekeeper": False, "golden_retention": False},
            project_root=_PROJECT_ROOT,
        )
    assert applied == [], f"Stage A 不應套用任何 feature，實際：{applied}"
    assert "gatekeeper_golden_samples" not in _tables(conn), (
        "Stage A 不應出現 gatekeeper_golden_samples 表"
    )
    assert get_hook("gate") is None, "Stage A 不應註冊 gate hook"
    print("✓ Stage A（all flags off）通過：核心未受 gatekeeper 影響")


def stage_b_only_gatekeeper() -> None:
    """只開 shadow_gatekeeper + golden_retention：核心 + gatekeeper schema 並存。"""
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.gatekeeper", None)
    importlib.import_module("modules.gatekeeper")

    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"shadow_gatekeeper": True, "golden_retention": True},
            project_root=_PROJECT_ROOT,
        )
    assert applied == ["gatekeeper"], f"Stage B 應只套用 gatekeeper，實際：{applied}"
    tables = _tables(conn)
    assert "gatekeeper_golden_samples" in tables, "Stage B 應建立 gatekeeper_golden_samples"
    # 核心表仍在
    for required in ("messages", "training_samples", "finetune_runs"):
        assert required in tables, f"核心表 {required} 缺漏"
    assert get_hook("gate") is not None, "Stage B 應註冊 gate hook"
    print("✓ Stage B（only shadow_gatekeeper + golden_retention）通過：feature 與核心並存")


def stage_b_missing_dependency_fails() -> None:
    """只開 shadow_gatekeeper、不開 golden_retention：apply_features 應拋錯。"""
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.gatekeeper", None)
    importlib.import_module("modules.gatekeeper")

    conn = _fresh_db()
    try:
        apply_features(
            conn,
            enabled_flags={"shadow_gatekeeper": True, "golden_retention": False},
            project_root=_PROJECT_ROOT,
        )
    except ValueError as e:
        assert "golden_retention" in str(e), f"錯誤訊息應提及 golden_retention：{e}"
        print("✓ 依賴缺失正確 fail fast：", e)
        return
    raise AssertionError("缺 golden_retention 時應拋 ValueError")


if __name__ == "__main__":
    stage_a_all_off()
    stage_b_only_gatekeeper()
    stage_b_missing_dependency_fails()
    print("\n全部隔離驗證通過 ✓")
