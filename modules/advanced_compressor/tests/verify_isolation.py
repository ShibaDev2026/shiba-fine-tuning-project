"""advanced_compressor 隔離驗證（PR-O-8 Stage A / B）。

Stage A：feature off → 無 hook，compress_context 走截斷 fallback
Stage B：feature on → hook 註冊，compress_context 透過 hook 走 advanced

執行：
    python -m modules.advanced_compressor.tests.verify_isolation
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
    register_hook,
    reset_hooks,
    reset_registry,
)
from layer_0_router.compressor import compress_context  # noqa: E402


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = (_PROJECT_ROOT / "config" / "db" / "schema_core.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    return conn


def _bootstrap() -> None:
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.advanced_compressor", None)
    importlib.import_module("modules.advanced_compressor")


def stage_a_off() -> None:
    _bootstrap()
    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"advanced_compressor": False},
            project_root=_PROJECT_ROOT,
        )
    assert applied == [], f"Stage A 不應套用 feature，實際：{applied}"
    assert get_hook("compress_context") is None, "Stage A 不應註冊 hook"
    long_ctx = "x" * 500
    assert compress_context(long_ctx) == long_ctx[:300] + "...", "Stage A 應走截斷"
    print("✓ Stage A（advanced_compressor off）通過：fallback 截斷生效")


def stage_b_on() -> None:
    _bootstrap()
    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"advanced_compressor": True},
            project_root=_PROJECT_ROOT,
        )
    assert applied == ["advanced_compressor"], f"Stage B 應套用 advanced_compressor，實際：{applied}"
    hook = get_hook("compress_context")
    assert hook is not None, "Stage B 應註冊 compress_context hook"
    # 蓋掉真 Ollama 呼叫，只測 hook wiring
    reset_hooks()
    register_hook("compress_context", lambda ctx: "ADV-OK")
    assert compress_context("x" * 500) == "ADV-OK", "Stage B 應走 hook"
    print("✓ Stage B（advanced_compressor on）通過：hook wired 並可呼叫")


if __name__ == "__main__":
    stage_a_off()
    stage_b_on()
    print("\nadvanced_compressor 隔離驗證通過 ✓")
