#!/usr/bin/env python3
"""PR2 E2E smoke：在 backend container 內驗證 Step 5/6 真實環境行為。

執行：
    docker exec shiba-fine-tuning-project-backend-1 python /app/scripts/e2e_pr2_smoke.py

涵蓋：
    E2E-1 (Step 6 happy path)：mock 兩 judge 全 approve →
        驗證 training_samples 的 status/score/weight 三欄在同一事務內原子寫入。
    E2E-2 (Step 5 failure path)：session_stop_hook C 段模擬 raise →
        驗證 A+B 段（sessions/messages）也被整體 rollback（讀法 B）。

本腳本用 /tmp/e2e_pr2.db 臨時 DB，不污染 production data/shiba-brain.db。
"""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, '/app')

# ---- Setup：臨時 DB + monkey patch shiba_db.open_connection ----
TMP_DB = Path('/tmp/e2e_pr2.db')
TMP_DB.unlink(missing_ok=True)

schema = Path('/app/layer_1_memory/db/schema.sql').read_text()
init = sqlite3.connect(TMP_DB)
init.executescript(schema)
init.executescript("""
CREATE TABLE IF NOT EXISTS training_samples (
    id INTEGER PRIMARY KEY,
    instruction TEXT, input TEXT, output TEXT,
    score REAL, score_reason TEXT, status TEXT,
    weight REAL, reviewed_at TEXT, session_id TEXT
);
INSERT INTO training_samples (id, status, weight) VALUES (1, 'pending', NULL);
""")
init.commit()
init.close()

import shiba_db
_orig_open = shiba_db.open_connection

def _patched_open(role='writer', **kwargs):
    conn = sqlite3.connect(TMP_DB)
    conn.row_factory = sqlite3.Row
    for pragma in shiba_db._PRAGMAS:
        conn.execute(pragma)
    return conn

shiba_db.open_connection = _patched_open


# ============ E2E-1: multi_judge_score 三欄原子寫入（Step 6 happy path）============
print("=== E2E-1: multi_judge_score happy path ===")
from layer_2_chamber.backend.services import multi_judge

mock_votes = [
    {"teacher_id": 1, "teacher_name": "MockA", "vendor": "v_a",
     "score": 9.0, "approved": True, "reason": "good"},
    {"teacher_id": 2, "teacher_name": "MockB", "vendor": "v_b",
     "score": 8.5, "approved": True, "reason": "ok"},
]

conn = shiba_db.open_connection()
# _collect_votes 已被 mock，teachers/available 不會真的被使用 → 一併 mock get_active_teachers
# 與 is_quota_available 以避開「teachers 資料表不存在於臨時 DB」的噪音。
with patch.object(multi_judge, '_collect_votes', return_value=mock_votes), \
     patch.object(multi_judge, '_check_shiba_accepted', return_value=False), \
     patch.object(multi_judge, 'get_active_teachers', return_value=[]), \
     patch.object(multi_judge, 'is_quota_available', return_value=True):
    result = multi_judge.multi_judge_score(
        conn, sample_id=1, instruction='x', input_text='', output='y'
    )
print(f"   result: status={result['status']} score={result['score']:.2f} weight={result['weight']}")
row = conn.execute(
    "SELECT status, score, weight FROM training_samples WHERE id=1"
).fetchone()
print(f"   DB:     status={row['status']} score={row['score']:.2f} weight={row['weight']}")
assert row['status'] == 'approved', f"FAIL: status={row['status']}"
assert abs(row['score'] - 8.75) < 0.01, f"FAIL: score={row['score']}"
assert row['weight'] == 1.0, f"FAIL: weight={row['weight']}"
print("   ✅ E2E-1 通過：三欄原子寫入（status/score/weight）")
conn.close()


# ============ E2E-2: session_stop_hook C 段 raise → 整體 rollback（Step 5 failure path）============
print("\n=== E2E-2: session_stop_hook C 段 raise → 整體 rollback ===")
from layer_1_memory.lib.db import (
    upsert_project, upsert_session, update_session_stats,
    insert_message, deactivate_old_branches,
)

probe = shiba_db.open_connection()
pre_s = probe.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
pre_m = probe.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
probe.close()

# 重現 session_stop_hook PR2 後的 4 段結構，C 段故意 raise
try:
    with shiba_db.get_connection() as c:
        # A 段
        try:
            pid = upsert_project(c, name='e2e', path='/tmp/e2e', hash_='hash_e2e')
            sid = upsert_session(c, project_id=pid, uuid='e2e-uuid-001')
            update_session_stats(
                c, session_id=sid, exchange_count=1,
                files_modified=0, commits=0, tool_counts={},
                event_types=['test'], ended_at='2026-05-17T00:00:00+00:00',
            )
        except Exception as e:
            print(f"   A 段失敗：{e}")
            raise
        # B 段
        try:
            insert_message(
                c, session_id=sid, uuid='msg-uuid-001', parent_uuid=None,
                role='user', content='hi', raw_content='hi',
                input_tokens=0, output_tokens=0,
                cache_creation_input_tokens=0, cache_read_input_tokens=0,
                char_count=2, byte_count=2, encoding='utf-8',
                has_tool_use=False, tool_names=[],
                message_time='2026-05-17T00:00:00+00:00', model_name=None,
            )
        except Exception as e:
            print(f"   B 段失敗：{e}")
            raise
        # C 段：故意 raise
        try:
            deactivate_old_branches(c, sid)
            raise RuntimeError("模擬 C 段 upsert_branch 失敗")
        except Exception as e:
            print(f"   C 段失敗（預期）：{e}")
            raise
except RuntimeError:
    pass

probe = shiba_db.open_connection()
post_s = probe.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
post_m = probe.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
probe.close()
print(f"   事務前: sessions={pre_s} messages={pre_m}")
print(f"   事務後: sessions={post_s} messages={post_m}")
assert post_s == pre_s, f"sessions 未 rollback: {post_s} != {pre_s}"
assert post_m == pre_m, f"messages 未 rollback: {post_m} != {pre_m}"
print("   ✅ E2E-2 通過：C 段 raise → A+B 段資料全 rollback")


# ---- Teardown ----
shiba_db.open_connection = _orig_open
TMP_DB.unlink(missing_ok=True)

print("\n🎉 PR2 E2E smoke 全部通過（Step 5 + Step 6 原子性已驗證）")
