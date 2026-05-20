-- RAGAS 評估模組 DB Migration
-- 三張表共用於 Phase A / B / C

-- ── 評估結果（三階段共用）────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evaluation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,              -- UUID per run
    phase           TEXT NOT NULL,              -- 'layer1' | 'layer2' | 'e2e'
    metric_name     TEXT NOT NULL,              -- 'context_precision' 等
    metric_value    REAL NOT NULL,
    sample_id       INTEGER,                    -- 對應 training_samples.id（aggregate 時為 NULL）
    evaluator_model TEXT NOT NULL,              -- 'claude-sonnet-4-6' 等
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata        JSON
);

-- ── Layer 1 召回 Ground Truth ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS retrieval_golden_set (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    query                   TEXT NOT NULL,
    expected_session_uuids  TEXT NOT NULL,      -- JSON array
    expected_exchange_ids   TEXT,               -- JSON array
    expected_answer         TEXT,               -- Phase C 擴充用
    annotator               TEXT,               -- 'shiba' | 'auto-by-claude'
    is_active               INTEGER NOT NULL DEFAULT 1,  -- 0=deprecated（低分/無解題汰換留審計）
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes                   TEXT
);

-- ── Judge 一致性紀錄（Phase B）────────────────────────────────────────
CREATE TABLE IF NOT EXISTS judge_agreement_logs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id               INTEGER NOT NULL REFERENCES training_samples(id),
    votes_json              TEXT NOT NULL,      -- 3 judges 完整分數+理由
    fleiss_kappa            REAL,
    pairwise_disagreement   TEXT,               -- JSON: 哪兩位 judge 不合
    ragas_faithfulness      REAL,
    evaluated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eval_results_phase ON evaluation_results(phase, metric_name);
CREATE INDEX IF NOT EXISTS idx_judge_agree_sample ON judge_agreement_logs(sample_id);
