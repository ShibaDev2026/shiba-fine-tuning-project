"""
Harness cosine-bound probe — 判定 cosine(bge-m3) top-15 漏掉多少實際 relevant session。

spec：docs/archive/plans/2026-06-21-harness-cosine-bound-probe.md
性質：experiments 隔離實驗，**唯讀 DB、不碰 production hot path、不寫任何表**。

判定：cosine_miss_rate = Σ|R - C| / Σ|R|
  C = cosine(bge-m3) top-15 召回的 session 集合（被測對象）
  R = 在 union pool（cosine ∪ FTS5 ∪ e5）上「盲標」出的 relevant session 集合
  ≤25% → cosine 召回足強、B 組關閉；>25% → 缺陷有後果、大修掙得正當性

用法：
  python probe.py --action sample            # 抽 N query 看一眼（純 DB）
  python probe.py --action build-e5-cache    # 全庫 instruction → e5 embedding 快取（需 e5 endpoint）
  python probe.py --action preview           # dry-run：建 union pool + 印盲標 prompt（不呼叫標註 LLM）
  python probe.py --action run               # 實跑：盲標 + 算 cosine_miss_rate + 寫 RESULT.md
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
from pathlib import Path

# 專案根加入 sys.path（experiments 在兩層下）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from layer_1_memory.lib.db import get_connection
from layer_1_memory.lib.embedder import cosine_similarity
from layer_1_memory.lib.rag import _vector_search
from modules.ragas.golden_set_builder import _ANNOTATION_PROMPT

# ── 設定（可由 CLI 覆寫）─────────────────────────────────────────────
# 註：函數/變數沿用 e5_* 作「第二 embedding」代稱；實際 model 由 SECOND_MODEL 指定。
LMS_BASE = "http://localhost:1234/v1"               # 標註裁判 endpoint（local-qwen）
OLLAMA_BASE = "http://localhost:11434"              # 第二 embedding endpoint
SECOND_MODEL = "snowflake-arctic-embed2"            # 正交 BAAI 的多語 embedding，暴露語意漏網
QWEN_MODEL = "qwen/qwen3.5-35b-a3b"                 # 標註裁判（Layer 2 active local-qwen）
COSINE_K = 15        # 被測：cosine top-15（與 golden_set_builder vector_n 一致）
FTS_K = 50           # aggressive lexical
E5_K = 15            # 第二 embedding top-k（語意漏網）
SEED = 20260621
CACHE_FILE = Path(__file__).parent / "e5_cache.json"
RESULT_FILE = Path(__file__).parent / "RESULT.md"

# 與 _vector_search 一致的高發散過濾（同候選空間，確保「漏」是真漏非故意排除）
_DIVERGENCE_FILTER = (
    "instruction IN (SELECT instruction FROM exchange_embeddings "
    "GROUP BY instruction HAVING count(DISTINCT commands) < 3)"
)


# ── LM Studio OpenAI-compatible 呼叫（urllib，與 embedder.py 同 pattern）──
def _post(path: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        f"{LMS_BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def e5_embed(text: str) -> list[float]:
    """第二 embedding 向量：經 ollama /api/embeddings（SECOND_MODEL，預設 arctic-embed2）。"""
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/embeddings",
        data=json.dumps({"model": SECOND_MODEL, "prompt": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())["embedding"]


def qwen_annotate(prompt: str) -> dict:
    """經 LM Studio /v1/chat/completions 用 local-qwen 盲標；reasoning_effort=none 關 thinking。"""
    data = _post("/chat/completions", {
        "model": QWEN_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 1024,
        "reasoning_effort": "none",   # 唯一對 qwen/glm 有效的關 thinking 法（見 CLAUDE.md）
    })
    text = data["choices"][0]["message"]["content"]
    # 容忍 markdown code fence
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


# ── 取樣 ─────────────────────────────────────────────────────────────
def load_golden_queries(n: int) -> list[dict]:
    """從 active golden 抽 n 個 query（固定 seed 可重現）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT query, expected_session_uuids FROM ragas_retrieval_golden_set "
            "WHERE is_active = 1"
        ).fetchall()
    items = [{"query": r["query"],
              "old_gt": set(json.loads(r["expected_session_uuids"]))} for r in rows]
    random.Random(SEED).shuffle(items)
    return items[:n]


# ── e5 全庫快取 ───────────────────────────────────────────────────────
def build_e5_cache() -> None:
    """全庫 instruction（同 _vector_search 過濾）→ e5 embedding，寫 cache。冪等可續跑。"""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, session_uuid, instruction, commands, exchange_id "
            f"FROM exchange_embeddings WHERE {_DIVERGENCE_FILTER}"
        ).fetchall()
    cache = {}
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text())
    total = len(rows)
    print(f"全庫候選 {total} 筆，已快取 {len(cache)}")
    for i, r in enumerate(rows, 1):
        rid = str(r["id"])
        if rid in cache:
            continue
        cache[rid] = {
            "session_uuid": r["session_uuid"],
            "instruction": r["instruction"],
            "commands": r["commands"],
            "exchange_id": r["exchange_id"],
            "vec": e5_embed(r["instruction"]),   # 對照公平：只編碼 instruction
        }
        if i % 50 == 0:
            CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False))
            print(f"  [{i}/{total}] 已寫快取")
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False))
    print(f"完成：{len(cache)} 筆 e5 embedding 快取於 {CACHE_FILE.name}")


def _load_e5_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        raise RuntimeError(f"缺 e5 快取，先跑 --action build-e5-cache（{CACHE_FILE}）")
    return list(json.loads(CACHE_FILE.read_text()).values())


def e5_topk(query: str, cache: list[dict], k: int = E5_K) -> list[dict]:
    """e5 cosine top-k（exchange-level，與 cosine 召回單位一致）。"""
    qv = e5_embed(query)
    scored = [(cosine_similarity(qv, c["vec"]), c) for c in cache]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


def _bigrams(s: str) -> set[str]:
    """char-level bigram（中英文皆適用的 lexical 表面特徵）。"""
    s = "".join(s.split()).lower()
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}


def lexical_topk(query: str, cache: list[dict], k: int = FTS_K) -> list[dict]:
    """純 lexical 召回（char-bigram Jaccard over instruction），暴露『字詞重疊但 cosine 低分』漏網。

    取代 sessions_fts（session 級 summary，與 exchange_embeddings 不對齊、對 golden 不 match）。
    """
    qb = _bigrams(query)
    scored = []
    for c in cache:
        cb = _bigrams(c["instruction"])
        inter = len(qb & cb)
        if inter == 0:
            continue
        scored.append((inter / len(qb | cb), c))   # Jaccard
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


# ── union pool 建構 ───────────────────────────────────────────────────
def _repr_text(session_uuid: str, exchange_id, fallback: dict) -> tuple[str, str]:
    """統一從 DB 取代表 Q/A（盲標需文本格式一致、不洩來源）。"""
    with get_connection() as conn:
        if exchange_id is not None:
            r = conn.execute(
                "SELECT instruction, commands FROM exchange_embeddings WHERE exchange_id=? LIMIT 1",
                (exchange_id,)).fetchone()
            if r:
                return r["instruction"] or "", r["commands"] or ""
        r = conn.execute(
            "SELECT instruction, commands FROM exchange_embeddings WHERE session_uuid=? LIMIT 1",
            (session_uuid,)).fetchone()
        if r:
            return r["instruction"] or "", r["commands"] or ""
    return fallback.get("instruction", ""), fallback.get("commands", "")


def build_union(query: str, e5_cache: list[dict]) -> tuple[list[dict], set[str]]:
    """建 cosine ∪ FTS5 ∪ e5 union pool。回 (candidates, cosine_session_set)。"""
    cos = _vector_search(query, top_n=COSINE_K)
    cosine_sessions = {r["session_uuid"] for r in cos}

    lex = lexical_topk(query, e5_cache, k=FTS_K)
    e5 = e5_topk(query, e5_cache)

    by_uuid: dict[str, dict] = {}
    def _add(uuid, exchange_id, fb):
        if uuid not in by_uuid:
            by_uuid[uuid] = {"session_uuid": uuid, "exchange_id": exchange_id, "_fb": fb}

    for r in cos:
        _add(r["session_uuid"], r.get("exchange_id"), r)
    for c in lex:
        _add(c["session_uuid"], c.get("exchange_id"), c)
    for c in e5:
        _add(c["session_uuid"], c.get("exchange_id"), c)

    candidates = []
    for uuid, c in by_uuid.items():
        q, a = _repr_text(uuid, c.get("exchange_id"), c["_fb"])
        candidates.append({"session_uuid": uuid, "q": q, "a": a})

    # leave-one-out：剔除與 query 完全相同的候選（query 自身的重複出現）。
    # 否則它必被 cosine 召回、必被標 relevant → 同時膨脹分母與必中項，稀釋 cosine_miss_rate。
    qnorm = query.strip()
    self_uuids = {c["session_uuid"] for c in candidates if c["q"].strip() == qnorm}
    candidates = [c for c in candidates if c["session_uuid"] not in self_uuids]
    cosine_sessions = cosine_sessions - self_uuids
    for c in candidates:
        c["in_cosine"] = c["session_uuid"] in cosine_sessions   # 判定用，不洩給標註者
    return candidates, cosine_sessions


def format_blind(query: str, candidates: list[dict]) -> str:
    """盲標 prompt：遮 source/score + 洗牌（去位置偏誤）。"""
    shuffled = candidates[:]
    random.Random(SEED).shuffle(shuffled)
    lines = []
    for i, c in enumerate(shuffled, 1):
        block = f"[{i}] uuid={c['session_uuid']}\n    Q: {c['q'].strip()[:120]}"
        if c["a"]:
            block += f"\n    A: {c['a'].strip()[:150]}"
        lines.append(block)
    return _ANNOTATION_PROMPT.format(query=query, n=len(shuffled),
                                     candidates="\n\n".join(lines))


# ── 主流程 ───────────────────────────────────────────────────────────
def probe_one(item: dict, e5_cache: list[dict]) -> dict:
    query = item["query"]
    candidates, cosine_sessions = build_union(query, e5_cache)
    prompt = format_blind(query, candidates)
    ann = qwen_annotate(prompt)
    relevant = set(ann.get("relevant_session_uuids", [])) & {c["session_uuid"] for c in candidates}
    missed = relevant - cosine_sessions
    return {
        "query": query,
        "pool_size": len(candidates),
        "cosine_size": len(cosine_sessions),
        "relevant": sorted(relevant),
        "cosine_miss": sorted(missed),
        "n_relevant": len(relevant),
        "n_miss": len(missed),
    }


def action_run(n: int) -> None:
    e5_cache = _load_e5_cache()
    items = load_golden_queries(n)
    results = []
    tot_rel, tot_miss = 0, 0
    for i, item in enumerate(items, 1):
        r = probe_one(item, e5_cache)
        results.append(r)
        tot_rel += r["n_relevant"]
        tot_miss += r["n_miss"]
        print(f"[{i}/{len(items)}] miss={r['n_miss']}/{r['n_relevant']} :: {r['query'][:45]}")
    rate = (tot_miss / tot_rel) if tot_rel else 0.0
    verdict = "缺陷有後果 → golden set 大修" if rate > 0.25 else "cosine 召回足強 → B 組關閉"
    _write_result(results, tot_rel, tot_miss, rate, verdict, n)
    print(f"\ncosine_miss_rate = {tot_miss}/{tot_rel} = {rate:.1%} → {verdict}")


def _write_result(results, tot_rel, tot_miss, rate, verdict, n) -> None:
    lines = [
        "# Harness cosine-bound probe — RESULT",
        "",
        f"- n_query = {n}（active golden, seed={SEED}）",
        f"- 標註者 = local-qwen 盲標（{QWEN_MODEL}）｜第二 embedding = {SECOND_MODEL}",
        f"- **cosine_miss_rate = {tot_miss}/{tot_rel} = {rate:.1%}**",
        f"- 判定門檻 = 25%（>25% 缺陷有後果）→ **{verdict}**",
        "",
        "| # | n_miss/n_rel | pool | query |",
        "|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r['n_miss']}/{r['n_relevant']} | {r['pool_size']} | "
                     f"{r['query'][:50].replace('|', '/')} |")
    lines += ["", "## 每 query cosine 漏掉的 relevant session", ""]
    for i, r in enumerate(results, 1):
        if r["cosine_miss"]:
            lines.append(f"- #{i} `{r['query'][:40]}` → 漏 {r['cosine_miss']}")
    RESULT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"RESULT 寫入 {RESULT_FILE.name}")


def action_preview(n: int) -> None:
    """dry-run：建 union pool + 印盲標 prompt（不呼叫標註 LLM；需 e5 cache + cosine/fts 服務）。"""
    e5_cache = _load_e5_cache()
    for item in load_golden_queries(n):
        candidates, cosine_sessions = build_union(item["query"], e5_cache)
        print("=" * 80)
        print(f"query: {item['query']}")
        print(f"pool={len(candidates)} cosine={len(cosine_sessions)} "
              f"non_cosine={len(candidates) - len(cosine_sessions)}")
        print(format_blind(item["query"], candidates))
        print()


def action_sample(n: int) -> None:
    for i, item in enumerate(load_golden_queries(n), 1):
        print(f"{i:2d}. [{len(item['old_gt'])} old_gt] {item['query'][:60]}")


def action_audit(n: int) -> None:
    """判別檢查：印各源 distinct-session 數，分辨『三源真重疊』vs『擴展源餓死→probe 盲』。"""
    e5_cache = _load_e5_cache()
    for i, item in enumerate(load_golden_queries(n), 1):
        q = item["query"]
        cset = {r["session_uuid"] for r in _vector_search(q, top_n=COSINE_K)}
        lset = {c["session_uuid"] for c in lexical_topk(q, e5_cache, k=FTS_K)}
        aset = {c["session_uuid"] for c in e5_topk(q, e5_cache)}
        union = cset | lset | aset
        print(f"[{i:2d}] |cos|={len(cset):2d} |lex|={len(lset):2d} |arc|={len(aset):2d} "
              f"|union|={len(union):2d} | arc_outside_cos={len(aset - cset):2d} "
              f"lex_outside_cos={len(lset - cset):2d} :: {q[:32]}")


def main():
    global SECOND_MODEL, QWEN_MODEL
    p = argparse.ArgumentParser(description="Harness cosine-bound probe")
    p.add_argument("--action", required=True,
                   choices=["sample", "build-e5-cache", "preview", "audit", "run"])
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--second-model", default=SECOND_MODEL)
    p.add_argument("--qwen-model", default=QWEN_MODEL)
    args = p.parse_args()
    SECOND_MODEL, QWEN_MODEL = args.second_model, args.qwen_model

    if args.action == "sample":
        action_sample(args.n)
    elif args.action == "build-e5-cache":
        build_e5_cache()
    elif args.action == "preview":
        action_preview(args.n)
    elif args.action == "audit":
        action_audit(args.n)
    elif args.action == "run":
        action_run(args.n)


if __name__ == "__main__":
    main()
