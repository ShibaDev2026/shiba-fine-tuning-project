"""
ragas_runner.py — Layer 1 召回評估（Phase A.3）

指標：
  uuid_recall@k   — ground truth UUID 中被召回的比例（真正率）
  uuid_precision@k — 召回 UUID 中屬 ground truth 的比例
  hit@1            — top-1 是否命中任一 ground truth
  mrr              — Mean Reciprocal Rank（第一個命中的排名倒數均值）
  ctx_relevance    — LLM judge 評分：召回的文字片段對 query 的語意相關性

Judge backend（--judge 參數）：
  local  — 本地 qwen3:30b-a3b（OpenAI-compat，port 11434）
  gemini — Gemini 2.5 Flash（Keychain gemini-api-key）
  both   — 先 local，後 gemini
  none   — 僅計算 UUID 型指標，不呼叫 LLM
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from layer_1_memory.lib.db import get_connection
from layer_1_memory.lib.rag import retrieve_for_eval, retrieve_for_eval_with_context
from layer_2_chamber.backend.services.teacher_service import (
    _call_gemini_rest, _call_openai_compat, _strip_markdown, get_api_key,
)


# ── Judge prompt ──────────────────────────────────────────────────────────────
_JUDGE_PROMPT = """你是 RAG 召回品質評分員。任務：判斷下列歷史對話片段對使用者 query 是否具有語意相關性。

【query】
{query}

【召回片段】（共 {n} 筆）
{contexts}

請逐筆判斷，以 JSON 輸出（不要加 markdown code fence）：
{{
  "judgments": [
    {{"index": 1, "relevant": true, "reason": "一句話說明"}},
    ...
  ]
}}

判斷標準：
- relevant=true：片段在意圖/領域/操作對象上與 query 相似，或能直接幫助回答 query
- relevant=false：僅表面字詞重疊但語意不符，或過於通用
"""


def _format_contexts_for_judge(contexts: list[str]) -> str:
    lines = []
    for i, ctx in enumerate(contexts, 1):
        lines.append(f"[{i}] {ctx.strip()[:200]}")
    return "\n\n".join(lines)


# ── UUID 型指標（deterministic，不需 LLM）────────────────────────────────────

def _compute_uuid_metrics(
    retrieved_uuids: list[str],
    ground_truth_uuids: list[str],
) -> dict[str, float]:
    """計算 UUID 集合型指標。ground_truth_uuids 為空時回傳全 None。"""
    if not ground_truth_uuids:
        return {"uuid_recall": None, "uuid_precision": None, "hit@1": None, "mrr": None}

    gt_set = set(ground_truth_uuids)
    ret_list = retrieved_uuids  # 保留順序以計算 MRR

    hits = [u for u in ret_list if u in gt_set]
    recall = len(hits) / len(gt_set) if gt_set else 0.0
    precision = len(hits) / len(ret_list) if ret_list else 0.0
    hit1 = 1.0 if (ret_list and ret_list[0] in gt_set) else 0.0

    # MRR：第一個命中的排名倒數
    mrr = 0.0
    for rank, u in enumerate(ret_list, 1):
        if u in gt_set:
            mrr = 1.0 / rank
            break

    return {
        "uuid_recall": round(recall, 4),
        "uuid_precision": round(precision, 4),
        "hit@1": hit1,
        "mrr": round(mrr, 4),
    }


# ── LLM Context Relevance judge ───────────────────────────────────────────────

_OLLAMA_HOST = "http://localhost:11434"
_OLLAMA_MODEL = "qwen3:30b-a3b"


def _judge_local(query: str, contexts: list[str]) -> float | None:
    """
    本地 qwen3:30b-a3b 評估 ctx_relevance，回傳 [0.0, 1.0] 或 None（失敗）。
    走 Ollama native /api/generate（think:false），避免 OpenAI-compat 接口
    把 reasoning 放 content 而非 response 欄位的問題。
    """
    import urllib.request, urllib.error

    if not contexts:
        return 0.0
    prompt = _JUDGE_PROMPT.format(
        query=query,
        n=len(contexts),
        contexts=_format_contexts_for_judge(contexts),
    )
    body = json.dumps({
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 512},
    }).encode()
    req = urllib.request.Request(
        f"{_OLLAMA_HOST}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            text = data.get("response", "").strip()
    except Exception as e:
        print(f"  [local] Ollama 呼叫失敗：{e}")
        return None

    if not text:
        return None
    try:
        parsed = json.loads(_strip_markdown(text))
        judgments = parsed.get("judgments", [])
        if not judgments:
            return 0.0
        return round(sum(1 for j in judgments if j.get("relevant")) / len(judgments), 4)
    except Exception:
        return None


def _judge_gemini(query: str, contexts: list[str]) -> float | None:
    """Gemini 2.5 Flash 評估 ctx_relevance，回傳 [0.0, 1.0] 或 None（失敗）"""
    if not contexts:
        return 0.0
    api_key = get_api_key("gemini-api-key")
    if not api_key:
        return None
    prompt = _JUDGE_PROMPT.format(
        query=query,
        n=len(contexts),
        contexts=_format_contexts_for_judge(contexts),
    )
    text, _, _, status = _call_gemini_rest(
        api_key=api_key,
        model_id="gemini-2.5-flash",
        prompt=prompt,
        force_json=True,
        max_tokens=512,
    )
    if status == "quota_exceeded":
        print("  [Gemini] 配額耗盡，跳過此筆")
        return None
    if status != "success" or not text:
        return None
    try:
        data = json.loads(_strip_markdown(text))
        judgments = data.get("judgments", [])
        if not judgments:
            return 0.0
        return round(sum(1 for j in judgments if j.get("relevant")) / len(judgments), 4)
    except Exception:
        return None


# ── DB 寫入 ───────────────────────────────────────────────────────────────────

def _write_eval_result(
    run_id: str,
    phase: str,
    metric_name: str,
    metric_value: float,
    evaluator_model: str,
    sample_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO ragas_evaluation_results
               (run_id, phase, metric_name, metric_value, evaluator_model, sample_id, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, phase, metric_name, metric_value, evaluator_model, sample_id, meta_json),
        )
        conn.commit()


# ── 主評估迴圈 ────────────────────────────────────────────────────────────────

def run_layer1_evaluation(
    judge: str = "both",
    sample_size: int | None = None,
    top_n: int = 3,
    run_id: str | None = None,
    rag_window: int = 0,
) -> dict:
    """
    從 ragas_retrieval_golden_set 讀 ground truth → 呼叫 retrieve_for_eval → 計算指標 → 寫入 DB。

    judge: 'local' | 'gemini' | 'both' | 'none'
    rag_window: 0 走原本單 exchange 召回；≥1 走鄰居 ±K exchange 擴展上下文召回
    """
    run_id = run_id or f"layer1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

    with get_connection() as conn:
        sql = """SELECT id, query, expected_session_uuids
                 FROM ragas_retrieval_golden_set
                 WHERE expected_session_uuids != '[]'
                   AND is_active = 1
                 ORDER BY id"""
        if sample_size:
            sql += f" LIMIT {sample_size}"
        rows = conn.execute(sql).fetchall()

    print(f"\n[A.3 Layer1 Eval] run_id={run_id}  samples={len(rows)}  top_n={top_n}  "
          f"judge={judge}  rag_window={rag_window}\n")

    all_uuid_metrics: dict[str, list[float]] = {
        "uuid_recall": [], "uuid_precision": [], "hit@1": [], "mrr": [],
    }
    ctx_relevance_local: list[float] = []
    ctx_relevance_gemini: list[float] = []

    for i, row in enumerate(rows, 1):
        sample_id = row["id"]
        query = row["query"]
        gt_uuids: list[str] = json.loads(row["expected_session_uuids"])

        # 召回：rag_window=0 走原本單 exchange；≥1 走鄰居擴展
        if rag_window > 0:
            ret = retrieve_for_eval_with_context(
                query, top_n=top_n, window_k=rag_window,
            )
        else:
            ret = retrieve_for_eval(query, top_n=top_n)
        ret_uuids = ret["retrieved_session_uuids"]
        contexts = ret["retrieved_contexts"]
        source = ret["source"]

        # UUID 型指標
        um = _compute_uuid_metrics(ret_uuids, gt_uuids)
        status_str = (f"R={um['uuid_recall']} P={um['uuid_precision']} "
                      f"hit1={um['hit@1']} mrr={um['mrr']}")

        for k, v in um.items():
            if v is not None:
                all_uuid_metrics[k].append(v)
                _write_eval_result(run_id, "layer1", k, v, source, sample_id,
                                   {"ret_uuids": ret_uuids, "gt_uuids": gt_uuids})

        judge_str = ""
        # LLM judge — local
        if judge in ("local", "both"):
            cr_local = _judge_local(query, contexts)
            if cr_local is not None:
                ctx_relevance_local.append(cr_local)
                _write_eval_result(run_id, "layer1", "ctx_relevance", cr_local,
                                   f"local/{_OLLAMA_MODEL}", sample_id,
                                   {"judge": "local", "n_contexts": len(contexts)})
                judge_str += f" | local_cr={cr_local}"

        # LLM judge — gemini（Flash 5 RPM → sleep 12s）
        if judge in ("gemini", "both"):
            cr_gemini = _judge_gemini(query, contexts)
            time.sleep(12)  # Flash 5 RPM 速率保護
            if cr_gemini is not None:
                ctx_relevance_gemini.append(cr_gemini)
                _write_eval_result(run_id, "layer1", "ctx_relevance", cr_gemini,
                                   "gemini-2.5-flash", sample_id,
                                   {"judge": "gemini", "n_contexts": len(contexts)})
                judge_str += f" | gemini_cr={cr_gemini}"

        print(f"[{i:2d}/{len(rows)}] id={sample_id}  {status_str}{judge_str}")
        print(f"       q={query[:50]}")

    # 摘要
    def _avg(lst: list[float]) -> str:
        return f"{sum(lst)/len(lst):.4f}" if lst else "N/A"

    summary = {
        "run_id": run_id,
        "n_samples": len(rows),
        "rag_window": rag_window,
        "uuid_recall_avg": _avg(all_uuid_metrics["uuid_recall"]),
        "uuid_precision_avg": _avg(all_uuid_metrics["uuid_precision"]),
        "hit@1_avg": _avg(all_uuid_metrics["hit@1"]),
        "mrr_avg": _avg(all_uuid_metrics["mrr"]),
        "ctx_relevance_local_avg": _avg(ctx_relevance_local),
        "ctx_relevance_gemini_avg": _avg(ctx_relevance_gemini),
    }

    print("\n── 摘要 ─────────────────────────────")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    return summary


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="RAGAS Layer 1 召回評估")
    p.add_argument("--phase", default="layer1", choices=["layer1"])
    p.add_argument("--judge", default="both",
                   choices=["local", "gemini", "both", "none"])
    p.add_argument("--sample-size", type=int, default=None, help="限制樣本數")
    p.add_argument("--top-n", type=int, default=3, help="召回數量")
    p.add_argument("--run-id", default=None, help="自訂 run_id")
    p.add_argument("--rag-window", type=int, default=0,
                   help="鄰居擴展視窗 K（0=不擴展走舊路徑；≥1 帶上 ±K 鄰居 exchange）")
    args = p.parse_args()

    if args.phase == "layer1":
        run_layer1_evaluation(
            judge=args.judge,
            sample_size=args.sample_size,
            top_n=args.top_n,
            run_id=args.run_id,
            rag_window=args.rag_window,
        )


if __name__ == "__main__":
    main()
