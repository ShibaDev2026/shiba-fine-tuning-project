"""
c4_weekly_ci.py — C.4 週度 E2E 品質 CI 採樣

排程：每週日 22:00 台灣時間，隨機抽 10 筆 golden set query
流程：
  1. 從 retrieval_golden_set 隨機抽 SAMPLE_N 筆（expected_answer 非空）
  2. 每筆走 RAG → qwen3:30b-a3b 生成 → Gemini Flash-Lite judge 評分
  3. 取得本次 mean_score，與 anchor baseline 比對
  4. 若 mean_score < baseline - DROP_THRESHOLD → shiba_alert

執行：
  python -m evaluation.c4_weekly_ci            # 標準 10 筆
  python -m evaluation.c4_weekly_ci --dry-run  # 只取樣，不生成不評分
  python -m evaluation.c4_weekly_ci --n 5      # 調整採樣數（測試用）
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shiba_alert import send_alert
from layer_1_memory.lib.db import get_connection
from evaluation.c2_e2e_evaluation import (
    _ensure_runs_table, _write_run_summary,
    _generate_answer, _judge_answer, _write_eval_result,
)

import time

# C.4 固定設定
_MODEL_SPEC = "ollama:qwen3:30b-a3b"
_SAMPLE_N = 10
_DROP_THRESHOLD = 0.5  # baseline mean 下降超過此值才觸發 alert
_TOP_N = 3


def _load_anchor_baseline() -> float | None:
    """讀取最近一次大批量（sample_count >= 20）qwen baseline 的 mean_score 作為 anchor。"""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT mean_score FROM evaluation_runs
               WHERE model_spec=? AND sample_count >= 20 AND phase='e2e'
               ORDER BY started_at DESC LIMIT 1""",
            (_MODEL_SPEC,),
        ).fetchone()
    return float(row["mean_score"]) if row and row["mean_score"] is not None else None


def _random_sample(n: int) -> list:
    """從 retrieval_golden_set 隨機抽 n 筆有 expected_answer 的 query。"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, query, expected_answer
               FROM retrieval_golden_set
               WHERE expected_answer IS NOT NULL
                 AND is_active = 1
               ORDER BY RANDOM()
               LIMIT ?""",
            (n,),
        ).fetchall()
    return rows


def run(n: int = _SAMPLE_N, dry_run: bool = False) -> None:
    """執行 C.4 週度 CI 採樣評估。"""
    _ensure_runs_table()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"c4-ci-{ts}"
    started_at = datetime.now(timezone.utc).isoformat()

    anchor = _load_anchor_baseline()
    rows = _random_sample(n)

    print(f"\n[C.4 CI] run_id={run_id}  model={_MODEL_SPEC}  n={len(rows)}  anchor={anchor}  dry_run={dry_run}\n")

    if not rows:
        print("⚠ golden set 無可用樣本，中止")
        return

    scores: list[float] = []
    ok = 0

    from clients.base import AIClientError
    from layer_1_memory.lib.rag import retrieve_for_eval

    try:
        for i, row in enumerate(rows, 1):
            qid = row["id"]
            query = row["query"]
            expected = row["expected_answer"]

            rag = retrieve_for_eval(query, top_n=_TOP_N)
            contexts = rag.get("retrieved_contexts", [])
            source = rag.get("source", "?")

            print(f"[{i:2d}/{len(rows)}] id={qid} src={source} ctx={len(contexts)} q={query[:50]}")

            if dry_run:
                continue

            generated = _generate_answer(_MODEL_SPEC, query, contexts, sample_id=qid)
            if not generated:
                print("  ⚠ 生成失敗，跳過")
                continue

            print(f"  → {generated[:80]}...")

            score, reason = _judge_answer(query, expected, generated)
            time.sleep(4)  # Flash-Lite 速率保護

            score_str = f"{score:.1f}" if score is not None else "N/A"
            print(f"  score={score_str}  {reason[:60]}")

            if score is not None:
                scores.append(score)
                _write_eval_result(
                    run_id=run_id,
                    metric_name="answer_quality",
                    metric_value=score,
                    evaluator_model="gemini-2.5-flash-lite",
                    sample_id=qid,
                    metadata={
                        "model_spec": _MODEL_SPEC,
                        "rag_source": source,
                        "n_contexts": len(contexts),
                        "generated": generated[:300],
                        "reason": reason,
                    },
                )
            ok += 1

    except AIClientError as e:
        print(
            f"\n⛔ 整批熔斷（{ok}/{len(rows)}）："
            f"{e.category.value} {e.vendor}:{e.model_id} http={e.status_code}",
            file=sys.stderr,
        )
        print(f"   原因：{e.message}", file=sys.stderr)

    finished_at = datetime.now(timezone.utc).isoformat()
    mean_score = round(sum(scores) / len(scores), 4) if scores else None

    _write_run_summary(
        run_id=run_id,
        model_spec=_MODEL_SPEC,
        sample_count=ok,
        mean_score=mean_score,
        started_at=started_at,
        finished_at=finished_at,
        metadata={"ci": True, "sample_n": n, "anchor": anchor},
    )

    print(f"\n── 完成 {ok}/{len(rows)}  mean={mean_score}  anchor={anchor}  run_id={run_id} ──")

    # anchor 比對：下降超過閾值才告警
    if not dry_run and mean_score is not None and anchor is not None:
        delta = mean_score - anchor
        if delta < -_DROP_THRESHOLD:
            send_alert(
                "c4_quality_regression",
                f"C.4 週度 CI 品質下降 Δ={delta:+.2f}（mean={mean_score}，anchor={anchor}）",
                context={
                    "run_id": run_id,
                    "mean_score": mean_score,
                    "anchor": anchor,
                    "delta": delta,
                    "model": _MODEL_SPEC,
                },
            )
            print(f"\n🚨 ALERT：品質下降 Δ={delta:+.2f}（閾值 -{_DROP_THRESHOLD}）", file=sys.stderr)
        else:
            print(f"  品質正常 Δ={delta:+.2f}（閾值 -{_DROP_THRESHOLD}）")


def main() -> None:
    p = argparse.ArgumentParser(description="C.4 週度 E2E 品質 CI 採樣")
    p.add_argument("--n", type=int, default=_SAMPLE_N, help="採樣筆數（預設 10）")
    p.add_argument("--dry-run", action="store_true", help="只取樣，不生成不評分")
    args = p.parse_args()
    run(n=args.n, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
