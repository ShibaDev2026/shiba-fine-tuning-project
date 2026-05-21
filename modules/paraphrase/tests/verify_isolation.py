"""paraphrase feature 隔離驗證（PR-O-7 Stage A / B）。

Stage A：feature off → 不註冊 paraphrase hook，背景排程 tick noop
Stage B：feature on → 註冊 paraphrase hook，可被 background.py 取出呼叫

paraphrase 不另建表（source_instruction 在核心 exchange_embeddings），
故本驗證只檢 hook 註冊狀態。

執行：
    python -m modules.paraphrase.tests.verify_isolation
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


def _bootstrap() -> None:
    reset_registry()
    reset_hooks()
    sys.modules.pop("modules.paraphrase", None)
    importlib.import_module("modules.paraphrase")


def stage_a_off() -> None:
    _bootstrap()
    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"paraphrase_service": False},
            project_root=_PROJECT_ROOT,
        )
    assert applied == [], f"Stage A 不應套用 feature，實際：{applied}"
    assert get_hook("paraphrase") is None, "Stage A 不應註冊 paraphrase hook"
    print("✓ Stage A（paraphrase off）通過：hook 未註冊，排程 tick noop")


def stage_b_on() -> None:
    _bootstrap()
    conn = _fresh_db()
    with conn:
        applied = apply_features(
            conn,
            enabled_flags={"paraphrase_service": True},
            project_root=_PROJECT_ROOT,
        )
    assert applied == ["paraphrase"], f"Stage B 應套用 paraphrase，實際：{applied}"
    assert get_hook("paraphrase") is not None, "Stage B 應註冊 paraphrase hook"
    print("✓ Stage B（paraphrase on）通過：hook 已註冊，可被 background 取用")


if __name__ == "__main__":
    stage_a_off()
    stage_b_on()
    print("\nparaphrase 隔離驗證通過 ✓")
