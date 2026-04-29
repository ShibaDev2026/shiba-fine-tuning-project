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

    # 每日 UTC 00:05 重置 teacher 每日額度旗標
    scheduler.add_job(
        lambda: _reset_daily_limits(conn_factory),
        trigger="cron", hour=0, minute=5,
        id="daily_limit_reset", replace_existing=True,
    )

    return scheduler


def _run_extraction_job(conn_factory) -> None:
    from ..extraction.pipeline import run_extraction_v2
    conn = conn_factory()
    try:
        run_extraction_v2(conn)

        # W4 監控：raw 樣本若逾 24h 未升 pending，表示 refiner 可能離線
        stale = conn.execute(
            "SELECT COUNT(*) FROM training_samples "
            "WHERE status='raw' AND created_at < datetime('now', '-1 day')"
        ).fetchone()[0]
        if stale > 0:
            logger.warning("有 %d 筆 raw 樣本逾 24h 未精煉，請確認 refiner job 或 Ollama 狀態", stale)

        # W5 回饋補齊：extraction 完成後對新樣本補一次 weight 同步
        # （stop_hook 執行時樣本尚未寫入，採納回饋在此時才能正確套用）
        try:
            from layer_0_router.telemetry import sync_sample_weights
            new_sessions = [
                r["session_id"] for r in conn.execute(
                    "SELECT DISTINCT session_id FROM training_samples "
                    "WHERE status='raw' AND weight=1.0 AND session_id IS NOT NULL"
                ).fetchall()
            ]
            for sid in new_sessions:
                sync_sample_weights(sid)
            if new_sessions:
                logger.info("extraction 後 weight 同步：%d sessions", len(new_sessions))
        except Exception as e:
            logger.debug("weight 同步略過（Layer 0 未啟動或無資料）：%s", e)
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


def _reset_daily_limits(conn_factory) -> None:
    """每日 UTC 00:05 重置所有 teacher 的配額旗標與今日計數器"""
    conn = conn_factory()
    try:
        conn.execute("""
            UPDATE teachers SET
                is_daily_limit_reached = 0,
                requests_today         = 0,
                input_tokens_today     = 0,
                output_tokens_today    = 0,
                quota_exhausted_at     = NULL,
                quota_exhausted_type   = NULL
        """)
        conn.commit()
        logger.info("Teacher 每日配額已重置")
    finally:
        conn.close()


def _run_finetune_check(conn_factory) -> None:
    """排程觸發：HTTP POST 至 Layer 3 host 服務，Layer 3 掛掉時 log 警告不拋異常"""
    import httpx
    from shiba_config import CONFIG
    base = CONFIG.services.layer3_base_url
    for block in (1, 2):
        try:
            resp = httpx.post(f"{base}/trigger/{block}", timeout=600)
            resp.raise_for_status()
            result = resp.json()
            if result:
                logger.info("fine-tune 排程完成 block%d：%s", block, result)
        except httpx.ConnectError:
            logger.warning("fine-tune 排程略過 block%d：Layer 3 服務未啟動", block)
        except Exception as e:
            logger.error("fine-tune 排程失敗 block%d：%s", block, e)
