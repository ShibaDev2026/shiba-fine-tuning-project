"""
c2_e2e_evaluation.py — Phase C.2/C.3 E2E RAG 品質評估

流程：
  1. 從 retrieval_golden_set 讀取有 expected_answer 的 query
  2. retrieve_for_eval(query, k=3) 取得 RAG context
  3. 以 context + query 呼叫生成模型
  4. Gemini Flash-Lite judge：比對 generated vs expected_answer，評分 0-10
  5. 寫入 evaluation_results（phase="e2e"），run summary 寫 evaluation_runs

執行：
  python -m evaluation.c2_e2e_evaluation run                    # 預設 qwen3:30b-a3b
  python -m evaluation.c2_e2e_evaluation run --model claude:claude-sonnet-4-6
  python -m evaluation.c2_e2e_evaluation run --limit 5 --dry-run
  python -m evaluation.c2_e2e_evaluation compare <run_id_1> <run_id_2>

C.3 雙模型比較：
  python -m evaluation.c2_e2e_evaluation run                                   # run_id_A
  python -m evaluation.c2_e2e_evaluation run --model claude:claude-sonnet-4-6  # run_id_B
  python -m evaluation.c2_e2e_evaluation compare e2e-qwen-... e2e-claude-...
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients.base import AIClientError
from clients.ollama import OllamaClient
from layer_1_memory.lib.db import get_connection
from layer_1_memory.lib.rag import retrieve_for_eval
from layer_2_chamber.backend.services.teacher_service import (
    _call_gemini_rest, _call_anthropic, get_api_key, _strip_markdown,
)

_SCORE_THRESHOLD = 7.0

# Judge 模型：改用 flash 主力（避開 flash-lite 在 PT 尖峰時段的 503 spike）
# 配額 500 RPM / 5000 RPD 對 28 筆批次綽綽有餘
_JUDGE_MODEL = "gemini-2.5-flash"

# RAG 注入後生成用 prompt
_RAG_PROMPT = """你是 Shiba 開發助理，根據以下歷史記錄回答問題。

【歷史記錄】
{contexts}

【問題】
{query}

用繁體中文回答（50-120字），若歷史記錄無直接相關，根據問題本身給最佳答案："""

# Gemini judge：比對生成答案 vs 參考答案
_E2E_JUDGE_PROMPT = """評估「生成答案」對「參考答案」的語意吻合程度與資訊完整性。

【Query】
{query}

【參考答案（Ground Truth）】
{expected}

【生成答案】
{generated}

評分標準（0-10）：
- 10：語意完全吻合，資訊完整
- 7-9：大致吻合，有些細節缺漏
- 4-6：部分相關，但關鍵資訊缺失
- 0-3：語意偏離或資訊錯誤

只回覆 JSON：{{"score": <數字>, "reason": "<一句說明>"}}"""

_SCHEMA_RUNS = """
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL UNIQUE,
    phase       TEXT    NOT NULL,
    model_spec  TEXT,
    sample_count INTEGER,
    mean_score  REAL,
    started_at  TEXT,
    finished_at TEXT,
    metadata    JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _ensure_runs_table() -> None:
    with get_connection() as conn:
        conn.execute(_SCHEMA_RUNS)
        conn.commit()


def _write_run_summary(
    run_id: str,
    model_spec: str,
    sample_count: int,
    mean_score: float | None,
    started_at: str,
    finished_at: str,
    metadata: dict | None = None,
) -> None:
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO evaluation_runs
               (run_id, phase, model_spec, sample_count, mean_score, started_at, finished_at, metadata)
               VALUES (?, 'e2e', ?, ?, ?, ?, ?, ?)""",
            (run_id, model_spec, sample_count, mean_score, started_at, finished_at, meta_json),
        )
        conn.commit()


def _write_eval_result(
    run_id: str,
    metric_name: str,
    metric_value: float,
    evaluator_model: str,
    sample_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO evaluation_results
               (run_id, phase, metric_name, metric_value, evaluator_model, sample_id, metadata)
               VALUES (?, 'e2e', ?, ?, ?, ?, ?)""",
            (run_id, metric_name, metric_value, evaluator_model, sample_id, meta_json),
        )
        conn.commit()


# ── 生成後端 ─────────────────────────────────────────────────────────────────

# Ollama client 共用實例：寫 ai_api_call_logs（source_type='local'），
# 不設 HTTP timeout（qwen3 thinking mode 單筆可達 60-180s），
# 連線拒絕走 1 次重試 → AITransientError；404/空回應 → AIPermanentError。
_OLLAMA_CLIENT = OllamaClient()


def _call_ollama(model: str, prompt: str, sample_id: int | None = None) -> str | None:
    """呼叫本地 Ollama，回傳生成文字或 None。
    失敗會 raise AIClientError 給上層整批熔斷；極端例外才回 None。
    """
    # max_tokens=4096：qwen3 thinking mode 在 E2E 多 context 下，
    # 2048 仍有約 15% 機率 done_reason=length 被截斷 → 空回應熔斷整批
    text, _, _, _ = _OLLAMA_CLIENT.generate(
        model_id=model,
        prompt=prompt,
        max_tokens=4096,
        caller_module="c2_e2e_evaluation.generate",
        sample_id=sample_id,
    )
    return text


def _call_claude(model_id: str, prompt: str, max_tokens: int = 200) -> str | None:
    """呼叫 Anthropic Claude API（走 teacher_service._call_anthropic）"""
    api_key = get_api_key("anthropic-api-key")
    if not api_key:
        print("  [Claude] 無 API key")
        return None
    text, _, _, status = _call_anthropic(
        api_key=api_key,
        api_base="https://api.anthropic.com/v1",
        model_id=model_id,
        prompt=prompt,
        max_tokens=max_tokens,
        effort="medium",
    )
    if status != "success" or not text:
        print(f"  [Claude] 呼叫失敗（{status}）")
        return None
    return text.strip()


def _generate_answer(
    model_spec: str, query: str, contexts: list[str], sample_id: int | None = None
) -> str | None:
    """根據 model_spec 選擇後端，RAG prompt 注入 context 後生成答案"""
    ctx_text = "\n".join(f"- {c[:150]}" for c in contexts) if contexts else "（無相關歷史記錄）"
    prompt = _RAG_PROMPT.format(query=query.strip(), contexts=ctx_text)

    vendor, model_id = model_spec.split(":", 1)
    if vendor == "ollama":
        return _call_ollama(model_id, prompt, sample_id=sample_id)
    elif vendor == "claude":
        return _call_claude(model_id, prompt)
    else:
        print(f"  [generate] 不支援的 vendor：{vendor}")
        return None


# ── Gemini judge ──────────────────────────────────────────────────────────────

def _judge_answer(query: str, expected: str, generated: str) -> tuple[float | None, str]:
    """用 Gemini Flash-Lite 評分，回傳 (score, reason)"""
    api_key = get_api_key("gemini-api-key")
    if not api_key:
        return None, "無 API key"
    prompt = _E2E_JUDGE_PROMPT.format(
        query=query.strip(),
        expected=expected.strip(),
        generated=generated.strip(),
    )
    text, _, _, status = _call_gemini_rest(
        api_key, _JUDGE_MODEL, prompt, max_tokens=100,
        caller_module="c2_e2e_evaluation.judge",
        disable_thinking=True,  # flash 預設啟用 thinking，會吃光 max_tokens=100 預算
    )
    if status != "success" or not text:
        return None, f"Gemini 呼叫失敗（{status}）"
    try:
        data = json.loads(_strip_markdown(text))
        return float(data["score"]), str(data.get("reason", ""))
    except Exception:
        return None, "解析失敗"


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(
    model_spec: str = "ollama:qwen3:30b-a3b",
    limit: int | None = None,
    dry_run: bool = False,
    skip_scoring: bool = False,
    top_n: int = 3,
) -> str:
    """執行 E2E 評估，回傳 run_id。"""
    _ensure_runs_table()

    vendor, model_id = model_spec.split(":", 1)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"e2e-{vendor}-{ts}"
    started_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        sql = """
            SELECT id, query, expected_answer
            FROM retrieval_golden_set
            WHERE expected_answer IS NOT NULL
              AND is_active = 1
            ORDER BY id
        """
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql).fetchall()

    print(f"\n[C.2 E2E] run_id={run_id}  model={model_spec}  samples={len(rows)}  dry_run={dry_run}\n")

    scores: list[float] = []
    ok = 0
    aborted = False

    try:
        for i, row in enumerate(rows, 1):
            qid = row["id"]
            query = row["query"]
            expected = row["expected_answer"]

            # RAG 召回
            rag = retrieve_for_eval(query, top_n=top_n)
            contexts = rag.get("retrieved_contexts", [])
            source = rag.get("source", "?")
            n_ctx = len(contexts)

            print(f"[{i:2d}/{len(rows)}] id={qid} src={source} ctx={n_ctx} q={query[:50]}")

            if dry_run:
                ctx_preview = (contexts[0][:80] if contexts else "(無)").replace("\n", " ")
                print(f"  context[0]: {ctx_preview}...")
                continue

            # 本地 Ollama 永久錯誤（thinking token 耗盡、空回應）僅 skip 此筆，
            # 不熔斷整批；外部 vendor（Gemini / Anthropic）429/5xx 仍維持熔斷以保護配額。
            try:
                generated = _generate_answer(model_spec, query, contexts, sample_id=qid)
            except AIClientError as e:
                if e.vendor == "ollama" and e.category.value == "permanent":
                    print(f"  ⚠ Ollama 永久錯誤 skip：{e.message[:80]}", file=sys.stderr)
                    continue
                raise
            if vendor == "ollama":
                pass  # Ollama 本地無需 sleep
            else:
                time.sleep(4)  # Anthropic / 外部 API

            if not generated:
                print(f"  ⚠ 生成失敗，跳過")
                continue

            print(f"  → {generated[:80]}...")

            # Gemini judge
            if skip_scoring:
                score, reason = None, ""
            else:
                score, reason = _judge_answer(query, expected, generated)
                time.sleep(4)  # Flash-Lite 速率保護

            score_str = f"{score:.1f}" if score is not None else "N/A"
            flag = score is not None and score < _SCORE_THRESHOLD
            print(f"  score={score_str} {'⚠' if flag else '✓'} {reason[:60]}")

            # 寫 evaluation_results
            if score is not None:
                scores.append(score)
                _write_eval_result(
                    run_id=run_id,
                    metric_name="answer_quality",
                    metric_value=score,
                    evaluator_model=_JUDGE_MODEL,
                    sample_id=qid,
                    metadata={
                        "model_spec": model_spec,
                        "rag_source": source,
                        "n_contexts": n_ctx,
                        "generated": generated[:300],
                        "reason": reason,
                    },
                )
            ok += 1

    except AIClientError as e:
        aborted = True
        print(
            f"\n⛔ 整批熔斷（已完成 {ok}/{len(rows)}）："
            f"{e.category.value} {e.vendor}:{e.model_id} http={e.status_code}",
            file=sys.stderr,
        )
        print(f"   原因：{e.message}", file=sys.stderr)

    finished_at = datetime.now(timezone.utc).isoformat()
    mean_score = round(sum(scores) / len(scores), 4) if scores else None
    status_tag = "中止" if aborted else "完成"

    _write_run_summary(
        run_id=run_id,
        model_spec=model_spec,
        sample_count=ok,
        mean_score=mean_score,
        started_at=started_at,
        finished_at=finished_at,
        metadata={"top_n": top_n, "aborted": aborted},
    )

    print(f"\n── {status_tag} {ok}/{len(rows)}  mean_score={mean_score}  run_id={run_id} ──")
    return run_id


def compare(run_id_1: str, run_id_2: str) -> None:
    """C.3：比對兩個 run_id 的 E2E 評估結果，按 sample_id 對齊輸出。"""
    with get_connection() as conn:
        def fetch_run(rid: str) -> dict:
            meta = conn.execute(
                "SELECT model_spec, mean_score, sample_count FROM evaluation_runs WHERE run_id=?", (rid,)
            ).fetchone()
            rows = conn.execute(
                """SELECT er.sample_id, er.metric_value, er.metadata, rgs.query
                   FROM evaluation_results er
                   JOIN retrieval_golden_set rgs ON rgs.id = er.sample_id
                   WHERE er.run_id=? AND er.metric_name='answer_quality'
                   ORDER BY er.sample_id""",
                (rid,),
            ).fetchall()
            return {"meta": meta, "rows": rows}

        r1 = fetch_run(run_id_1)
        r2 = fetch_run(run_id_2)

    m1 = r1["meta"]
    m2 = r2["meta"]
    model1 = m1["model_spec"] if m1 else run_id_1
    model2 = m2["model_spec"] if m2 else run_id_2

    print(f"\n[C.3 比較]")
    print(f"  A: {run_id_1}  model={model1}  mean={m1['mean_score']}  n={m1['sample_count']}")
    print(f"  B: {run_id_2}  model={model2}  mean={m2['mean_score']}  n={m2['sample_count']}")
    print()

    # 對齊 sample_id
    by_sid_1 = {r["sample_id"]: r for r in r1["rows"]}
    by_sid_2 = {r["sample_id"]: r for r in r2["rows"]}
    all_sids = sorted(set(by_sid_1) | set(by_sid_2))

    wins_a = wins_b = ties = 0
    print(f"{'id':>4}  {'A':>5}  {'B':>5}  {'Δ(A-B)':>7}  query")
    print("-" * 72)
    for sid in all_sids:
        ra = by_sid_1.get(sid)
        rb = by_sid_2.get(sid)
        sa = ra["metric_value"] if ra else float("nan")
        sb = rb["metric_value"] if rb else float("nan")
        delta = sa - sb if (ra and rb) else float("nan")
        q = (ra or rb)["query"][:45]
        sign = ">" if delta > 0.1 else ("<" if delta < -0.1 else "=")
        if sign == ">":
            wins_a += 1
        elif sign == "<":
            wins_b += 1
        else:
            ties += 1
        print(f"{sid:>4}  {sa:>5.1f}  {sb:>5.1f}  {delta:>+7.1f}  {sign}  {q}")

    print("-" * 72)
    print(f"  A wins={wins_a}  B wins={wins_b}  ties={ties}")
    print(f"  mean: A={m1['mean_score']}  B={m2['mean_score']}")


def main() -> None:
    p = argparse.ArgumentParser(description="C.2/C.3 E2E RAG 品質評估")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="執行 E2E 評估")
    r.add_argument("--model", default="ollama:qwen3:30b-a3b",
                   help="模型規格，格式 vendor:model_id（ollama / claude）")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--top-n", type=int, default=3)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--skip-scoring", action="store_true")

    c = sub.add_parser("compare", help="C.3 雙模型比較")
    c.add_argument("run_id_1")
    c.add_argument("run_id_2")

    args = p.parse_args()
    if args.cmd == "run":
        run(
            model_spec=args.model,
            limit=args.limit,
            dry_run=args.dry_run,
            skip_scoring=args.skip_scoring,
            top_n=args.top_n,
        )
    else:
        compare(args.run_id_1, args.run_id_2)


if __name__ == "__main__":
    main()
