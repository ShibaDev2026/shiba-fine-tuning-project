"""Layer 0 測試共用 fixture（autouse）。

monkeypatch shiba_db.open_connection（以及已 import 的模組參照），
讓 Layer 0 所有測試連 tmp DB，避免打 production shiba-brain.db。
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _seed_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
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
    snapshots = {
        "classifier": ("classifier-gemma3-4b", "Gemma 3 4B (Classifier)", {
            "ollama_tag": "gemma3:4b",
            "inference": {"think": False, "temperature": 0.0, "num_predict": 256},
            "prompt": {"system": "你是嚴格分類器", "user_template": None},
        }),
        "compressor": ("compressor-gemma3-4b", "Gemma 3 4B (Compressor)", {
            "ollama_tag": "gemma3:4b",
            "inference": {"think": False, "temperature": 0.1, "num_predict": 150},
            "prompt": {"system": None, "user_template": None},
        }),
        "responder": ("responder-qwen3-30b-a3b", "Qwen 3 30B Responder", {
            "ollama_tag": "qwen3:30b-a3b",
            "inference": {"think": False, "temperature": 0.7, "num_predict": 512},
            "prompt": {"system": None, "user_template": None},
        }),
    }
    for role, (stem, display, snap) in snapshots.items():
        conn.execute(
            "INSERT INTO router_config(key, value) VALUES (?, ?)",
            (f"{role}_model_yaml", stem),
        )
        conn.execute(
            """INSERT INTO model_registry
               (model_name, version_seq, is_current, content_hash,
                role, display_name, snapshot, change_kind)
               VALUES (?, 1, 1, ?, ?, ?, ?, 'created')""",
            (stem, f"hash_{role}", role, display, json.dumps(snap)),
        )
    conn.execute(
        "INSERT INTO router_config(key, value) VALUES ('ollama_status', 'online')"
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _isolate_layer0_config_db(tmp_path, monkeypatch):
    """所有 layer0 測試自動套：open_connection → tmp DB；測前清 cache。"""
    db = tmp_path / "layer0_test.db"
    _seed_db(db)

    import shiba_db
    from layer_0_router import _config, telemetry

    # shiba_db.open_connection 已被各模組 `from shiba_db import open_connection`，
    # 須在每個已 import 的模組命名空間各自 patch
    def _patched_open(role="writer", timeout=30.0):
        conn = sqlite3.connect(str(db), timeout=timeout, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(shiba_db, "open_connection", _patched_open)
    monkeypatch.setattr(_config, "open_connection", _patched_open)
    monkeypatch.setattr(telemetry, "open_connection", _patched_open)

    _config.invalidate_cache()
    yield db
    _config.invalidate_cache()
