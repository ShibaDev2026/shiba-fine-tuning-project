"""
c2_e2e_evaluation.py — Phase C.2/C.3 E2E RAG 品質評估

流程：
  1. 從 ragas_retrieval_golden_set 讀取有 expected_answer 的 query
  2. retrieve_for_eval(query, k=3) 取得 RAG context
  3. 以 context + query 呼叫生成模型
  4. Gemini Flash-Lite judge：比對 generated vs expected_answer，評分 0-10
  5. 寫入 ragas_evaluation_results（phase="e2e"），run summary 寫 evaluation_runs

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
from layer_1_memory.lib.rag import retrieve_for_eval, retrieve_for_eval_with_context
from layer_2_chamber.backend.services.teacher_service import (
    _call_gemini_rest, _call_anthropic, _call_openai_compat, get_api_key, _strip_markdown,
)

_SCORE_THRESHOLD = 7.0


def _std(xs: list[float]) -> float:
    """N>1 樣本標準差，N≤1 回 0.0（quick noise-floor 統計用）"""
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5

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
            """INSERT INTO ragas_evaluation_results
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


# ── 本地 panel judge（leave-one-out kill-switch 用，no-paid-API）────────────────
#
# kill-switch 只需 within-judge delta（static vs dynamic_loo 同一裁判），單模型偏差
# 在相減中大致抵消 → 不跑三裁判 panel（JIT 循序載入 35B 會讓 195×3 次評分爆死），
# 用單一本地 qwen3.5-35b 常駐評分。參考式 prompt 沿用 _E2E_JUDGE_PROMPT。

def _resolve_local_judge() -> dict | None:
    """從 DB active teachers 取本地 qwen 裁判（含 reasoning_effort=none 映射的 vendor）。

    回傳 {'model_id','api_base','vendor'}；找不到回 None（preflight 會擋下）。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT model_id, api_base FROM teachers "
            "WHERE is_active=1 AND keychain_ref IS NULL AND model_id LIKE '%qwen%' "
            "ORDER BY priority LIMIT 1"
        ).fetchone()
    if not row:
        return None
    # vendor 直接帶 model_id：_thinking_extra_body 只判子字串 'qwen'/'glm'，
    # model_id 'qwen/qwen3.5-35b-a3b' 含 'qwen' → reasoning_effort='none' 生效。
    return {"model_id": row["model_id"], "api_base": row["api_base"], "vendor": row["model_id"]}


def _judge_answer_local(query: str, expected: str, generated: str, judge: dict) -> tuple[float | None, str]:
    """本地裁判評分（參考式，generated vs expected）；max_tokens=512 留 JSON headroom。"""
    prompt = _E2E_JUDGE_PROMPT.format(
        query=query.strip(), expected=expected.strip(), generated=generated.strip(),
    )
    text, _, _, status = _call_openai_compat(
        api_key="none",
        api_base=judge["api_base"],
        model_id=judge["model_id"],
        prompt=prompt,
        max_tokens=512,            # 本地 thinking 模型即使關 thinking 也留足 JSON 預算，避免截斷成空
        vendor=judge["vendor"],
        disable_thinking=True,     # → reasoning_effort='none'（qwen/glm 唯一有效關法）
        caller_module="c2_e2e_evaluation.judge_local",
    )
    if status != "success" or not text:
        return None, f"本地裁判呼叫失敗（{status}）"
    try:
        data = json.loads(_strip_markdown(text))
        return float(data["score"]), str(data.get("reason", ""))
    except Exception:
        return None, "解析失敗"


def _build_static_context(top_n: int = 3) -> list[str]:
    """static arm 對照組：固定高品質範例（不依 query），取 gatekeeper 凍結樣本 top-N 高分。

    跨題共用同一組 → 排除 per-query 召回變因，只當 baseline。回傳的筆數對齊 top_n，
    與 dynamic 召回的 context 量一致，避免「context 量」混淆 delta。
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT expected_output FROM gatekeeper_golden_samples "
            "WHERE is_active=1 ORDER BY score DESC, id LIMIT ?",
            (top_n,),
        ).fetchall()
    return [r["expected_output"] for r in rows]


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(
    model_spec: str = "ollama:qwen3:30b-a3b",
    limit: int | None = None,
    dry_run: bool = False,
    skip_scoring: bool = False,
    top_n: int = 3,
    rag_window: int = 0,
    n_runs: int = 1,
    arm: str = "dynamic",
    judge_backend: str = "local",
) -> str:
    """執行 E2E 評估，回傳 run_id。

    arm（leave-one-out kill-switch 三臂對照，同模型同裁判，只差召回方式）：
      "static"      → 固定 gatekeeper 高分範例（不依 query），baseline
      "dynamic"     → 依 query 召回（含答案自身來源），上界
      "dynamic_loo" → 依 query 召回但排除當題 expected_session_uuids（受測）
      delta(dynamic_loo − static)=召回 generalizable value；delta(dynamic − dynamic_loo)=source 污染量
    judge_backend："local"（本地 qwen 裁判，no-paid-API）/ "gemini"（付費，保歷史可比）。
    rag_window≥1 → retrieve_for_eval_with_context（±K 鄰居擴展，僅 arm='dynamic' 時生效）。
    n_runs≥2 → 每題重複跑 judge K 次，metric_value 寫 mean。
    """
    _ensure_runs_table()

    if arm not in {"static", "dynamic", "dynamic_loo"}:
        raise ValueError(f"未知 arm：{arm}")

    # preflight：本地裁判須在進迴圈前解析成功，否則整批評分全空 → 假 delta（advisor 標的 blocker）
    judge = None
    if judge_backend == "local" and not skip_scoring:
        judge = _resolve_local_judge()
        if judge is None:
            raise RuntimeError("找不到 active 本地 qwen 裁判（teachers is_active=1 & model_id LIKE %qwen%）")

    # static arm 的固定 context 只建一次（跨題共用）
    static_ctx = _build_static_context(top_n=top_n) if arm == "static" else []
    if arm == "static" and not static_ctx:
        raise RuntimeError("static arm 取不到 gatekeeper_golden_samples（is_active=1）")

    vendor, model_id = model_spec.split(":", 1)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"e2e-{vendor}-{arm}-{ts}"
    started_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        sql = """
            SELECT id, query, expected_answer, expected_session_uuids
            FROM ragas_retrieval_golden_set
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
    gen_dropped = 0    # 生成失敗 / Ollama 永久錯誤被 skip 的樣本數
    judge_failed = 0   # 生成成功但 judge 全失敗（解析/呼叫失敗）的樣本數
    loo_fallback = 0   # dynamic_loo：expected_session_uuids 解析失敗→未套 LOO 的樣本數
    aborted = False

    try:
        for i, row in enumerate(rows, 1):
            qid = row["id"]
            query = row["query"]
            expected = row["expected_answer"]

            # arm 決定召回來源（kill-switch 三臂只差這裡）
            if arm == "static":
                contexts, source = static_ctx, "static"
            elif arm == "dynamic_loo":
                # leave-one-out：排除當題 expected_session_uuids 指向的答案來源 session
                try:
                    exclude = set(json.loads(row["expected_session_uuids"] or "[]"))
                except (json.JSONDecodeError, TypeError):
                    exclude = set()
                    loo_fallback += 1  # 未套 LOO，此筆退化成 dynamic（會稀釋污染訊號，須計數）
                rag = retrieve_for_eval(query, top_n=top_n, exclude_session_uuids=exclude)
                contexts, source = rag.get("retrieved_contexts", []), rag.get("source", "?")
            elif rag_window > 0:
                rag = retrieve_for_eval_with_context(query, top_n=top_n, window_k=rag_window)
                contexts, source = rag.get("retrieved_contexts", []), rag.get("source", "?")
            else:
                rag = retrieve_for_eval(query, top_n=top_n)
                contexts, source = rag.get("retrieved_contexts", []), rag.get("source", "?")
            n_ctx = len(contexts)

            print(f"[{i:2d}/{len(rows)}] id={qid} src={source} ctx={n_ctx} q={query[:50]}")

            if dry_run:
                ctx_preview = (contexts[0][:80] if contexts else "(無)").replace("\n", " ")
                print(f"  context[0]: {ctx_preview}...")
                continue

            # 本地 Ollama 永久錯誤（thinking token 耗盡、空回應）僅 skip 此筆，
            # 不熔斷整批；外部 vendor（Gemini / Anthropic）429/5xx 仍維持熔斷以保護配額。
            try:
                gen_start = time.perf_counter()
                generated = _generate_answer(model_spec, query, contexts, sample_id=qid)
                gen_elapsed = time.perf_counter() - gen_start
            except AIClientError as e:
                if e.vendor == "ollama" and e.category.value == "permanent":
                    print(f"  ⚠ Ollama 永久錯誤 skip：{e.message[:80]}", file=sys.stderr)
                    gen_dropped += 1
                    continue
                raise
            if vendor == "ollama":
                pass  # Ollama 本地無需 sleep
            else:
                # Anthropic 是 TPM-based 不撞 RPM，API latency 已吃掉 4s 預算的多數；
                # 動態扣除已耗時，下限 0.5s 涵蓋網路抖動 + 上游 RPM slot 排隊空隙。
                time.sleep(max(0.5, 4.0 - gen_elapsed))

            if not generated:
                print(f"  ⚠ 生成失敗，跳過")
                gen_dropped += 1
                continue

            print(f"  → {generated[:80]}...")

            # Gemini judge（n_runs≥2 時重跑 K 次取 mean）
            if skip_scoring:
                score, reason = None, ""
                raw_scores: list[float] = []
                raw_reasons: list[str] = []
            else:
                raw_scores = []
                raw_reasons = []
                for k in range(n_runs):
                    judge_start = time.perf_counter()
                    if judge_backend == "local":
                        if judge is None:  # preflight 已保證；顯式 raise（避免 -O 下 assert 被剝成靜默）
                            raise RuntimeError("local judge 未解析，preflight 應已擋下")
                        s_k, r_k = _judge_answer_local(query, expected, generated, judge)
                    else:
                        s_k, r_k = _judge_answer(query, expected, generated)
                    judge_elapsed = time.perf_counter() - judge_start
                    if s_k is not None:
                        raw_scores.append(s_k)
                        raw_reasons.append(r_k)
                    # 本地裁判無速率限制；僅付費 Gemini 需動態 sleep（下限 0.5s）
                    if judge_backend != "local":
                        time.sleep(max(0.5, 4.0 - judge_elapsed))
                if raw_scores:
                    score = sum(raw_scores) / len(raw_scores)
                    reason = raw_reasons[0]  # 顯示第一條 reason 即可
                else:
                    score, reason = None, "Judge 全部失敗"

            score_str = f"{score:.2f}" if score is not None else "N/A"
            flag = score is not None and score < _SCORE_THRESHOLD
            extra = f" (K={n_runs} std={_std(raw_scores):.2f})" if n_runs > 1 and raw_scores else ""
            print(f"  score={score_str}{extra} {'⚠' if flag else '✓'} {reason[:60]}")

            # 寫 ragas_evaluation_results
            if score is not None:
                scores.append(score)
                meta = {
                    "model_spec": model_spec,
                    "rag_source": source,
                    "n_contexts": n_ctx,
                    "generated": generated[:300],
                    "reason": reason,
                }
                if n_runs > 1:
                    meta["raw_scores"] = raw_scores
                _write_eval_result(
                    run_id=run_id,
                    metric_name="answer_quality",
                    metric_value=score,
                    evaluator_model=judge["model_id"] if (judge_backend == "local" and judge) else _JUDGE_MODEL,
                    sample_id=qid,
                    metadata=meta,
                )
            elif not skip_scoring:
                judge_failed += 1  # 生成成功但 judge 全失敗 → 此筆不進 mean（須計數，否則存活者偏差）
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

    # drop 會計：存活者偏差是 kill-switch 頭號威脅，drop 計數須大聲、且寫進 metadata 供交集判讀
    total = len(rows)
    scored = len(scores)
    drop_rate = (total - scored) / total if total else 0.0
    _write_run_summary(
        run_id=run_id,
        model_spec=model_spec,
        sample_count=ok,
        mean_score=mean_score,
        started_at=started_at,
        finished_at=finished_at,
        metadata={"top_n": top_n, "rag_window": rag_window, "n_runs": n_runs,
                  "arm": arm, "judge_backend": judge_backend, "aborted": aborted,
                  "total": total, "scored": scored,
                  "gen_dropped": gen_dropped, "judge_failed": judge_failed,
                  "loo_fallback": loo_fallback},
    )
    print(f"\n  drop 會計：scored={scored}/{total}  gen_dropped={gen_dropped}  "
          f"judge_failed={judge_failed}  loo_fallback={loo_fallback}")
    if drop_rate > 0.3:
        print(f"  ⚠⚠ drop_rate={drop_rate:.0%} > 30% → 此臂 mean 不可靠，delta 判讀須存疑（存活者偏差）",
              file=sys.stderr)

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
                   FROM ragas_evaluation_results er
                   JOIN ragas_retrieval_golden_set rgs ON rgs.id = er.sample_id
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


def _killswitch_verdict(run_ids: dict[str, str]) -> None:
    """在三臂【共同存活】sample_id 交集上算 delta，杜絕跨臂存活者偏差污染判讀。

    各臂 drop 數不同（dynamic_loo 召回較薄→更易空生成/判失敗），若各用自身 mean，
    delta 會是 survivorship artifact。故 headline delta 一律在交集上算，並印各臂 drop 會計。
    """
    per_arm: dict[str, dict[int, float]] = {}
    meta_arm: dict[str, dict] = {}
    with get_connection() as conn:
        for arm, rid in run_ids.items():
            rows = conn.execute(
                "SELECT sample_id, metric_value FROM ragas_evaluation_results "
                "WHERE run_id=? AND metric_name='answer_quality'",
                (rid,),
            ).fetchall()
            per_arm[arm] = {r["sample_id"]: r["metric_value"] for r in rows}
            m = conn.execute(
                "SELECT mean_score, metadata FROM evaluation_runs WHERE run_id=?", (rid,)
            ).fetchone()
            meta_arm[arm] = (json.loads(m["metadata"]) if m and m["metadata"] else {}) if m else {}
            meta_arm[arm]["_full_mean"] = m["mean_score"] if m else None

    common = set.intersection(*[set(d) for d in per_arm.values()]) if per_arm else set()
    print(f"\n{'=' * 72}\n[KILL-SWITCH VERDICT]  交集 N={len(common)}（避免跨臂存活者偏差）\n{'=' * 72}")
    for arm in run_ids:
        md = meta_arm[arm]
        inter_mean = (sum(per_arm[arm][s] for s in common) / len(common)) if common else float("nan")
        print(f"  {arm:>12}: scored={len(per_arm[arm]):>2}  full_mean={md.get('_full_mean')}  "
              f"inter_mean={inter_mean:.3f}  "
              f"drop(gen={md.get('gen_dropped','?')},judge={md.get('judge_failed','?')},"
              f"loo_fb={md.get('loo_fallback','?')})")

    if len(common) < 10:
        print(f"  ⚠ 共同存活 N={len(common)} < 10，統計力過低，delta 僅供參考、不下結論")
    if not common:
        print("  ⚠ 三臂無共同存活樣本，無法判讀")
        return

    im = {arm: sum(per_arm[arm][s] for s in common) / len(common) for arm in per_arm}
    d_main = im["dynamic_loo"] - im["static"]
    d_contam = im["dynamic"] - im["dynamic_loo"]
    print(f"\n  ■ 主判讀  Δ(dynamic_loo − static)   = {d_main:+.3f}  （召回 generalizable value）")
    print(f"  ■ 污染量  Δ(dynamic − dynamic_loo) = {d_contam:+.3f}  （answer 自身 source 灌水量）")
    verdict = ("召回有 generalizable value → 路線活" if d_main > 0.3
               else "召回無可測 generalizable value（Δ≈0）→ 此 golden set 測不出，B 路線喊停 / 須重建獨立標註 golden")
    print(f"\n  判讀：{verdict}")


def killswitch(
    model_spec: str = "ollama:qwen3:30b-a3b",
    limit: int | None = None,
    top_n: int = 3,
    judge_backend: str = "local",
) -> dict:
    """B 組 retrieval-delta kill-switch：三臂同模型同裁判，一次跑完並印兩組 delta。

    主判讀 delta(dynamic_loo − static)：召回的 generalizable value
      ≈0 → answer 只能從自身來源召回 → 此 golden set 測不出 generalizable retrieval value
           → B 組 recall 路線喊停 / 須重建獨立標註 golden（flat 本身就是有效 kill 結果）
      ≫0 → 召回有 generalizable value，路線活，才進放大乾淨 golden + few-shot 技術
    污染量 delta(dynamic − dynamic_loo)：answer 自身 source session 對分數的灌水量。
    """
    arms = ["static", "dynamic", "dynamic_loo"]
    run_ids: dict[str, str] = {}
    for a in arms:
        print(f"\n{'=' * 72}\n[KILL-SWITCH] arm={a}  judge={judge_backend}\n{'=' * 72}")
        run_ids[a] = run(
            model_spec=model_spec, limit=limit, top_n=top_n,
            arm=a, judge_backend=judge_backend,
        )
    # headline：交集判讀（杜絕存活者偏差）；compare() 留作逐筆細節
    _killswitch_verdict(run_ids)
    print(f"\n{'#' * 72}\n# 逐筆細節（per-sample，mean 為各臂自身存活集，僅供觀察）\n{'#' * 72}")
    print("\n■ A=dynamic_loo  B=static")
    compare(run_ids["dynamic_loo"], run_ids["static"])
    print("\n■ A=dynamic  B=dynamic_loo")
    compare(run_ids["dynamic"], run_ids["dynamic_loo"])
    print(f"\nrun_ids={run_ids}")
    return run_ids


def main() -> None:
    p = argparse.ArgumentParser(description="C.2/C.3 E2E RAG 品質評估")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="執行 E2E 評估")
    r.add_argument("--model", default="ollama:qwen3:30b-a3b",
                   help="模型規格，格式 vendor:model_id（ollama / claude）")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--top-n", type=int, default=3)
    r.add_argument("--rag-window", type=int, default=0,
                   help="鄰居 exchange 擴展視窗 K（0=baseline 不擴展；建議 A/B 用 2）")
    r.add_argument("--n-runs", type=int, default=1,
                   help="每題 judge 重跑次數 K（K≥2 取 mean，raw_scores 寫 metadata；"
                        "用於量化 LLM judge noise floor）")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--skip-scoring", action="store_true")
    r.add_argument("--arm", default="dynamic", choices=["static", "dynamic", "dynamic_loo"],
                   help="召回臂（kill-switch 對照）")
    r.add_argument("--judge-backend", default="local", choices=["local", "gemini"],
                   help="評分裁判：local 本地 qwen（no-paid）/ gemini 付費")

    c = sub.add_parser("compare", help="C.3 雙模型比較")
    c.add_argument("run_id_1")
    c.add_argument("run_id_2")

    k = sub.add_parser("killswitch", help="B 組 retrieval-delta 三臂一鍵 kill-switch")
    k.add_argument("--model", default="ollama:qwen3:30b-a3b")
    k.add_argument("--limit", type=int, default=None)
    k.add_argument("--top-n", type=int, default=3)
    k.add_argument("--judge-backend", default="local", choices=["local", "gemini"])

    args = p.parse_args()
    if args.cmd == "run":
        run(
            model_spec=args.model,
            limit=args.limit,
            dry_run=args.dry_run,
            skip_scoring=args.skip_scoring,
            top_n=args.top_n,
            rag_window=args.rag_window,
            n_runs=args.n_runs,
            arm=args.arm,
            judge_backend=args.judge_backend,
        )
    elif args.cmd == "killswitch":
        killswitch(
            model_spec=args.model,
            limit=args.limit,
            top_n=args.top_n,
            judge_backend=args.judge_backend,
        )
    else:
        compare(args.run_id_1, args.run_id_2)


if __name__ == "__main__":
    main()
