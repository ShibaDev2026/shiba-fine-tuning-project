-- modules/multi_judge_v2/db/multi_judge_v2.sql
-- PR-O-5：multi_judge_v2 feature 專屬 schema
--
-- 原 evaluation/migration_evaluation.sql 內 judge_agreement_logs 表概念搬至此處，
-- 加 multi_judge_v2_ 前綴與核心解耦。v2 strategy 啟用時才寫入；
-- v1 strategy（services/multi_judge.py）完全不寫 log，保持核心輕量。

CREATE TABLE IF NOT EXISTS multi_judge_v2_agreement_logs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id               INTEGER NOT NULL REFERENCES training_samples(id),
    votes_json              TEXT NOT NULL,      -- 完整 vendor / score / reason
    vendor_diversity        INTEGER NOT NULL,   -- 不同 vendor 數（v2 要求 ≥2）
    fleiss_kappa            REAL,               -- 後續批次計算回填
    pairwise_disagreement   TEXT,               -- JSON: 哪兩位 judge 不合
    ragas_faithfulness      REAL,
    evaluated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_multi_judge_v2_sample
    ON multi_judge_v2_agreement_logs(sample_id);
