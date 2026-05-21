# layer_3_pipeline/runner.py
"""Layer 3 Pipeline 主協調器"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import sqlite3

from .db import create_run, update_run, get_last_run_id
from .mlx_trainer import train_lora
from .gguf_converter import convert_to_gguf
from .ollama_updater import push_to_ollama
from .trigger_policy_basic import should_trigger_basic
from core.feature_registry import get_hook
from layer_2_chamber.backend.extraction.dataset_formatter import export_dataset

logger = logging.getLogger(__name__)

# Layer 3 host 獨立服務的 MLX 訓練工作區（checkpoint / adapter / GGUF 中間產物）
# 刻意不進 config/shiba.yaml：此路徑為 Layer 3 私有實作細節，
# 與 docker 生態無關（MPS 需求 → host only），也無跨 layer 共用需求。
_DEFAULT_WORK_DIR = Path.home() / ".local-brain" / "finetune"


def run_finetune_if_ready(
    conn: sqlite3.Connection,
    adapter_block: int,
    work_dir: Path = _DEFAULT_WORK_DIR,
) -> dict | None:
    """
    P1-1 動態觸發：三信號（Ebbinghaus / 採納退化 / 分布偏移）任一觸發
    且 approved ≥ MIN_SAMPLES 才執行完整 fine-tune pipeline。
    回傳 {'status': 'done', 'ollama_model': '...'} 或 None（未觸發）。

    觸發門檻由 trigger_policy.should_trigger 內部決定，不再由外部 threshold 注入。
    """
    # ebbinghaus_trigger feature 啟用時走 v2 三信號策略；否則 fallback 基本策略（approved≥30）
    trigger_fn = get_hook("trigger") or should_trigger_basic
    decision = trigger_fn(conn, adapter_block)
    if not decision.should_train:
        logger.info("block%d 未觸發：%s", adapter_block, decision.reason)
        return None

    # D：首次訓練 → 建立 pending_manual run，等待人工 approve；不執行實際訓練
    if decision.requires_manual:
        cur = conn.execute(
            """INSERT INTO finetune_runs
               (adapter_block, status, requires_manual_approval, created_at)
               VALUES (?, 'pending_manual', 1, datetime('now'))""",
            (adapter_block,),
        )
        conn.commit()
        run_id = cur.lastrowid
        logger.info(
            "block%d 首次訓練：建立 pending_manual run_id=%d，請至 /api/v1/finetune/%d/approve 人工審核",
            adapter_block, run_id, run_id,
        )
        return {"status": "pending_manual", "run_id": run_id, "reason": decision.reason}

    logger.info("block%d 觸發訓練：%s", adapter_block, decision.reason)

    dataset_dir = work_dir / f"block{adapter_block}"
    dataset_path = dataset_dir / "train.jsonl"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    since_id = get_last_run_id(conn, adapter_block) or 0
    export_result = export_dataset(conn, dataset_path, adapter_block=adapter_block, since_id=since_id)
    total = export_result["total"]

    # F2：取得 approved 樣本數供動態 rank 決策
    approved_count = conn.execute(
        "SELECT COUNT(*) FROM training_samples WHERE status='approved' AND adapter_block=?",
        (adapter_block,),
    ).fetchone()[0]

    run_id = create_run(conn, adapter_block, total, str(dataset_path))

    try:
        adapter_dir = train_lora(
            dataset_path=dataset_path,
            adapter_block=adapter_block,
            output_dir=work_dir / "adapters",
            approved_count=approved_count,
        )
        update_run(conn, run_id, adapter_path=str(adapter_dir))

        gguf_path = convert_to_gguf(
            adapter_dir=adapter_dir,
            output_dir=work_dir / "gguf",
            adapter_block=adapter_block,
        )
        update_run(conn, run_id, gguf_path=str(gguf_path))

        # P0-2 Shadow Gate：經 feature_registry 注入 "gate" hook；
        # shadow_gatekeeper feature 未啟用時 hook 為 None → 直接放行（最小核心路徑）
        run_gate = get_hook("gate")
        if run_gate is not None:
            gate = run_gate(gguf_path=gguf_path, adapter_block=adapter_block, conn=conn)
            update_run(conn, run_id,
                       error_msg=f"gate: {gate.reason} (win_rate={gate.win_rate:.3f})",
                       status="gate_eval")

            if not gate.passed:
                update_run(conn, run_id,
                           status="gate_rejected",
                           finished_at=datetime.now(timezone.utc).isoformat())
                logger.warning(
                    "Shadow gate 拒絕 block%d：%s",
                    adapter_block, gate.reason,
                )
                return {"status": "gate_rejected", "run_id": run_id, "gate": vars(gate)}
        else:
            logger.info("shadow_gatekeeper feature off：略過 gate，直接 deploy")

        model_tag = push_to_ollama(gguf_path=gguf_path, adapter_block=adapter_block)

        update_run(conn, run_id,
                   ollama_model=model_tag,
                   status="done",
                   finished_at=datetime.now(timezone.utc).isoformat())

        logger.info("Layer 3 pipeline 完成：%s", model_tag)
        return {"status": "done", "ollama_model": model_tag, "run_id": run_id}

    except Exception as e:
        update_run(conn, run_id, status="failed", error_msg=str(e)[:500],
                   finished_at=datetime.now(timezone.utc).isoformat())
        logger.error("Layer 3 pipeline 失敗：%s", e)
        raise
