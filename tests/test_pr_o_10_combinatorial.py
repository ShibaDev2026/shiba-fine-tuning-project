"""PR-O-10：feature flag 組合驗證矩陣。

不窮舉 2^7 全組合（多數為冗餘排列），只驗證代表性切片：
  - all-off：核心 4-layer 路徑必須完整可用（schema_core 不洩 feature 表）
  - single-on：每個 feature 單獨 on 不會撞他人或意外建表
  - dep-pair：依賴鏈兩端同開（shadow+golden / ragas+v2）
  - dep-violation：應 fail-fast 的組合
  - all-on：7 旗全開能成功 apply、所有預期表+hook 到位
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from core.feature_registry import (  # noqa: E402
    apply_features,
    get_hook,
    reset_hooks,
    reset_registry,
)


_MODULES = (
    "modules.gatekeeper",
    "modules.ebbinghaus_trigger",
    "modules.multi_judge_v2",
    "modules.ragas",
    "modules.paraphrase",
    "modules.advanced_compressor",
)

_FEATURE_TABLES = {
    "shadow_gatekeeper": {"gatekeeper_golden_samples"},
    "multi_judge_v2": {"multi_judge_v2_agreement_logs"},
    "ragas_eval": {"ragas_evaluation_results", "ragas_retrieval_golden_set"},
}

_FEATURE_HOOKS = {
    "shadow_gatekeeper": "gate",
    "ebbinghaus_trigger": "trigger",
    "multi_judge_v2": "judge_score",
    "paraphrase_service": "paraphrase",
    "advanced_compressor": "compress_context",
}


def _bootstrap() -> None:
    reset_registry()
    reset_hooks()
    for m in _MODULES:
        sys.modules.pop(m, None)
        importlib.import_module(m)


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = (_PROJECT_ROOT / "config" / "db" / "schema_core.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _all_off() -> dict[str, bool]:
    return {f: False for f in (
        "shadow_gatekeeper", "ebbinghaus_trigger", "ragas_eval",
        "multi_judge_v2", "paraphrase_service", "advanced_compressor",
        "golden_retention",
    )}


def test_all_off_core_only() -> None:
    """全關 → 0 個 feature 套用，所有 feature 表+hook 都不存在。"""
    _bootstrap()
    conn = _fresh_db()
    with conn:
        applied = apply_features(conn, enabled_flags=_all_off(), project_root=_PROJECT_ROOT)
    assert applied == [], applied
    tables = _tables(conn)
    for tset in _FEATURE_TABLES.values():
        assert not (tset & tables), f"all-off 不應有 feature 表：{tset & tables}"
    for hook in _FEATURE_HOOKS.values():
        assert get_hook(hook) is None, f"all-off 不應註冊 hook {hook}"


@pytest.mark.parametrize("flag,expected_module", [
    ("ebbinghaus_trigger", "ebbinghaus_trigger"),
    ("multi_judge_v2", "multi_judge_v2"),
    ("paraphrase_service", "paraphrase"),
    ("advanced_compressor", "advanced_compressor"),
])
def test_single_feature_on(flag: str, expected_module: str) -> None:
    """單一無依賴 feature on → 只該 feature 套用 + 對應 hook 註冊。"""
    _bootstrap()
    conn = _fresh_db()
    flags = _all_off() | {flag: True}
    with conn:
        applied = apply_features(conn, enabled_flags=flags, project_root=_PROJECT_ROOT)
    assert applied == [expected_module], applied
    if flag in _FEATURE_HOOKS:
        assert get_hook(_FEATURE_HOOKS[flag]) is not None


def test_dep_pair_gatekeeper() -> None:
    """shadow_gatekeeper + golden_retention 共開 → gatekeeper 套用，gate hook 到位。"""
    _bootstrap()
    conn = _fresh_db()
    flags = _all_off() | {"shadow_gatekeeper": True, "golden_retention": True}
    with conn:
        applied = apply_features(conn, enabled_flags=flags, project_root=_PROJECT_ROOT)
    assert "gatekeeper" in applied
    assert "gatekeeper_golden_samples" in _tables(conn)
    assert get_hook("gate") is not None


def test_dep_pair_ragas() -> None:
    """ragas_eval + multi_judge_v2 共開 → 兩 feature 套用，agreement_logs + ragas 表齊備。"""
    _bootstrap()
    conn = _fresh_db()
    flags = _all_off() | {"ragas_eval": True, "multi_judge_v2": True}
    with conn:
        applied = apply_features(conn, enabled_flags=flags, project_root=_PROJECT_ROOT)
    assert set(applied) == {"ragas", "multi_judge_v2"}
    tables = _tables(conn)
    assert "multi_judge_v2_agreement_logs" in tables
    assert "ragas_evaluation_results" in tables


@pytest.mark.parametrize("missing_dep,target", [
    ("golden_retention", "shadow_gatekeeper"),
    ("multi_judge_v2", "ragas_eval"),
])
def test_dep_violation_fail_fast(missing_dep: str, target: str) -> None:
    """目標 feature on 但被依賴 off → registry 須 raise ValueError。"""
    _bootstrap()
    conn = _fresh_db()
    flags = _all_off() | {target: True}  # missing_dep 保持 False
    with pytest.raises(ValueError):
        with conn:
            apply_features(conn, enabled_flags=flags, project_root=_PROJECT_ROOT)


def test_all_on() -> None:
    """全 7 旗開 → 所有 feature 套用、所有 hook 到位、所有 feature 表建立。"""
    _bootstrap()
    conn = _fresh_db()
    flags = {k: True for k in _all_off()}
    with conn:
        applied = apply_features(conn, enabled_flags=flags, project_root=_PROJECT_ROOT)
    # gatekeeper / ebbinghaus_trigger / multi_judge_v2 / ragas / paraphrase / advanced_compressor
    assert set(applied) >= {
        "gatekeeper", "ebbinghaus_trigger", "multi_judge_v2",
        "ragas", "paraphrase", "advanced_compressor",
    }
    tables = _tables(conn)
    for tset in _FEATURE_TABLES.values():
        assert tset <= tables, f"all-on 應建 {tset}，實際缺：{tset - tables}"
    for hook in _FEATURE_HOOKS.values():
        assert get_hook(hook) is not None, f"all-on 缺 hook {hook}"
