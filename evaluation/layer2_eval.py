"""
layer2_eval.py — Phase B Layer 2 Judge 可靠性評估

B.2  Fleiss' Kappa：從 judge_agreement_logs 計算 judge 間一致性
B.3  RAGAS Faithfulness：用本地 qwen3:30b 評估 approved 樣本的輸出忠實度

執行：
  python -m evaluation.layer2_eval --action kappa
  python -m evaluation.layer2_eval --action faithfulness --limit 50
  python -m evaluation.layer2_eval --action all
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from layer_1_memory.lib.db import get_connection
from layer_2_chamber.backend.services.teacher_service import (
    _strip_markdown, get_api_key,
)

_OLLAMA_HOST = "http://localhost:11434"
_OLLAMA_MODEL = "qwen3:30b-a3b"

# ── B.2 Fleiss' Kappa ────────────────────────────────────────────────────────

def _load_votes() -> list[dict]:
    """讀 judge_agreement_logs，每筆 expand votes_json 為 list[dict]"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, sample_id, votes_json FROM judge_agreement_logs ORDER BY id"
        ).fetchall()
    result = []
    for r in rows:
        try:
            votes = json.loads(r["votes_json"])
        except Exception:
            continue
        result.append({"log_id": r["id"], "sample_id": r["sample_id"], "votes": votes})
    return result


def compute_fleiss_kappa(records: list[dict]) -> dict:
    """
    計算 Fleiss' Kappa（二元分類：approved vs rejected）。

    公式：κ = (P̄ - P̄ₑ) / (1 - P̄ₑ)
    - P̄   = 每個 subject 所有 rater 配對一致的均值
    - P̄ₑ  = 每個類別在所有評分中的比例平方和（機率期望值）

    注意：若 rater 數量不一致（早停），仍可計算；
    每筆只有 1 票時跳過（無法算配對一致性）。
    """
    N = len(records)  # subjects (samples)
    if N == 0:
        return {"fleiss_kappa": None, "n_samples": 0, "error": "no data"}

    total_ratings = 0
    approved_total = 0
    rejected_total = 0
    subject_p_sum = 0.0
    valid_n = 0

    for rec in records:
        votes = rec["votes"]
        n_j = len(votes)  # raters for this subject
        if n_j < 2:
            continue  # 無法計算配對一致性
        valid_n += 1
        n_approved = sum(1 for v in votes if v.get("approved"))
        n_rejected = n_j - n_approved
        approved_total += n_approved
        rejected_total += n_rejected
        total_ratings += n_j
        # per-subject 一致性：Σ(nij²) - n_j / (n_j*(n_j-1))
        p_i = (n_approved ** 2 + n_rejected ** 2 - n_j) / (n_j * (n_j - 1))
        subject_p_sum += p_i

    if valid_n == 0 or total_ratings == 0:
        return {"fleiss_kappa": None, "n_samples": N, "error": "insufficient valid samples"}

    p_bar = subject_p_sum / valid_n

    # 各類別在所有評分中的比例
    p_approved = approved_total / total_ratings
    p_rejected = rejected_total / total_ratings
    p_e_bar = p_approved ** 2 + p_rejected ** 2

    if abs(1 - p_e_bar) < 1e-9:
        return {"fleiss_kappa": 1.0, "n_samples": valid_n, "note": "perfect agreement"}

    kappa = (p_bar - p_e_bar) / (1 - p_e_bar)

    return {
        "fleiss_kappa": round(kappa, 4),
        "n_samples": valid_n,
        "n_skipped": N - valid_n,
        "p_bar": round(p_bar, 4),
        "p_e_bar": round(p_e_bar, 4),
        "approved_rate": round(p_approved, 4),
        "total_ratings": total_ratings,
    }


def _save_kappa_result(run_id: str, result: dict) -> None:
    kappa = result.get("fleiss_kappa")
    if kappa is None:
        return
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO evaluation_results
               (run_id, phase, metric_name, metric_value, evaluator_model, metadata)
               VALUES (?, 'layer2', 'fleiss_kappa', ?, 'computed', ?)""",
            (run_id, kappa, json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()


def action_kappa(run_id: str) -> dict:
    """B.2 主流程：計算並儲存 Fleiss' Kappa"""
    records = _load_votes()
    result = compute_fleiss_kappa(records)
    _save_kappa_result(run_id, result)

    print("\n── B.2 Fleiss' Kappa ─────────────────────────")
    for k, v in result.items():
        print(f"  {k}: {v}")

    kappa = result.get("fleiss_kappa")
    if kappa is not None:
        if kappa >= 0.8:
            print("  → 幾乎完美一致（≥0.8）")
        elif kappa >= 0.6:
            print("  → 實質一致（0.6-0.8）")
        elif kappa >= 0.4:
            print("  → 中等一致（0.4-0.6），建議審查 judge 配置")
        else:
            print("  → 一致性偏低（<0.4），judge 間存在系統性分歧")

    return result


# ── B.3 RAGAS Faithfulness ───────────────────────────────────────────────────

_FAITHFULNESS_PROMPT = """你是訓練資料品質評估員。任務：判斷以下「AI 助手的輸出」是否忠實地回應「使用者的指令」。

【使用者指令】
{instruction}

【AI 輸出】
{output}

判斷標準：
- faithful=true：輸出確實回應了指令、操作對象/命令正確，沒有明顯捏造或偏題
- faithful=false：輸出偏離指令、使用錯誤工具/命令，或包含無根據的聲明

請以 JSON 輸出（不要加 markdown code fence）：
{{"faithful": true, "confidence": "high", "reason": "一句話說明"}}

confidence 只能是 "high" | "medium" | "low"。
"""


def _call_local_judge(prompt: str, max_tokens: int = 256) -> str | None:
    """Ollama native /api/generate，think=false"""
    import urllib.request, urllib.error

    body = json.dumps({
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": max_tokens},
    }).encode()
    req = urllib.request.Request(
        f"{_OLLAMA_HOST}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip() or None
    except Exception as e:
        print(f"  [local judge] 呼叫失敗：{e}")
        return None


def _score_faithfulness(instruction: str, output: str) -> tuple[float | None, str]:
    """回傳 (score 0.0/1.0, confidence)；失敗回 (None, '')"""
    prompt = _FAITHFULNESS_PROMPT.format(instruction=instruction.strip(), output=output.strip())
    text = _call_local_judge(prompt)
    if not text:
        return None, ""
    try:
        data = json.loads(_strip_markdown(text))
        score = 1.0 if data.get("faithful") else 0.0
        conf = data.get("confidence", "")
        return score, conf
    except Exception:
        return None, ""


def action_faithfulness(run_id: str, limit: int | None = None) -> dict:
    """B.3 主流程：對 training_samples 跑 Faithfulness，寫 judge_agreement_logs.ragas_faithfulness"""
    with get_connection() as conn:
        sql = """SELECT ts.id, ts.instruction, ts.output, ts.status,
                        jal.id AS log_id
                 FROM training_samples ts
                 LEFT JOIN judge_agreement_logs jal ON jal.sample_id = ts.id
                   AND jal.ragas_faithfulness IS NULL
                 WHERE ts.output IS NOT NULL AND ts.instruction IS NOT NULL
                   AND ts.status IN ('approved', 'rejected')
                 ORDER BY ts.id"""
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql).fetchall()

    print(f"\n── B.3 Faithfulness（qwen3:30b，{len(rows)} 筆）─────────────")
    scores: list[float] = []
    approved_faithful = 0
    approved_total = 0

    for i, row in enumerate(rows, 1):
        score, conf = _score_faithfulness(row["instruction"], row["output"])
        tag = "✓" if score == 1.0 else ("✗" if score == 0.0 else "?")
        status = row["status"]
        print(f"[{i:3d}] id={row['id']} {status} {tag}(conf={conf}) | {row['instruction'][:45]}")

        if score is None:
            continue
        scores.append(score)

        if status == "approved":
            approved_total += 1
            if score >= 0.8:
                approved_faithful += 1

        # 寫回 evaluation_results
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO evaluation_results
                   (run_id, phase, metric_name, metric_value, evaluator_model, sample_id)
                   VALUES (?, 'layer2', 'faithfulness', ?, ?, ?)""",
                (run_id, score, f"local/{_OLLAMA_MODEL}", row["id"]),
            )
            # 若有對應 log，更新 ragas_faithfulness
            if row["log_id"]:
                conn.execute(
                    "UPDATE judge_agreement_logs SET ragas_faithfulness=? WHERE id=?",
                    (score, row["log_id"]),
                )
            conn.commit()

    avg = sum(scores) / len(scores) if scores else None
    agree_rate = approved_faithful / approved_total if approved_total else None

    print("\n── 摘要 ──────────────────────────────────────────")
    print(f"  評估筆數: {len(scores)}/{len(rows)}")
    print(f"  faithfulness_avg: {avg:.4f}" if avg is not None else "  faithfulness_avg: N/A")
    if agree_rate is not None:
        print(f"  approved 中 faithful≥0.8 佔比: {agree_rate:.4f}（{approved_faithful}/{approved_total}）")

    return {
        "faithfulness_avg": round(avg, 4) if avg else None,
        "approved_faithful_rate": round(agree_rate, 4) if agree_rate else None,
        "n_scored": len(scores),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Phase B Layer 2 Judge 可靠性評估")
    p.add_argument("--action", required=True, choices=["kappa", "faithfulness", "all"])
    p.add_argument("--limit", type=int, default=None, help="faithfulness 樣本上限")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    run_id = args.run_id or f"layer2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

    if args.action in ("kappa", "all"):
        action_kappa(run_id)
    if args.action in ("faithfulness", "all"):
        action_faithfulness(run_id, limit=args.limit)


if __name__ == "__main__":
    main()
