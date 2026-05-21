"""ebbinghaus_trigger feature 隔離驗證（PR-O-4 Stage A / B）。

Stage A：feature off，runner 不應有 "trigger" hook，basic 策略可獨立運作
Stage B：feature on，"trigger" hook 註冊為 v2 should_trigger（三信號）

執行：
    python -m modules.ebbinghaus_trigger.tests.verify_isolation
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


def stage_a_all_off() -> None:
    """feature off：apply_features 不註冊 trigger hook，basic 策略可用。"""
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.ebbinghaus_trigger", None)
    importlib.import_module("modules.ebbinghaus_trigger")

    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"ebbinghaus_trigger": False},
            project_root=_PROJECT_ROOT,
        )
    assert applied == [], f"Stage A 不應套用任何 feature，實際：{applied}"
    assert get_hook("trigger") is None, "Stage A 不應註冊 trigger hook"

    # basic 策略應可直接呼叫且回傳 should_train=False（樣本不足）
    from layer_3_pipeline.trigger_policy_basic import should_trigger_basic
    decision = should_trigger_basic(conn, adapter_block=1)
    assert decision.should_train is False, "空 DB 下 basic 應回 False"
    assert "approved=0" in decision.reason
    print("✓ Stage A（ebbinghaus_trigger off）通過：basic fallback 運作正常")


def stage_b_only_ebbinghaus() -> None:
    """feature on：trigger hook 註冊為 v2 should_trigger。"""
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.ebbinghaus_trigger", None)
    importlib.import_module("modules.ebbinghaus_trigger")

    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"ebbinghaus_trigger": True},
            project_root=_PROJECT_ROOT,
        )
    assert applied == ["ebbinghaus_trigger"], f"Stage B 應套用 ebbinghaus_trigger，實際：{applied}"
    trigger_fn = get_hook("trigger")
    assert trigger_fn is not None, "Stage B 應註冊 trigger hook"

    # v2 hook 應可直接呼叫
    decision = trigger_fn(conn, adapter_block=1)
    assert decision.should_train is False, "空 DB 下 v2 也應回 False"
    print("✓ Stage B（only ebbinghaus_trigger）通過：v2 hook 註冊並運作")


if __name__ == "__main__":
    stage_a_all_off()
    stage_b_only_ebbinghaus()
    print("\nebbinghaus_trigger 隔離驗證通過 ✓")
