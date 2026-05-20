# SQLite Race / Corruption 強化方案

> **Plan 檔位置注意**：依 Shiba CLAUDE.md「Plan 檔一律寫入專案內 `docs/archive/plans/`」規範，本檔在執行時 Step 0 會搬到 `docs/archive/plans/2026-05-09-sqlite-race-hardening.md`。此處寫 `~/.claude/plans/` 純粹是 plan-mode 限制只能編此路徑。

## Context

2026-05-09 11:14 backend 噴 `sqlite3.OperationalError: disk I/O error`，整個 `data/shiba-brain.db` `PRAGMA integrity_check` 末段 100+ pages 全壞。已用 `.recover` SOP 修完並驗證（11:24 全綠），但根因尚未排除，下次仍會發生。

**根因鏈**（Phase 1 兩 agent 探索 + DBA 角度分析）：
1. **跨進程 writer 同時讀寫同一 .db 檔**：host stop_hook（每對話結束）+ container backend uvicorn + container APScheduler 6 jobs（extraction 15min、refiner 10min、paraphrase 15min、scoring 60min、cold_compress、finetune_check）+ Layer 3 訓練 trigger，最多 3-4 進程同秒並發
2. **PRAGMA 三層不一致**：Layer 0 完全無設、Layer 1 WAL+busy=5s、Layer 2 WAL+busy=30s+`check_same_thread=False`，全層皆缺 `synchronous`、`wal_autocheckpoint`、`mmap_size`
3. **stop_hook 100 行單事務**（`stop_hook.py:165-269`）橫跨 6 張表，事務期間 paraphrase/refiner 撞 lock
4. **APScheduler 6 jobs 全用 `interval` 而非 `cron`**，啟動時間 align 後同 minute=0 觸發
5. **macOS docker bind mount + APFS** 對 SQLite WAL fsync 行為不利

**目標**：分 2 PR 階段性消除 race，PR1 把 corruption 機率降 80%+，PR2 補事務原子性。

---

## Step 0 — 搬 plan 檔到專案路徑（手動 1 行）

```bash
mv ~/.claude/plans/zazzy-scribbling-wirth.md \
   docs/archive/plans/2026-05-09-sqlite-race-hardening.md
```

---

## PR1：PRAGMA 統一 + 排程錯開 + WAL checkpoint
**目標**：消除 80%+ corruption 機率，不動事務邏輯。**驗證一週**穩定後才進 PR2。

### Step 1 — 建 root 層 `shiba_db.py`
**模型/effort**：Sonnet medium

**檔案**：新建 `/Users/surpend/Developer/01_project/shiba-fine-tuning-project/shiba_db.py`（與 `shiba_config.py`、`shiba_alert.py` 平行擺放）

**內容骨架**：
```python
"""shiba_db.py — 全專案統一 SQLite 連線 helper

跨 Layer 0/1/2/3 共用同一套 PRAGMA，消除三層 PRAGMA 不一致導致的 race。
"""
import sqlite3
from contextlib import contextmanager
from typing import Literal

from shiba_config import CONFIG

WRITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",       # WAL 下對 process crash 安全；macOS bind mount 上 FULL 太慢
    "PRAGMA busy_timeout=30000",        # 30s lock 等待
    "PRAGMA wal_autocheckpoint=1000",   # ~4MB 自動 checkpoint
    "PRAGMA mmap_size=268435456",       # 256MB memory map
    "PRAGMA temp_store=MEMORY",
    "PRAGMA foreign_keys=ON",
)

def open_connection(
    role: Literal["writer", "reader"] = "writer",
    timeout: float = 30.0,
) -> sqlite3.Connection:
    """取得套好 PRAGMA 的 SQLite connection。
    role 暫為文件用途；未來可加 advisory file lock 區分 writer/reader。"""
    conn = sqlite3.connect(str(CONFIG.paths.db), timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in WRITE_PRAGMAS:
        conn.execute(pragma)
    return conn

@contextmanager
def get_connection(role: Literal["writer", "reader"] = "writer"):
    conn = open_connection(role)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

**驗證**：
```bash
python -c "from shiba_db import open_connection; c = open_connection(); \
  print({r[0]: r[1] for r in [(p, c.execute(f'PRAGMA {p}').fetchone()[0]) \
  for p in ['journal_mode','synchronous','busy_timeout','mmap_size']]})"
# 期望：{'journal_mode': 'wal', 'synchronous': 1, 'busy_timeout': 30000, 'mmap_size': 268435456}
```

**Risk/Rollback**：純新檔，無 import side effect。Rollback = `rm shiba_db.py`。

---

### Step 2 — Layer 0 替換
**模型/effort**：Haiku low

**檔案/行**：
- `layer_0_router/_config.py:26-29` `_connect()` 改用 `from shiba_db import open_connection; return open_connection("reader")`
- `layer_0_router/telemetry.py`（agent 報告 line 49 有 sqlite3.connect，執行時讀檔確認）

**驗證**：
```bash
docker compose restart backend && sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9590/api/v1/router/status   # 200
```

**Risk/Rollback**：Layer 0 是 hot path，任何 import 錯誤會 503。Rollback = `git revert`。

---

### Step 3 — Layer 1 替換
**模型/effort**：Sonnet medium

**檔案/行**：`layer_1_memory/lib/db.py:30-49` `get_connection()` 內部改用 `shiba_db.get_connection`，移除 line 41-43 局部 PRAGMA。同時刪 `layer_1_memory/db/schema.sql` 內任何 PRAGMA 行（PRAGMA 屬連線層不屬 schema）。

**驗證**：
```bash
# 模擬 stop_hook
echo '{"session_id": "test", ...}' | python3 -m layer_1_memory.hooks.stop_hook
sqlite3 data/shiba-brain.db "PRAGMA integrity_check"   # ok
```

**Risk/Rollback**：stop_hook 是寫主力。先在 broken-orig 備份檔上 dry run。Rollback = revert。

---

### Step 4 — Layer 2 + Layer 3 connection 點全替換
**模型/effort**：Sonnet medium（5 處小修，但要逐個 commit 符合 Shiba 單次異動）

**檔案/行**（執行時逐個 grep 確認）：
- `layer_2_chamber/backend/core/config.py:457`（移除 `check_same_thread=False`，helper 已內含）
- `layer_2_chamber/backend/main.py:52`（lifespan）
- `layer_2_chamber/backend/services/teacher_service.py:62`
- `layer_3_pipeline/db.py:13`
- `layer_3_pipeline/server.py:18`

**驗證**：
```bash
grep -rn "sqlite3.connect" layer_0_router layer_1_memory layer_2_chamber layer_3_pipeline
# 期望：0 筆（除 shiba_db.py 自身與 broken backup script）
docker compose restart backend && sleep 3
for ep in router/status models/registry teachers; do
  curl -s -o /dev/null -w "$ep %{http_code}\n" http://localhost:9590/api/v1/$ep
done
# 全 200
```

**Risk/Rollback**：分 5 commits，個別 revert。

---

### Step 7 — APScheduler `interval` 改 `cron` 錯開
**模型/effort**：Haiku low

**檔案**：`layer_2_chamber/backend/core/background.py:115-162`

**改動表**：
| job id | 現況 | 改後（cron） |
|---|---|---|
| extraction | interval 15min | `minute='0,15,30,45'` |
| refiner | interval 10min | `minute='2,12,22,32,42,52'` |
| paraphrase | interval 15min | `minute='7,22,37,52'` |
| scoring | interval 1h | `hour='*', minute=3` |
| cold_compress | cron 02:00 | 不動 |
| finetune_check | interval 6h | `hour='*/6', minute=8` |
| daily_limit_reset | cron 00:05 | 不動 |

**驗證**：
```bash
docker compose logs backend --since 1h | grep "Job .* fired" | awk '{print $NF}' | sort | uniq -c
# 期望：同一 minute 不會出現 ≥2 個 job 同步觸發
```

**Risk/Rollback**：改錯 cron expression 會永久不跑，務必對照表逐欄驗證。Revert 即可。

---

### Step 8 — WAL checkpoint cron job
**模型/effort**：Haiku low

**檔案**：`layer_2_chamber/backend/core/background.py` 加新 job

**內容**：
```python
def _wal_checkpoint(conn_factory) -> None:
    conn = conn_factory()
    try:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        logger.info("WAL checkpoint TRUNCATE: busy=%d log=%d ckpt=%d", *result)
    finally:
        conn.close()

scheduler.add_job(
    lambda: _wal_checkpoint(conn_factory),
    trigger="cron", hour=3, minute=30,
    id="wal_checkpoint", **_common,
)
```

**驗證**：
```bash
docker compose exec backend python -c "
from layer_2_chamber.backend.core.config import get_db_conn_factory
import shiba_db; c = shiba_db.open_connection()
print(c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
"
ls -lh data/shiba-brain.db-wal   # 期望 0 或 < 1MB
```

**Risk/Rollback**：Revert。

---

### PR1 驗收（合併前必跑）

```bash
# 1. integrity 全綠
sqlite3 data/shiba-brain.db "PRAGMA integrity_check"   # ok

# 2. PRAGMA 一致
grep -rn "sqlite3.connect" layer_0_router layer_1_memory layer_2_chamber layer_3_pipeline
# 期望 0 筆

# 3. 24 小時穩定觀察
ls -lh data/shiba-brain.db-wal      # < 64MB
docker compose logs backend --since 24h | grep -iE "disk i/o|malformed|database is locked"
# 期望 0 筆

# 4. 並發壓測
( for i in 1 2 3; do echo '{...sample...}' | python3 -m layer_1_memory.hooks.stop_hook & done; wait )
sqlite3 data/shiba-brain.db "PRAGMA integrity_check"   # ok
```

---

## PR2（PR1 穩定一週後進）：事務原子化

### Step 5 — `stop_hook.py` 加 SAVEPOINT 分段
**模型/effort**：Opus high

**檔案**：`layer_1_memory/hooks/stop_hook.py:165-269`

**設計**：保留外層 `with conn:` 單一事務，內部用 4 段 SAVEPOINT 切：
- (A) `s_session`：projects + sessions + update_stats
- (B) `s_msgs`：messages + tool_executions
- (C) `s_branches`：branches + branch_messages
- (D) `s_fts`：sessions_fts

每段失敗 `ROLLBACK TO`，整體最後 `RELEASE` + commit。任一段全失敗才整體 rollback。

**驗證**：
```bash
# 模擬中段失敗（在 branches 寫入前 raise）
python3 -c "
from layer_1_memory.hooks import stop_hook
# monkey patch upsert_branch raise
..."
sqlite3 data/shiba-brain.db "SELECT COUNT(*) FROM messages WHERE session_id=(SELECT id FROM sessions WHERE uuid='test_session')"
# 期望：messages 仍寫入（SAVEPOINT s_msgs RELEASE 過了），branches=0（ROLLBACK TO s_branches）
```

**Risk/Rollback**：邏輯複雜，先寫 unit test。Rollback = revert。

---

### Step 6 — `multi_judge.py` 包外層事務
**模型/effort**：Sonnet medium

**檔案**：`layer_2_chamber/backend/services/multi_judge.py:77-84`

**改動**：移除 service 內 3 個 judge 各自 commit，改由呼叫端 `with shiba_db.get_connection() as conn:` 包裹整個 multi_judge_score。失敗整批 rollback。

**驗證**：
```bash
# 跑一次 scoring，模擬中途 judge 失敗
sqlite3 data/shiba-brain.db "SELECT id, status, weight FROM training_samples WHERE id=...";
# 期望：要嘛三 judge 都更新，要嘛全不更新（無 partial）
```

---

### PR2 驗收
- stop_hook 模擬 raise → 預期 SAVEPOINT 範圍正確
- scoring job 模擬 raise → 預期 training_samples 無 partial state
- 24 小時無 corruption

---

## Future Considerations（不在本 plan，留紀錄）

1. **stop_hook 改打 backend HTTP API**（單寫者架構）— 結構性消除跨進程 race，但需處理 backend offline 的 buffer queue
2. **bind mount 改 named volume** — 避開 macOS APFS fsync，但 stop_hook 從 host 直寫的能力會消失（須配合上面改造）
3. **Litestream 連續備份** — 即使 corruption 再發也有 PITR 還原
4. **改 SQLAlchemy Core 統一 ORM 層** — 大改，僅當需要強型別 query builder 才考慮

---

## Risk & Rollback（總體）

- 每 step 一個 commit，git revert 即回滾
- PR1 全部 step 都是 PRAGMA / 排程 / 新 cron，不動既有事務邏輯，風險低
- PR2 Step 5 風險最高（拆事務），務必在 broken-orig 備份檔 dry run
- PR1 合併後 7 日內監控 `data/shiba-brain.db-wal` 大小、`docker compose logs backend | grep -iE "disk i/o|malformed"` 必須 0 筆才允許進 PR2

## Critical Files

- 新建：`shiba_db.py`（root）
- 修改：
  - `layer_0_router/_config.py:26`、`telemetry.py`
  - `layer_1_memory/lib/db.py:30-49`、`db/schema.sql`
  - `layer_1_memory/hooks/stop_hook.py:165-269`（PR2）
  - `layer_2_chamber/backend/core/config.py:457`
  - `layer_2_chamber/backend/core/background.py:115-162`
  - `layer_2_chamber/backend/main.py:52`
  - `layer_2_chamber/backend/services/teacher_service.py:62`
  - `layer_2_chamber/backend/services/multi_judge.py:77-84`（PR2）
  - `layer_3_pipeline/db.py:13`、`server.py:18`
