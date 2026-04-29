#!/usr/bin/env python3
"""
回填 exchanges / exchange_messages 語意層。

用法：
  python -m layer_1_memory.scripts.backfill_exchanges --all
  python -m layer_1_memory.scripts.backfill_exchanges --session-uuid <uuid>
  python -m layer_1_memory.scripts.backfill_exchanges --all --dry-run
"""

import argparse
import logging
import sys
import time

from layer_1_memory.lib.db import get_connection
from layer_1_memory.lib.exchanges import rebuild_exchanges_for_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 每處理 N 個 session 才 commit 一次（降低 WAL checkpoint 頻率）
BATCH_SIZE = 20


def _fetch_all_session_ids(conn) -> list[tuple[int, str]]:
    """回傳 [(session_id, uuid), ...] 按 started_at 升序。"""
    rows = conn.execute(
        "SELECT id, uuid FROM sessions ORDER BY started_at ASC"
    ).fetchall()
    return [(r["id"], r["uuid"]) for r in rows]


def _dry_run_session(conn, session_id: int) -> dict[str, int]:
    """
    在 SAVEPOINT 內執行回填，然後 ROLLBACK 到 SAVEPOINT，
    回傳統計而不實際寫入。
    """
    conn.execute("SAVEPOINT dry_run")
    try:
        stats = rebuild_exchanges_for_session(conn, session_id)
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT dry_run")
        conn.execute("RELEASE SAVEPOINT dry_run")
    return stats


def _run_all(dry_run: bool) -> None:
    total = {"sessions": 0, "branches": 0, "exchanges": 0, "members": 0}
    errors = 0
    t0 = time.time()

    with get_connection() as conn:
        sessions = _fetch_all_session_ids(conn)
        logger.info("共 %d 個 session，dry_run=%s", len(sessions), dry_run)

        pending_commit = 0

        for session_id, uuid in sessions:
            try:
                if dry_run:
                    stats = _dry_run_session(conn, session_id)
                else:
                    stats = rebuild_exchanges_for_session(conn, session_id)
                    pending_commit += 1

                total["sessions"] += 1
                total["branches"] += stats["branches"]
                total["exchanges"] += stats["exchanges"]
                total["members"] += stats["members"]

                # 批次 commit
                if not dry_run and pending_commit >= BATCH_SIZE:
                    conn.commit()
                    pending_commit = 0

            except Exception as exc:
                logger.error("session %s 失敗：%s", uuid, exc)
                if not dry_run:
                    conn.rollback()
                    pending_commit = 0
                errors += 1

        if not dry_run and pending_commit > 0:
            conn.commit()

    elapsed = time.time() - t0
    prefix = "[DRY-RUN] " if dry_run else ""
    logger.info(
        "%s完成：%d sessions / %d branches / %d exchanges / %d members，"
        "錯誤 %d 個，耗時 %.1f 秒",
        prefix,
        total["sessions"],
        total["branches"],
        total["exchanges"],
        total["members"],
        errors,
        elapsed,
    )
    if errors:
        sys.exit(1)


def _run_single(uuid: str, dry_run: bool) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM sessions WHERE uuid = ?", (uuid,)
        ).fetchone()
        if row is None:
            logger.error("找不到 session uuid=%s", uuid)
            sys.exit(1)

        session_id = row["id"]
        if dry_run:
            stats = _dry_run_session(conn, session_id)
            prefix = "[DRY-RUN] "
        else:
            stats = rebuild_exchanges_for_session(conn, session_id)
            conn.commit()
            prefix = ""

        logger.info(
            "%ssession %s：%d branches / %d exchanges / %d members",
            prefix, uuid, stats["branches"], stats["exchanges"], stats["members"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 exchanges 語意層")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="回填全部 sessions")
    group.add_argument("--session-uuid", metavar="UUID", help="只回填指定 session")
    parser.add_argument("--dry-run", action="store_true", help="只統計不寫入")
    args = parser.parse_args()

    if args.all:
        _run_all(dry_run=args.dry_run)
    else:
        _run_single(args.session_uuid, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
