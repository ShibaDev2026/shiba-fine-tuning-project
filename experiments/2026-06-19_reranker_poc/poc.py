#!/usr/bin/env python3
"""reranker PoC — 驗證 cross-encoder rerank 能否把召回 hit@1/mrr 推過 baseline。

對齊 D2 plan「先 PoC 量淨值再投產」。**PoC only，不碰 production hot path**
（不改 get_rag_context）。對照設計隔離 rerank 純效果：
  同候選池（_vector_search top-10）→ baseline 用 cosine score 排 top-3 session、
  reranker 用 llama-server cross-encoder score 排 top-3 session，兩者只差排序方法。

前置：Ollama（embedding）+ llama-server --reranking :8088（bge-reranker-v2-m3）皆需在跑。
"""
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from shiba_config import CONFIG
from layer_1_memory.lib.rag import _vector_search

RERANK_URL = "http://localhost:8088/v1/rerank"
CANDIDATE_K = 10   # 候選池（rerank 重排的範圍）
TOP_N = 3          # 最終取前 3 session（對齊 baseline）


def rerank(query: str, docs: list[str], batch: int = 8) -> list[float]:
    """呼叫 llama-server cross-encoder rerank，回每個 doc 的 relevance_score（原順序）。

    分批送（≤batch）避開 server 並行 slot 上限的 500；cross-encoder 為 pointwise
    （每 query-doc pair 獨立打分），分批後合併排序不影響正確性。
    """
    scores = [0.0] * len(docs)
    for off in range(0, len(docs), batch):
        chunk = docs[off:off + batch]
        payload = json.dumps({"query": query, "documents": chunk}).encode()
        req = urllib.request.Request(
            RERANK_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read())
        for item in res["results"]:
            scores[off + item["index"]] = item["relevance_score"]
    return scores


def metrics(ret_uuids: list[str], gt_uuids: list[str]):
    """recall / hit@1 / mrr（去重集合，對齊修好的 ragas metric）。gt 空→None。"""
    gt = set(gt_uuids)
    if not gt:
        return None
    recall = len(gt & set(ret_uuids)) / len(gt)
    hit1 = 1.0 if (ret_uuids and ret_uuids[0] in gt) else 0.0
    mrr = 0.0
    for rank, u in enumerate(ret_uuids, 1):
        if u in gt:
            mrr = 1.0 / rank
            break
    return recall, hit1, mrr


def session_topn(cands: list[dict], scores: list[float], n: int) -> list[str]:
    """session 層級聚合：每 session 取候選中 max score，取 top-n session uuid。"""
    best: dict[str, float] = {}
    for c, s in zip(cands, scores):
        u = c["session_uuid"]
        if u not in best or s > best[u]:
            best[u] = s
    return [u for u, _ in sorted(best.items(), key=lambda x: -x[1])[:n]]


def main():
    conn = sqlite3.connect(str(CONFIG.paths.db)); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT query, expected_session_uuids FROM ragas_retrieval_golden_set "
        "WHERE is_active=1 AND expected_session_uuids != '[]' ORDER BY id"
    ).fetchall()

    base = {"recall": [], "hit1": [], "mrr": []}
    rrk = {"recall": [], "hit1": [], "mrr": []}
    flips = 0  # baseline miss hit@1 但 reranker 救回 top-1 的題數

    for row in rows:
        query = row["query"]
        gt = json.loads(row["expected_session_uuids"])
        cands = _vector_search(query, top_n=CANDIDATE_K)
        if not cands:
            continue
        base_top3 = session_topn(cands, [c["score"] for c in cands], TOP_N)
        docs = [f"{c['instruction']} {c['commands']}".strip() for c in cands]
        rrk_top3 = session_topn(cands, rerank(query, docs), TOP_N)

        mb, mr = metrics(base_top3, gt), metrics(rrk_top3, gt)
        if mb and mr:
            base["recall"].append(mb[0]); base["hit1"].append(mb[1]); base["mrr"].append(mb[2])
            rrk["recall"].append(mr[0]); rrk["hit1"].append(mr[1]); rrk["mrr"].append(mr[2])
            if mb[1] == 0.0 and mr[1] == 1.0:
                flips += 1

    def avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    n = len(base["hit1"])
    print(f"\nreranker PoC  n={n}  候選池={CANDIDATE_K} → top-{TOP_N}\n")
    print(f"{'metric':<10}{'baseline(cosine)':<20}{'reranker':<14}{'Δ'}")
    print("-" * 52)
    for k in ["recall", "hit1", "mrr"]:
        b, r = avg(base[k]), avg(rrk[k])
        print(f"{k:<10}{b:<20}{r:<14}{r - b:+.4f}")
    print(f"\nhit@1 救回（baseline miss→reranker top-1 命中）：{flips} 題")


if __name__ == "__main__":
    main()
