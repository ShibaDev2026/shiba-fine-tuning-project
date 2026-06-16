"""cmd_cutover 流程測試"""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.services.teacher_service import upsert_teacher

LAYER1_SCHEMA = Path(__file__).parent.parent.parent / "layer_1_memory" / "db" / "schema.sql"
LAYER2_SCHEMA = (Path(__file__).parent.parent.parent
                 / "layer_2_chamber" / "backend" / "db" / "schema_layer2.sql")


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(str(path)); conn.row_factory = sqlite3.Row
    conn.executescript(LAYER1_SCHEMA.read_text())
    conn.executescript(LAYER2_SCHEMA.read_text())
    upsert_teacher(conn, name="Gemini 2.5 Flash", model_id="gemini-2.5-flash",
                   api_base="https://g", keychain_ref="gemini-api-key")
    upsert_teacher(conn, name="Claude Sonnet 4.6", model_id="claude-sonnet-4-6",
                   api_base="https://api.anthropic.com", keychain_ref="anthropic-api-key")
    conn.commit(); conn.close()


def test_cutover_disables_paid_and_seeds_judges(tmp_path):
    db = tmp_path / "brain.db"
    _seed_db(db)
    from layer_2_chamber.scripts import setup_teachers

    def _open():
        c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
        return c

    with patch.object(setup_teachers, "init_layer2_db", _open):
        setup_teachers.cmd_cutover()

    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row
    # 付費全停
    paid = conn.execute(
        "SELECT name,is_active FROM teachers WHERE name IN ('Gemini 2.5 Flash','Claude Sonnet 4.6')"
    ).fetchall()
    assert all(r["is_active"] == 0 for r in paid)
    # 3 active 本地裁判、vendor 三家族
    active = conn.execute(
        "SELECT vendor FROM teachers WHERE is_active=1 AND keychain_ref IS NULL"
    ).fetchall()
    vendors = sorted(r["vendor"] for r in active)
    assert vendors == ["local-gemma", "local-glm", "local-qwen"]
    # 2 bench 停用
    bench = conn.execute(
        "SELECT COUNT(*) c FROM teachers WHERE is_active=0 AND keychain_ref IS NULL"
    ).fetchone()
    assert bench["c"] == 2


def test_resolve_api_key_local_returns_none_string():
    """本地裁判（keychain_ref=None）應回傳字串 'none'，不呼叫 Keychain"""
    from layer_2_chamber.scripts.setup_teachers import _resolve_api_key
    local = {"keychain_ref": None}
    assert _resolve_api_key(local) == "none"


def test_resolve_api_key_remote_uses_keychain():
    """遠端裁判應透過 get_api_key 取得 key"""
    from layer_2_chamber.scripts import setup_teachers
    remote = {"keychain_ref": "some-ref"}
    with patch.object(setup_teachers, "get_api_key", return_value="KEY123"):
        assert setup_teachers._resolve_api_key(remote) == "KEY123"
