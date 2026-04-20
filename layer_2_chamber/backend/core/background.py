"""
background.py — APScheduler 背景排程

排程任務：
1. 每小時：run_extraction（路徑 A + B 抽取新樣本）
2. 每 6 小時：自動評分 pending 樣本（批次送 Teacher）
3. 每日凌晨 2 點：冷資料壓縮（超過 90 天未存取的 branch 標記 decay_score=0）
"""

import logging
from datetime import datetime, timedelta, timezone

import sqlite3

logger = logging.getLogger(__name__)


def score_pending_samples(conn_factory) -> dict:
    """
    批次評分所有 pending 樣本，每次最多處理 20 筆（避免 API 配額爆掉）。
    conn_factory：呼叫後回傳 sqlite3.Connection
    """
    from ..services.multi_judge import multi_judge_score

    conn = conn_factory()
    try:
        # COALESCE：優先用 Qwen 改寫版本，fallback 原始 instruction
        rows = conn.execute(
            """SELECT id, session_id,
                      COALESCE(refined_instruction, instruction) AS instruction,
                      input, output
               FROM training_samples WHERE status = 'pending'
               ORDER BY id LIMIT 20"""
        ).fetchall()

        results = {"scored": 0, "failed": 0}
        for row in rows:
            result = multi_judge_score(
                conn, row["id"], row["instruction"], row["input"] or "", row["output"],
                session_id=row["session_id"],
            )
            if result["score"] is not None:
                results["scored"] += 1
            else:
                results["failed"] += 1

        logger.info("批次評分完成（multi_judge）：%s", results)
        return results
    finally:
        conn.close()


def compress_cold_data(conn_factory) -> dict:
    """
    冷資料壓縮：超過 90 天未存取（last_accessed 為 NULL 或過期）的 branch
    decay_score 設為 0，不再被 RAG 優先抽取。
    保護條件：未被 Layer 2 完成評分的 session 不壓縮（確保仍可被 pipeline 抽取）。
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    conn = conn_factory()
    try:
        cur = conn.execute(
            """UPDATE branches SET decay_score = 0
               WHERE is_active = 1
                 AND decay_score > 0
                 AND (last_accessed IS NULL OR last_accessed < ?)
                 AND session_id IN (
                     SELECT s.id FROM sessions s
                     JOIN training_samples ts ON ts.session_id = s.uuid
                     WHERE ts.status IN ('approved', 'rejected', 'needs_review')
                 )""",
            (cutoff,),
        )
        conn.commit()
        count = cur.rowcount
        logger.info("冷資料壓縮：%d 筆 branch 設為 decay_score=0", count)
        return {"compressed": count}
    finally:
        conn.close()


def setup_scheduler(app, conn_factory):
    """
    建立 APScheduler 並掛載到 FastAPI lifespan。
    app：FastAPI instance；conn_factory：回傳 DB connection 的 callable。
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning("APScheduler 未安裝，背景排程停用（pip install apscheduler）")
        return None

    scheduler = AsyncIOScheduler()

    # 每 15 分鐘抽取新樣本
    scheduler.add_job(
        lambda: _run_extraction_job(conn_factory),
        trigger="interval", minutes=15,
        id="extraction", replace_existing=True,
    )

    # 每 10 分鐘批次精煉 raw 樣本
    scheduler.add_job(
        lambda: _run_refiner_job(conn_factory),
        trigger="interval", minutes=10,
        id="refiner", replace_existing=True,
    )

    # 每小時批次評分
    scheduler.add_job(
        lambda: score_pending_samples(conn_factory),
        trigger="interval", hours=1,
        id="scoring", replace_existing=True,
    )

    # 每 15 分鐘補充 exchange_embeddings 同義說法變體
    scheduler.add_job(
        lambda: _run_paraphrase_job(conn_factory),
        trigger="interval", minutes=15,
        id="paraphrase", replace_existing=True,
    )

    # 每日凌晨 2 點冷資料壓縮
    scheduler.add_job(
        lambda: compress_cold_data(conn_factory),
        trigger="cron", hour=2, minute=0,
        id="cold_compress", replace_existing=True,
    )

    # 每 6 小時檢查是否達 fine-tune 門檻
    scheduler.add_job(
        lambda: _run_finetune_check(conn_factory),
        trigger="interval", hours=6,
        id="finetune_check", replace_existing=True,
    )

    return scheduler


def _run_extraction_job(conn_factory) -> None:
    from ..extraction.pipeline import run_extraction
    conn = conn_factory()
    try:
        run_extraction(conn)
    finally:
        conn.close()


def _run_refiner_job(conn_factory) -> None:
    from ..services.refiner_service import refine_pending_raw_samples
    stats = refine_pending_raw_samples(conn_factory)
    logger.info("精煉排程完成：%s", stats)


def _run_paraphrase_job(conn_factory) -> None:
    from ..services.paraphrase_service import paraphrase_sparse_instructions
    stats = paraphrase_sparse_instructions(conn_factory)
    logger.info("同義說法補充完成：%s", stats)


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
