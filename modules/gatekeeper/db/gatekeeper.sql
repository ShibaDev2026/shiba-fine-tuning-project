-- modules/gatekeeper/db/gatekeeper.sql
-- PR-O-3：shadow_gatekeeper + golden_retention feature 專屬 schema
--
-- 原 layer_2_chamber/backend/db/schema_layer2.sql 內 golden_samples 表改名為
-- gatekeeper_golden_samples（加模組前綴），與核心 schema 解耦。
-- 由 core.feature_registry.apply_features 於 shadow_gatekeeper 啟用時套用。
--
-- 強約束：本檔僅含 gatekeeper feature 自身的表/索引，不得 reference
-- 任何其他 feature 表；對核心表只允許 FK 反向參照（如 training_samples）。

-- ── 黃金樣本集（C：retention/防遺忘）─────────────────────────────────
-- 凍結歷史高分樣本（score≥9 的 approved），shadow A/B 時以此集合驗證新模型
-- 是否在舊知識上維持水準（≥85% 不退化才放行），對抗災難性遺忘。
CREATE TABLE IF NOT EXISTS gatekeeper_golden_samples (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_sample_id INTEGER NOT NULL REFERENCES training_samples(id),
    instruction      TEXT NOT NULL,
    input            TEXT NOT NULL DEFAULT '',
    expected_output  TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    score            REAL NOT NULL,
    frozen_at        TEXT NOT NULL DEFAULT (datetime('now')),
    is_active        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_gatekeeper_golden_event
    ON gatekeeper_golden_samples(event_type, is_active);
