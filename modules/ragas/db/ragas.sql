-- modules/ragas/db/ragas.sql
-- PR-O-6：ragas_eval feature 專屬 schema（原 evaluation/migration_evaluation.sql）
--
-- 變動相對 PR-O-5：
-- - evaluation_results → ragas_evaluation_results（加模組前綴）
-- - retrieval_golden_set → ragas_retrieval_golden_set
-- - judge_agreement_logs 已搬至 modules/multi_judge_v2（PR-O-5），本檔不再含
--
-- 由 core.feature_registry 在 ragas_eval feature 啟用時套用；
-- 舊資料由 modules/ragas/migrations.py 一次性 INSERT...SELECT 搬移。

-- ── 評估結果（三階段共用：Layer 1 / Layer 2 / E2E）─────────────────
CREATE TABLE IF NOT EXISTS ragas_evaluation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    phase           TEXT NOT NULL,              -- 'layer1' | 'layer2' | 'e2e'
    metric_name     TEXT NOT NULL,
    metric_value    REAL NOT NULL,
    sample_id       INTEGER,                    -- 對應 training_samples.id（aggregate 時為 NULL）
    evaluator_model TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata        JSON
);

-- ── Layer 1 召回 Ground Truth ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ragas_retrieval_golden_set (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    query                   TEXT NOT NULL,
    expected_session_uuids  TEXT NOT NULL,      -- JSON array
    expected_exchange_ids   TEXT,               -- JSON array
    expected_answer         TEXT,
    annotator               TEXT,               -- 'shiba' | 'auto-by-claude'
    is_active               INTEGER NOT NULL DEFAULT 1,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes                   TEXT
);

CREATE INDEX IF NOT EXISTS idx_ragas_eval_results_phase
    ON ragas_evaluation_results(phase, metric_name);
