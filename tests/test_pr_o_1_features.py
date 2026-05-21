"""PR-O-1 驗收：features 載入 / feature_registry API / schema_core 可套用。

對應 spec §11.1 Stage A 全關回歸的最小子集（單元層級）。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ── Features 載入 ────────────────────────────────────────────
class TestFeaturesConfig:
    def test_features_all_false_by_default(self):
        """yaml 預設值：所有 7 個 flag 皆為 false（最小核心閉環）。"""
        from shiba_config import CONFIG

        f = CONFIG.features
        assert f.shadow_gatekeeper is False
        assert f.ebbinghaus_trigger is False
        assert f.ragas_eval is False
        assert f.multi_judge_v2 is False
        assert f.paraphrase_service is False
        assert f.advanced_compressor is False
        assert f.golden_retention is False

    def test_features_is_frozen(self):
        """frozen dataclass：runtime 不可修改（防止 feature flip 走後門）。"""
        from shiba_config import CONFIG

        with pytest.raises((AttributeError, Exception)):
            CONFIG.features.shadow_gatekeeper = True  # type: ignore[misc]


# ── feature_registry API ────────────────────────────────────
class TestFeatureRegistry:
    def setup_method(self):
        """每個測試前清空 module-level registry，避免互相污染。"""
        from core.feature_registry import reset_registry

        reset_registry()

    def test_register_and_get(self):
        from core.feature_registry import FeatureSpec, get_feature, register

        spec = FeatureSpec(name="dummy", flag="dummy_flag")
        register(spec)
        assert get_feature("dummy") is spec

    def test_duplicate_register_raises(self):
        from core.feature_registry import FeatureSpec, register

        register(FeatureSpec(name="dup", flag="dup_flag"))
        with pytest.raises(ValueError, match="已註冊"):
            register(FeatureSpec(name="dup", flag="dup_flag"))

    def test_dependency_violation_fails_fast(self):
        """A 啟用但 depends_on B 未啟用 → ValueError，不靜默 skip。"""
        from core.feature_registry import FeatureSpec, apply_features, register

        register(FeatureSpec(name="A", flag="flag_a", depends_on=("flag_b",)))
        register(FeatureSpec(name="B", flag="flag_b"))

        conn = sqlite3.connect(":memory:")
        with pytest.raises(ValueError, match="flag_a.*flag_b"):
            apply_features(
                conn,
                enabled_flags={"flag_a": True, "flag_b": False},
                project_root=_PROJECT_ROOT,
            )
        conn.close()

    def test_topo_order_respects_depends_on(self):
        """init_fn 執行順序：被依賴者先跑（B 在 A 之前）。"""
        from core.feature_registry import FeatureSpec, apply_features, register

        order: list[str] = []
        register(
            FeatureSpec(
                name="A",
                flag="flag_a",
                depends_on=("flag_b",),
                init_fn=lambda _c: order.append("A"),
            )
        )
        register(
            FeatureSpec(
                name="B",
                flag="flag_b",
                init_fn=lambda _c: order.append("B"),
            )
        )

        conn = sqlite3.connect(":memory:")
        applied = apply_features(
            conn,
            enabled_flags={"flag_a": True, "flag_b": True},
            project_root=_PROJECT_ROOT,
        )
        conn.close()
        assert order == ["B", "A"]
        assert applied == ["B", "A"]

    def test_disabled_flags_skip_silently(self):
        """flag=False 的 feature 完全不執行（無 schema、無 init_fn）。"""
        from core.feature_registry import FeatureSpec, apply_features, register

        called = {"ran": False}
        register(
            FeatureSpec(
                name="off",
                flag="off_flag",
                init_fn=lambda _c: called.update(ran=True),
            )
        )

        conn = sqlite3.connect(":memory:")
        applied = apply_features(conn, enabled_flags={"off_flag": False}, project_root=_PROJECT_ROOT)
        conn.close()
        assert applied == []
        assert called["ran"] is False


# ── schema_core.sql 可套用 ───────────────────────────────────
class TestSchemaCoreApplies:
    def test_schema_core_applies_to_blank_db(self, tmp_path):
        """schema_core.sql 必須能無錯套用到空 DB，且建出預期核心表。"""
        sql_path = _PROJECT_ROOT / "config" / "db" / "schema_core.sql"
        assert sql_path.is_file(), "schema_core.sql 不存在"

        db_path = tmp_path / "core.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(sql_path.read_text(encoding="utf-8"))
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()

        # 核心表必須存在
        expected_core = {
            "projects", "sessions", "branches", "messages", "tool_executions",
            "branch_messages", "exchanges", "exchange_messages", "exchange_embeddings",
            "router_decisions", "finetune_runs",
            "teachers", "question_sets", "questions", "training_samples", "teacher_usage_logs",
        }
        missing = expected_core - tables
        assert not missing, f"核心表缺漏：{missing}"

        # feature 表名嚴禁出現
        forbidden = {
            "golden_samples",
            "gatekeeper_golden_samples",
            "ragas_runs", "ragas_results", "ragas_golden_set",
            "evaluation_runs", "evaluation_results", "retrieval_golden_set",
            "multi_judge_v2_agreement_logs", "judge_agreement_logs",
            "paraphrase_variant_sources",
        }
        leaked = forbidden & tables
        assert not leaked, f"schema_core 洩漏 feature 表：{leaked}"
