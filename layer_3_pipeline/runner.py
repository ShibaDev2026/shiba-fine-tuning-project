# layer_3_pipeline/runner.py
"""Layer 3 Pipeline 主協調器"""

import logging
from pathlib import Path

import sqlite3

from .db import count_approved, create_run, update_run, get_last_run_id
from .mlx_trainer import train_lora
from .gguf_converter import convert_to_gguf
from .ollama_updater import push_to_ollama
from layer_2_chamber.backend.extraction.dataset_formatter import export_dataset

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

    dataset_dir = work_dir / f"block{adapter_block}"
    dataset_path = dataset_dir / "train.jsonl"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    since_id = get_last_run_id(conn, adapter_block) or 0
    export_result = export_dataset(conn, dataset_path, adapter_block=adapter_block, since_id=since_id)
    total = export_result["total"]

    run_id = create_run(conn, adapter_block, total, str(dataset_path))

    try:
        adapter_dir = train_lora(
            dataset_path=dataset_path,
            adapter_block=adapter_block,
            output_dir=work_dir / "adapters",
        )
        update_run(conn, run_id, adapter_path=str(adapter_dir))

        gguf_path = convert_to_gguf(
            adapter_dir=adapter_dir,
            output_dir=work_dir / "gguf",
            adapter_block=adapter_block,
        )
        update_run(conn, run_id, gguf_path=str(gguf_path))

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
