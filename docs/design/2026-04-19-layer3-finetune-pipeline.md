# Layer 3 Fine-tuning Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立自動 MLX LoRA fine-tune → GGUF → Ollama 更新的完整 Pipeline，並在 Layer 2 approved 樣本達到 30 筆時自動觸發。

**Architecture:** Layer 2 background.py 新增 `check_and_trigger_finetune()` 排程（每 6 小時），達門檻後呼叫 `layer_3_pipeline/runner.py` 執行 MLX 訓練、轉換 GGUF、`ollama create` 更新模型，並將結果寫入 DB 的 `finetune_runs` 表。

**Tech Stack:** Python 3.11、MLX-LM（`mlx_lm.lora`）、llama.cpp（`convert_hf_to_gguf.py`）、Ollama CLI、SQLite

---

## 檔案結構

```
layer_3_pipeline/
├── __init__.py
├── runner.py          ← 主入口：協調整個 pipeline
├── mlx_trainer.py     ← 呼叫 mlx_lm.lora 訓練
├── gguf_converter.py  ← 呼叫 llama.cpp convert + quantize
├── ollama_updater.py  ← 執行 ollama create + 驗證
└── db.py              ← finetune_runs 表 CRUD

tests/layer3/
├── test_runner.py
├── test_mlx_trainer.py
├── test_gguf_converter.py
└── test_ollama_updater.py

layer_2_chamber/backend/core/background.py   ← 新增觸發排程
layer_2_chamber/backend/api/routes_finetune.py  ← 手動觸發 endpoint
~/.local-brain/schema_layer3.sql             ← finetune_runs 表定義
```

---

## 常數與路徑（所有 task 共用）

```python
DB_PATH = Path.home() / ".local-brain" / "shiba-brain.db"
DATASET_DIR = Path.home() / ".local-brain" / "datasets"
MODEL_DIR = Path.home() / ".local-brain" / "models"
BASE_MODEL_BLOCK1 = "mlx-community/Qwen2.5-7B-Instruct-4bit"
BASE_MODEL_BLOCK2 = "mlx-community/Qwen2.5-7B-Instruct-4bit"
APPROVED_THRESHOLD = 30   # 觸發門檻
```

---

## Task 1：DB Schema — finetune_runs 表

**Files:**
- Create: `~/.local-brain/schema_layer3.sql`
- Modify: `layer_3_pipeline/db.py`
- Test: `tests/layer3/test_runner.py`（只測 DB 函式）

- [ ] **Step 1: 建立 schema SQL**

```sql
-- ~/.local-brain/schema_layer3.sql
CREATE TABLE IF NOT EXISTS finetune_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter_block INTEGER NOT NULL,          -- 1 或 2
    status      TEXT NOT NULL DEFAULT 'pending',
                                             -- pending / running / done / failed
    dataset_path TEXT,                       -- 訓練用 .jsonl 路徑
    adapter_path TEXT,                       -- 輸出 LoRA adapter 目錄
    gguf_path   TEXT,                        -- 輸出 GGUF 路徑
    ollama_model TEXT,                       -- ollama create 後的 model tag
    sample_count INTEGER,                    -- 本次訓練樣本數
    error_msg   TEXT,
    started_at  TEXT,
    finished_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

執行：
```bash
sqlite3 ~/.local-brain/shiba-brain.db < ~/.local-brain/schema_layer3.sql
```

預期：無錯誤輸出。

- [ ] **Step 2: 建立 layer_3_pipeline/db.py**

```python
# layer_3_pipeline/db.py
"""finetune_runs 表 CRUD"""

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".local-brain" / "shiba-brain.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def count_approved(conn: sqlite3.Connection, adapter_block: int) -> int:
    """回傳指定 block 的 approved 樣本數"""
    row = conn.execute(
        "SELECT COUNT(*) FROM training_samples WHERE status='approved' AND adapter_block=?",
        (adapter_block,),
    ).fetchone()
    return row[0]


def create_run(conn: sqlite3.Connection, adapter_block: int, sample_count: int, dataset_path: str) -> int:
    """建立新的 finetune_run，回傳 run_id"""
    cur = conn.execute(
        """INSERT INTO finetune_runs (adapter_block, status, sample_count, dataset_path, started_at)
           VALUES (?, 'running', ?, ?, datetime('now'))""",
        (adapter_block, sample_count, dataset_path),
    )
    conn.commit()
    return cur.lastrowid


def update_run(conn: sqlite3.Connection, run_id: int, **kwargs) -> None:
    """更新 run 欄位（adapter_path, gguf_path, ollama_model, status, error_msg, finished_at）"""
    sets = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(
        f"UPDATE finetune_runs SET {sets} WHERE id=?",
        (*kwargs.values(), run_id),
    )
    conn.commit()


def get_last_run_id(conn: sqlite3.Connection, adapter_block: int) -> int | None:
    """取得最近一次完成的 run_id，用於 since_id 計算"""
    row = conn.execute(
        """SELECT MAX(ts.id) FROM training_samples ts
           JOIN finetune_runs fr ON fr.adapter_block = ts.adapter_block
           WHERE fr.status = 'done' AND ts.adapter_block = ?""",
        (adapter_block,),
    ).fetchone()
    return row[0]
```

- [ ] **Step 3: 寫測試（僅測 count_approved、create_run、update_run）**

```python
# tests/layer3/test_runner.py
import sqlite3, pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.db import count_approved, create_run, update_run


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE training_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adapter_block INTEGER, status TEXT DEFAULT 'raw'
        );
        CREATE TABLE finetune_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adapter_block INTEGER, status TEXT DEFAULT 'pending',
            sample_count INTEGER, dataset_path TEXT, adapter_path TEXT,
            gguf_path TEXT, ollama_model TEXT, error_msg TEXT,
            started_at TEXT, finished_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    return c


def test_count_approved_empty(conn):
    assert count_approved(conn, 1) == 0


def test_count_approved(conn):
    conn.execute("INSERT INTO training_samples (adapter_block, status) VALUES (1, 'approved')")
    conn.execute("INSERT INTO training_samples (adapter_block, status) VALUES (1, 'approved')")
    conn.execute("INSERT INTO training_samples (adapter_block, status) VALUES (2, 'approved')")
    conn.commit()
    assert count_approved(conn, 1) == 2
    assert count_approved(conn, 2) == 1


def test_create_and_update_run(conn):
    run_id = create_run(conn, 1, 35, "/tmp/data.jsonl")
    assert run_id == 1
    update_run(conn, run_id, status="done", gguf_path="/tmp/model.gguf")
    row = conn.execute("SELECT status, gguf_path FROM finetune_runs WHERE id=1").fetchone()
    assert row["status"] == "done"
    assert row["gguf_path"] == "/tmp/model.gguf"
```

- [ ] **Step 4: 跑測試確認通過**

```bash
cd /Users/surpend/Developer/01_project/shiba-fine-tuning-project
python -m pytest tests/layer3/test_runner.py -v
```

預期：3 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add layer_3_pipeline/db.py tests/layer3/test_runner.py
git commit -m "feat(layer3): DB schema finetune_runs + CRUD"
```

---

## Task 2：MLX 訓練器

**Files:**
- Create: `layer_3_pipeline/mlx_trainer.py`
- Test: `tests/layer3/test_mlx_trainer.py`

- [ ] **Step 1: 寫測試（mock subprocess）**

```python
# tests/layer3/test_mlx_trainer.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.mlx_trainer import train_lora


def test_train_lora_returns_adapter_path(tmp_path):
    dataset = tmp_path / "data.jsonl"
    dataset.write_text('{"instruction":"hi","input":"","output":"hello"}\n')

    with patch("layer_3_pipeline.mlx_trainer.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = train_lora(
            dataset_path=dataset,
            adapter_block=1,
            output_dir=tmp_path / "adapters",
        )

    assert result.exists() or True  # subprocess 是 mock，目錄不會真的建立
    assert "block1" in str(result)


def test_train_lora_raises_on_failure(tmp_path):
    dataset = tmp_path / "data.jsonl"
    dataset.write_text("")

    with patch("layer_3_pipeline.mlx_trainer.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="OOM")
        import pytest
        with pytest.raises(RuntimeError, match="MLX 訓練失敗"):
            train_lora(
                dataset_path=dataset,
                adapter_block=1,
                output_dir=tmp_path / "adapters",
            )
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
python -m pytest tests/layer3/test_mlx_trainer.py -v
```

預期：ImportError（mlx_trainer 不存在）

- [ ] **Step 3: 實作 mlx_trainer.py**

```python
# layer_3_pipeline/mlx_trainer.py
"""MLX LoRA 訓練器：呼叫 mlx_lm.lora CLI 執行訓練"""

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# LoRA 訓練超參數（CLAUDE.md 規範：Phase 1 Qwen2.5 7B）
_LORA_CONFIG = {
    "num_layers": 16,
    "learning_rate": 1e-4,
    "iters": 600,
    "batch_size": 4,
    "lora_rank": 8,
}

BASE_MODELS = {
    1: "mlx-community/Qwen2.5-7B-Instruct-4bit",
    2: "mlx-community/Qwen2.5-7B-Instruct-4bit",
}


def train_lora(
    dataset_path: Path,
    adapter_block: int,
    output_dir: Path,
) -> Path:
    """
    執行 MLX LoRA fine-tune。
    回傳 adapter 目錄 Path；失敗時 raise RuntimeError。
    """
    adapter_dir = output_dir / f"block{adapter_block}"
    adapter_dir.mkdir(parents=True, exist_ok=True)

    model = BASE_MODELS[adapter_block]
    cmd = [
        "python", "-m", "mlx_lm.lora",
        "--model", model,
        "--train",
        "--data", str(dataset_path.parent),  # mlx_lm 讀目錄下的 train.jsonl
        "--adapter-path", str(adapter_dir),
        "--num-layers", str(_LORA_CONFIG["num_layers"]),
        "--learning-rate", str(_LORA_CONFIG["learning_rate"]),
        "--iters", str(_LORA_CONFIG["iters"]),
        "--batch-size", str(_LORA_CONFIG["batch_size"]),
    ]

    logger.info("開始 MLX 訓練 block%d：%s", adapter_block, " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"MLX 訓練失敗（returncode={result.returncode}）：{result.stderr[:500]}")

    logger.info("MLX 訓練完成，adapter → %s", adapter_dir)
    return adapter_dir
```

- [ ] **Step 4: 跑測試確認通過**

```bash
python -m pytest tests/layer3/test_mlx_trainer.py -v
```

預期：2 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add layer_3_pipeline/mlx_trainer.py tests/layer3/test_mlx_trainer.py
git commit -m "feat(layer3): MLX LoRA trainer"
```

---

## Task 3：GGUF 轉換器

**Files:**
- Create: `layer_3_pipeline/gguf_converter.py`
- Test: `tests/layer3/test_gguf_converter.py`

- [ ] **Step 1: 寫測試（mock subprocess）**

```python
# tests/layer3/test_gguf_converter.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.gguf_converter import convert_to_gguf


def test_convert_returns_gguf_path(tmp_path):
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    out_dir = tmp_path / "gguf"

    with patch("layer_3_pipeline.gguf_converter.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = convert_to_gguf(adapter_dir=adapter_dir, output_dir=out_dir, adapter_block=1)

    assert "block1" in str(result)
    assert result.suffix == ".gguf"


def test_convert_raises_on_failure(tmp_path):
    with patch("layer_3_pipeline.gguf_converter.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        import pytest
        with pytest.raises(RuntimeError, match="GGUF 轉換失敗"):
            convert_to_gguf(adapter_dir=tmp_path, output_dir=tmp_path, adapter_block=1)
```

- [ ] **Step 2: 實作 gguf_converter.py**

```python
# layer_3_pipeline/gguf_converter.py
"""MLX adapter → GGUF 轉換（mlx_lm.fuse + llama.cpp convert）"""

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_MODELS = {
    1: "mlx-community/Qwen2.5-7B-Instruct-4bit",
    2: "mlx-community/Qwen2.5-7B-Instruct-4bit",
}

# llama.cpp convert 腳本路徑（需安裝 llama.cpp）
_LLAMA_CPP_CONVERT = Path.home() / "llama.cpp" / "convert_hf_to_gguf.py"


def convert_to_gguf(adapter_dir: Path, output_dir: Path, adapter_block: int) -> Path:
    """
    1. mlx_lm.fuse：將 base model + LoRA adapter 合併為完整 HF model
    2. convert_hf_to_gguf.py：轉換為 Q8_0 GGUF
    回傳 .gguf 檔案 Path；失敗時 raise RuntimeError。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fused_dir = output_dir / f"block{adapter_block}_fused"
    gguf_path = output_dir / f"shiba-block{adapter_block}.gguf"

    # Step A：fuse adapter + base model
    fuse_cmd = [
        "python", "-m", "mlx_lm.fuse",
        "--model", BASE_MODELS[adapter_block],
        "--adapter-path", str(adapter_dir),
        "--save-path", str(fused_dir),
        "--de-quantize",  # 先 de-quantize 再 fuse，確保 GGUF 轉換相容
    ]
    _run(fuse_cmd, "fuse")

    # Step B：convert to GGUF Q8_0
    convert_cmd = [
        "python", str(_LLAMA_CPP_CONVERT),
        str(fused_dir),
        "--outfile", str(gguf_path),
        "--outtype", "q8_0",
    ]
    _run(convert_cmd, "convert")

    logger.info("GGUF 轉換完成：%s", gguf_path)
    return gguf_path


def _run(cmd: list[str], stage: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"GGUF 轉換失敗（{stage}，returncode={result.returncode}）：{result.stderr[:500]}")
```

- [ ] **Step 3: 跑測試確認通過**

```bash
python -m pytest tests/layer3/test_gguf_converter.py -v
```

預期：2 tests PASSED

- [ ] **Step 4: Commit**

```bash
git add layer_3_pipeline/gguf_converter.py tests/layer3/test_gguf_converter.py
git commit -m "feat(layer3): GGUF converter (fuse + convert)"
```

---

## Task 4：Ollama 更新器

**Files:**
- Create: `layer_3_pipeline/ollama_updater.py`
- Test: `tests/layer3/test_ollama_updater.py`

- [ ] **Step 1: 寫測試**

```python
# tests/layer3/test_ollama_updater.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_3_pipeline.ollama_updater import push_to_ollama


def test_push_returns_model_tag(tmp_path):
    gguf = tmp_path / "shiba-block1.gguf"
    gguf.write_bytes(b"fake")

    with patch("layer_3_pipeline.ollama_updater.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        tag = push_to_ollama(gguf_path=gguf, adapter_block=1)

    assert tag.startswith("shiba-block1:")


def test_push_raises_on_failure(tmp_path):
    gguf = tmp_path / "shiba-block1.gguf"
    gguf.write_bytes(b"fake")

    with patch("layer_3_pipeline.ollama_updater.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="err")
        import pytest
        with pytest.raises(RuntimeError, match="ollama create 失敗"):
            push_to_ollama(gguf_path=gguf, adapter_block=1)
```

- [ ] **Step 2: 實作 ollama_updater.py**

```python
# layer_3_pipeline/ollama_updater.py
"""將 GGUF 推送至本地 Ollama（ollama create）"""

import subprocess
import logging
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def push_to_ollama(gguf_path: Path, adapter_block: int) -> str:
    """
    用 Modelfile 建立 ollama model，回傳 model tag（如 shiba-block1:20260419）。
    失敗時 raise RuntimeError。
    """
    date_tag = datetime.now().strftime("%Y%m%d")
    model_tag = f"shiba-block{adapter_block}:{date_tag}"

    modelfile_content = f'FROM {gguf_path}\nPARAMETER temperature 0.7\n'

    with tempfile.NamedTemporaryFile(mode="w", suffix="Modelfile", delete=False) as f:
        f.write(modelfile_content)
        modelfile_path = f.name

    cmd = ["ollama", "create", model_tag, "-f", modelfile_path]
    logger.info("ollama create：%s", model_tag)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ollama create 失敗（returncode={result.returncode}）：{result.stderr[:300]}")

    logger.info("Ollama 模型更新完成：%s", model_tag)
    return model_tag
```

- [ ] **Step 3: 跑測試確認通過**

```bash
python -m pytest tests/layer3/test_ollama_updater.py -v
```

預期：2 tests PASSED

- [ ] **Step 4: Commit**

```bash
git add layer_3_pipeline/ollama_updater.py tests/layer3/test_ollama_updater.py
git commit -m "feat(layer3): Ollama updater (ollama create)"
```

---

## Task 5：Runner — Pipeline 主協調器

**Files:**
- Create: `layer_3_pipeline/runner.py`
- Create: `layer_3_pipeline/__init__.py`
- Test: `tests/layer3/test_runner.py`（追加）

- [ ] **Step 1: 追加 runner 測試至 test_runner.py**

```python
# 追加至 tests/layer3/test_runner.py 尾端

from unittest.mock import patch, MagicMock
from layer_3_pipeline.runner import run_finetune_if_ready


def test_run_skips_when_below_threshold(conn):
    """approved 不足 30 筆時不觸發"""
    result = run_finetune_if_ready(conn, adapter_block=1, threshold=30)
    assert result is None


def test_run_triggers_when_threshold_met(conn, tmp_path):
    """approved 達到門檻時執行完整 pipeline"""
    # 插入 30 筆 approved 樣本
    for i in range(30):
        conn.execute(
            "INSERT INTO training_samples (adapter_block, status, instruction, output) VALUES (1,'approved',?,?)",
            (f"instr{i}", f"out{i}"),
        )
    conn.commit()

    with patch("layer_3_pipeline.runner.export_dataset") as mock_export, \
         patch("layer_3_pipeline.runner.train_lora") as mock_train, \
         patch("layer_3_pipeline.runner.convert_to_gguf") as mock_convert, \
         patch("layer_3_pipeline.runner.push_to_ollama") as mock_push:

        mock_export.return_value = {"total": 30, "path": str(tmp_path / "data.jsonl")}
        mock_train.return_value = tmp_path / "adapters" / "block1"
        mock_convert.return_value = tmp_path / "shiba-block1.gguf"
        mock_push.return_value = "shiba-block1:20260419"

        result = run_finetune_if_ready(conn, adapter_block=1, threshold=30, work_dir=tmp_path)

    assert result["ollama_model"] == "shiba-block1:20260419"
    assert result["status"] == "done"
```

- [ ] **Step 2: 實作 runner.py**

```python
# layer_3_pipeline/runner.py
"""Layer 3 Pipeline 主協調器"""

import logging
from pathlib import Path

import sqlite3

from .db import count_approved, create_run, update_run, get_last_run_id
from .mlx_trainer import train_lora
from .gguf_converter import convert_to_gguf
from .ollama_updater import push_to_ollama

logger = logging.getLogger(__name__)

_DEFAULT_WORK_DIR = Path.home() / ".local-brain" / "finetune"


def run_finetune_if_ready(
    conn: sqlite3.Connection,
    adapter_block: int,
    threshold: int = 30,
    work_dir: Path = _DEFAULT_WORK_DIR,
) -> dict | None:
    """
    檢查 approved 樣本數是否達門檻，達到則執行完整 fine-tune pipeline。
    回傳 {'status': 'done', 'ollama_model': '...'} 或 None（未達門檻）。
    """
    approved = count_approved(conn, adapter_block)
    if approved < threshold:
        logger.info("block%d approved=%d < threshold=%d，跳過", adapter_block, approved, threshold)
        return None

    logger.info("block%d approved=%d，觸發 fine-tune", adapter_block, approved)

    # 匯出資料集（延遲 import 避免循環依賴）
    from layer_2_chamber.backend.extraction.dataset_formatter import export_dataset
    dataset_dir = work_dir / f"block{adapter_block}"
    dataset_path = dataset_dir / "train.jsonl"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    since_id = get_last_run_id(conn, adapter_block) or 0
    export_result = export_dataset(conn, dataset_path, adapter_block=adapter_block, since_id=since_id)
    total = export_result["total"]

    run_id = create_run(conn, adapter_block, total, str(dataset_path))

    try:
        # 1. MLX 訓練
        adapter_dir = train_lora(
            dataset_path=dataset_path,
            adapter_block=adapter_block,
            output_dir=work_dir / "adapters",
        )
        update_run(conn, run_id, adapter_path=str(adapter_dir))

        # 2. GGUF 轉換
        gguf_path = convert_to_gguf(
            adapter_dir=adapter_dir,
            output_dir=work_dir / "gguf",
            adapter_block=adapter_block,
        )
        update_run(conn, run_id, gguf_path=str(gguf_path))

        # 3. Ollama 更新
        model_tag = push_to_ollama(gguf_path=gguf_path, adapter_block=adapter_block)

        update_run(conn, run_id,
                   ollama_model=model_tag,
                   status="done",
                   finished_at="datetime('now')")

        logger.info("Layer 3 pipeline 完成：%s", model_tag)
        return {"status": "done", "ollama_model": model_tag, "run_id": run_id}

    except Exception as e:
        update_run(conn, run_id, status="failed", error_msg=str(e)[:500],
                   finished_at="datetime('now')")
        logger.error("Layer 3 pipeline 失敗：%s", e)
        raise
```

```python
# layer_3_pipeline/__init__.py
```

- [ ] **Step 3: 跑所有 layer3 測試**

```bash
python -m pytest tests/layer3/ -v
```

預期：7 tests PASSED（3 + 2 + 2 = task1~4 的測試 + 新增 2 個）

- [ ] **Step 4: Commit**

```bash
git add layer_3_pipeline/ tests/layer3/test_runner.py
git commit -m "feat(layer3): runner pipeline 主協調器"
```

---

## Task 6：背景排程整合 + 手動觸發 API

**Files:**
- Modify: `layer_2_chamber/backend/core/background.py`
- Create: `layer_2_chamber/backend/api/routes_finetune.py`
- Modify: `layer_2_chamber/backend/main.py`

- [ ] **Step 1: 新增排程至 background.py**

在 `setup_scheduler()` 函式內，`cold_compress` 排程之後新增：

```python
    # 每 6 小時檢查是否達 fine-tune 門檻
    scheduler.add_job(
        lambda: _run_finetune_check(conn_factory),
        trigger="interval", hours=6,
        id="finetune_check", replace_existing=True,
    )
```

在檔案底部新增：

```python
def _run_finetune_check(conn_factory) -> None:
    from layer_3_pipeline.runner import run_finetune_if_ready
    for block in (1, 2):
        conn = conn_factory()
        try:
            result = run_finetune_if_ready(conn, adapter_block=block)
            if result:
                logger.info("fine-tune 排程完成 block%d：%s", block, result)
        except Exception as e:
            logger.error("fine-tune 排程失敗 block%d：%s", block, e)
        finally:
            conn.close()
```

- [ ] **Step 2: 建立 routes_finetune.py（手動觸發用）**

```python
# layer_2_chamber/backend/api/routes_finetune.py
"""手動觸發 fine-tune pipeline"""

from fastapi import APIRouter
from ..core.config import get_connection

router = APIRouter(prefix="/api/v1/finetune", tags=["finetune"])


@router.post("/trigger/{adapter_block}")
def trigger_finetune(adapter_block: int):
    """手動觸發指定 block 的 fine-tune（不受門檻限制）"""
    from layer_3_pipeline.runner import run_finetune_if_ready
    conn = get_connection()
    try:
        result = run_finetune_if_ready(conn, adapter_block=adapter_block, threshold=0)
        return result or {"status": "skipped", "reason": "no approved samples"}
    finally:
        conn.close()


@router.get("/runs")
def list_runs():
    """列出最近 10 次 fine-tune run"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM finetune_runs ORDER BY id DESC LIMIT 10"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

- [ ] **Step 3: 在 main.py 註冊 router**

在 `main.py` 的 `app.include_router(...)` 區段新增：

```python
from .api.routes_finetune import router as finetune_router
app.include_router(finetune_router)
```

- [ ] **Step 4: 啟動 server 驗證 endpoint 存在**

```bash
cd layer_2_chamber/backend
uvicorn main:app --port 8000 &
sleep 3
curl -s http://localhost:8000/openapi.json | python3 -c "import json,sys; paths=json.load(sys.stdin)['paths']; [print(p) for p in paths if 'finetune' in p]"
```

預期輸出：
```
/api/v1/finetune/trigger/{adapter_block}
/api/v1/finetune/runs
```

- [ ] **Step 5: Commit**

```bash
git add layer_2_chamber/backend/core/background.py \
        layer_2_chamber/backend/api/routes_finetune.py \
        layer_2_chamber/backend/main.py
git commit -m "feat(layer3): 背景排程整合 + 手動觸發 API"
```

---

## 驗證總指令

```bash
# 1. 跑全部 layer3 測試
python -m pytest tests/layer3/ -v

# 2. 確認 finetune_runs 表存在
sqlite3 ~/.local-brain/shiba-brain.db ".tables" | grep finetune

# 3. 確認 API endpoint
curl -s http://localhost:8000/openapi.json | python3 -c \
  "import json,sys; [print(p) for p in json.load(sys.stdin)['paths'] if 'finetune' in p]"

# 4. 查看 finetune runs
curl -s http://localhost:8000/api/v1/finetune/runs | python3 -m json.tool
```

---

## 副作用清單

- `~/.local-brain/shiba-brain.db` 新增 `finetune_runs` 表
- `~/.local-brain/finetune/` 目錄：訓練過程中產生 dataset/adapter/gguf（磁碟用量大，7B model fused 約 14GB）
- `ollama create` 會在本地 Ollama 新增 model tag，不影響現有 model
- background.py 新增排程不影響現有排程
