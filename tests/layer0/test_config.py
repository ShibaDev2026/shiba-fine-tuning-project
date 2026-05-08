"""Layer 0 _config.py 單元測試（Step 3.1 TDD）。

驗 load_active_snapshot / is_local_enabled / invalidate_cache 三函數：
- 雙表 join：router_config 取 stem → model_registry is_current=1 取 snapshot
- raise on miss（DB 失敗交給上層 fallback Claude）
- 50ms in-process cache（hot path 不重打 DB）
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── 共用 fixture ──────────────────────────────────────────────
SAMPLE_SNAPSHOT = {
    "description": "test classifier",
    "ollama_tag": "gemma3:4b",
    "inference": {"think": False, "temperature": 0.0},
    "prompt": {"system": "you are a classifier", "user_template": None},
    "meta": {"role": "classifier"},
    "maintenance": {"yaml_version": 1, "added_at": "2026-05-08", "notes": ""},
}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """建一個 tmp SQLite，含 router_config + model_registry，塞 classifier 範例資料。

    並 monkeypatch _config.DB_PATH 指向這顆 tmp DB，以及清除 cache。
    """
    p = tmp_path / "test.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        """
        CREATE TABLE router_config (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE model_registry (
            id            INTEGER PRIMARY KEY,
            model_name    TEXT NOT NULL,
            version_seq   INTEGER NOT NULL,
            is_current    INTEGER NOT NULL DEFAULT 0,
            content_hash  TEXT NOT NULL,
            role          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            snapshot      TEXT NOT NULL,
            change_kind   TEXT NOT NULL,
            recorded_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (model_name, version_seq),
            UNIQUE (model_name, content_hash)
        );
        CREATE UNIQUE INDEX uq_registry_current
            ON model_registry(model_name) WHERE is_current = 1;
        """
    )
    conn.execute(
        "INSERT INTO router_config(key, value) VALUES (?, ?)",
        ("classifier_model_yaml", "classifier-gemma3-4b"),
    )
    conn.execute(
        "INSERT INTO router_config(key, value) VALUES (?, ?)",
        ("ollama_status", "online"),
    )
    conn.execute(
        """INSERT INTO model_registry
           (model_name, version_seq, is_current, content_hash, role,
            display_name, snapshot, change_kind)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "classifier-gemma3-4b",
            1,
            1,
            "hash_v1",
            "classifier",
            "Gemma 3 4B (Classifier)",
            json.dumps(SAMPLE_SNAPSHOT),
            "created",
        ),
    )
    conn.commit()
    conn.close()

    # 指 _config.DB_PATH 到 tmp DB；清 cache 防汙染
    from layer_0_router import _config

    monkeypatch.setattr(_config, "DB_PATH", str(p))
    _config.invalidate_cache()
    return p


# ── load_active_snapshot ──────────────────────────────────────
class TestLoadActiveSnapshot:
    def test_returns_full_snapshot_dict(self, tmp_db):
        """happy path：回完整 snapshot dict（含 ollama_tag / inference / prompt）"""
        from layer_0_router._config import load_active_snapshot

        snap = load_active_snapshot("classifier")
        assert snap["ollama_tag"] == "gemma3:4b"
        assert snap["inference"]["think"] is False
        assert snap["prompt"]["system"] == "you are a classifier"

    def test_missing_router_config_key_raises(self, tmp_db):
        """router_config 沒有對應 role 的 key → RuntimeError（lifespan sync 漏）"""
        from layer_0_router._config import load_active_snapshot

        with pytest.raises(RuntimeError, match="router_config"):
            load_active_snapshot("compressor")  # fixture 只塞 classifier

    def test_missing_registry_row_raises(self, tmp_db):
        """router_config 指向的 stem 在 model_registry 找不到 is_current=1 → RuntimeError"""
        # 把 classifier 的 is_current 翻成 0 → registry 沒任何 current row
        conn = sqlite3.connect(tmp_db)
        conn.execute("UPDATE model_registry SET is_current=0")
        conn.commit()
        conn.close()

        from layer_0_router._config import load_active_snapshot, invalidate_cache

        invalidate_cache()
        with pytest.raises(RuntimeError, match="model_registry"):
            load_active_snapshot("classifier")


# ── is_local_enabled ──────────────────────────────────────────
class TestIsLocalEnabled:
    @pytest.mark.parametrize(
        "status,expected",
        [("online", True), ("offline", False)],
    )
    def test_status_value_drives_result(self, tmp_db, status, expected):
        conn = sqlite3.connect(tmp_db)
        conn.execute("UPDATE router_config SET value=? WHERE key='ollama_status'", (status,))
        conn.commit()
        conn.close()

        from layer_0_router._config import is_local_enabled

        assert is_local_enabled() is expected

    def test_missing_key_returns_false(self, tmp_db):
        """router_config 沒 ollama_status key → False（保守 default 走 Claude）"""
        conn = sqlite3.connect(tmp_db)
        conn.execute("DELETE FROM router_config WHERE key='ollama_status'")
        conn.commit()
        conn.close()

        from layer_0_router._config import is_local_enabled

        assert is_local_enabled() is False


# ── split_inference ───────────────────────────────────────────
class TestSplitInference:
    def test_full_yaml_inference_splits_three_buckets(self):
        """yaml 完整 11 keys 拆成 (options 7, keep_alive, think) — timeout_seconds 丟棄"""
        from layer_0_router._config import split_inference

        full = {
            "think": False, "num_ctx": 4096, "temperature": 0.0,
            "top_p": 1.0, "top_k": 40, "repeat_penalty": 1.0,
            "num_predict": 256, "stop": [], "keep_alive": "10m",
            "timeout_seconds": 30,
        }
        opts, keep_alive, think = split_inference(full)
        assert keep_alive == "10m"
        assert think is False  # think 抽出到 body 頂層
        assert "keep_alive" not in opts
        assert "think" not in opts  # think 不再留在 options（Ollama 會忽略）
        assert "timeout_seconds" not in opts  # 丟棄，不進 options
        assert opts == {
            "num_ctx": 4096, "temperature": 0.0,
            "top_p": 1.0, "top_k": 40, "repeat_penalty": 1.0,
            "num_predict": 256, "stop": [],
        }

    def test_none_or_empty_returns_empty(self):
        from layer_0_router._config import split_inference

        assert split_inference(None) == ({}, None, None)
        assert split_inference({}) == ({}, None, None)

    def test_does_not_mutate_input(self):
        """不可破壞傳入 dict（snapshot cache 共用同物件，會污染下次呼叫）"""
        from layer_0_router._config import split_inference

        src = {"think": False, "keep_alive": "5m", "timeout_seconds": 30}
        snapshot_before = dict(src)
        split_inference(src)
        assert src == snapshot_before


# ── cache 行為 ────────────────────────────────────────────────
class TestCache:
    def test_invalidate_cache_forces_db_reread(self, tmp_db):
        """invalidate_cache 後第二次呼叫應拿到 DB 新值（驗 cache 真的會被清）"""
        from layer_0_router._config import load_active_snapshot, invalidate_cache

        # 第一次：拿到 v1
        snap1 = load_active_snapshot("classifier")
        assert snap1["ollama_tag"] == "gemma3:4b"

        # DB 改 snapshot 但不 invalidate → cache 命中，仍是 v1
        new_snap = {**SAMPLE_SNAPSHOT, "ollama_tag": "gemma3:12b"}
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "UPDATE model_registry SET snapshot=? WHERE model_name='classifier-gemma3-4b'",
            (json.dumps(new_snap),),
        )
        conn.commit()
        conn.close()

        snap_cached = load_active_snapshot("classifier")
        assert snap_cached["ollama_tag"] == "gemma3:4b"  # 仍是舊值（cache 命中）

        # invalidate 後再讀 → 拿到新值
        invalidate_cache()
        snap_fresh = load_active_snapshot("classifier")
        assert snap_fresh["ollama_tag"] == "gemma3:12b"
