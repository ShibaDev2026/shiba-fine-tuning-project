"""tests/layer2/test_refiner_service.py — 精煉器單元測試（3 個）"""

import sqlite3
import pytest

from layer_2_chamber.backend.services.refiner_service import (
    _is_ollama_available,
    _call_qwen,
    refine_pending_raw_samples,
    scrub_pii,
    scrub_sample_fields,
)


# ── Test 1：PII scrubbing ─────────────────────────────────────────────

def test_pii_scrubbing():
    """路徑與本機 IP 應被替換，原始值不得出現在輸出中"""
    raw = "請幫我看 /Users/surpend/Developer/my-project/src/main.py 的問題，伺服器在 192.168.1.5"
    result = scrub_pii(raw)

    assert "/Users/surpend" not in result
    assert "192.168.1.5" not in result
    assert "<PROJECT_PATH>" in result
    assert "<LOCAL_IP>" in result


# ── Test 2：自包含通過時 refined_instruction 為 None ──────────────────

def test_self_contained_passthrough(monkeypatch):
    """Qwen 回報 is_self_contained=true 時，refined_instruction 應為 None"""
    import json

    monkeypatch.setattr(
        "layer_2_chamber.backend.services.refiner_service._is_ollama_available",
        lambda url: True,
    )
    monkeypatch.setattr(
        "layer_2_chamber.backend.services.refiner_service._call_qwen",
        lambda *a, **kw: json.dumps({
            "is_self_contained": True,
            "rewritten_instruction": None,
            "expected_answer": "使用 git rebase -i 進行互動式 rebase",
        }),
    )

    from layer_2_chamber.backend.services.refiner_service import refine_sample
    result = refine_sample(
        instruction="如何用 git rebase 合併 commit？",
        input_text="",
        output="使用 git rebase -i HEAD~3",
    )

    assert result["refined_instruction"] is None
    assert result["instruction"] == "如何用 git rebase 合併 commit？"
    assert result["expected_answer"] is not None


# ── Test 3：Ollama 離線時 fallback ────────────────────────────────────

def test_fallback_when_ollama_down(monkeypatch):
    """Ollama 不可用時，raw 樣本應直接升為 pending，refined_instruction 為 NULL"""
    monkeypatch.setattr(
        "layer_2_chamber.backend.services.refiner_service._is_ollama_available",
        lambda url: False,
    )

    # 使用 file-based DB 讓 conn_factory 每次回新連線（避免 close 後失效）
    import tempfile, os
    db_file = tempfile.mktemp(suffix=".db")

    def make_conn():
        c = sqlite3.connect(db_file)
        c.row_factory = sqlite3.Row
        return c

    setup_conn = make_conn()
    setup_conn.executescript("""
        CREATE TABLE training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'layer1_bridge',
            session_id TEXT,
            question_id INTEGER,
            teacher_id INTEGER,
            event_type TEXT NOT NULL DEFAULT 'code_gen',
            instruction TEXT NOT NULL,
            input TEXT NOT NULL DEFAULT '',
            output TEXT NOT NULL,
            refined_instruction TEXT,
            expected_answer TEXT,
            pii_scrubbed INTEGER NOT NULL DEFAULT 0,
            score REAL,
            score_reason TEXT,
            status TEXT NOT NULL DEFAULT 'raw',
            adapter_block INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            reviewed_at TEXT
        );
        INSERT INTO training_samples (instruction, output) VALUES ('問題一', '回答一');
        INSERT INTO training_samples (instruction, output) VALUES ('問題二', '回答二');
    """)
    setup_conn.close()

    stats = refine_pending_raw_samples(make_conn)

    assert stats["fallback"] == 2
    assert stats["refined"] == 0
    assert stats["failed"] == 0

    verify_conn = make_conn()
    rows = verify_conn.execute(
        "SELECT status, refined_instruction FROM training_samples ORDER BY id"
    ).fetchall()
    verify_conn.close()
    os.unlink(db_file)

    for row in rows:
        assert row["status"] == "pending"
        assert row["refined_instruction"] is None
