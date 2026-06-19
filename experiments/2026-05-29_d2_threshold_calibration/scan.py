#!/usr/bin/env python3
"""
D2 retrieval 閾值校準掃描（唯讀，不碰 production code）。

目的：rag.py:400 的 `score > 0.35` 是拍腦袋值；本腳本在 retrieval_golden_set（65 題，
有 ground truth session_uuid）上掃不同 cosine 閾值，量 uuid_recall/precision/hit@1/mrr
+ 平均召回數 + 空召回率，找出比 0.35 更合理的門檻。

複用 production 的 get_embedding + cosine_similarity + 相同的高發散 instruction 過濾，
確保掃描結果與線上 _vector_search 一致；唯一變數是閾值與 top_n。
"""
import sys
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # experiments/<slug>/scan.py → 專案根
sys.path.insert(0, str(ROOT))

from layer_1_memory.lib.embedder import get_embedding, cosine_similarity  # noqa: E402

DB = ROOT / "data" / "shiba-brain.db"
TOP_N = 3
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


def load_golden(conn):
    rows = conn.execute(
        """SELECT query, expected_session_uuids
           FROM retrieval_golden_set
           WHERE is_active=1 AND expected_session_uuids != '[]'
           ORDER BY id"""
    ).fetchall()
    return [(r[0], json.loads(r[1])) for r in rows]


def load_candidates(conn):
    # 與 _vector_search 相同的過濾：排除一句話對應 >=3 種 commands 的高發散 instruction
    rows = conn.execute(
        """SELECT session_uuid, embedding FROM exchange_embeddings
           WHERE instruction IN (
               SELECT instruction FROM exchange_embeddings
               GROUP BY instruction HAVING count(DISTINCT commands) < 3
           )"""
    ).fetchall()
    cands = []
    for sid, emb in rows:
        try:
            cands.append((sid, json.loads(emb)))
        except Exception:
            continue
    return cands


def metrics(retrieved, gt):
    gt_set = set(gt)
    hits = [u for u in retrieved if u in gt_set]
    recall = len(hits) / len(gt_set) if gt_set else 0.0
    prec = len(hits) / len(retrieved) if retrieved else 0.0
    hit1 = 1.0 if (retrieved and retrieved[0] in gt_set) else 0.0
    mrr = 0.0
    for rank, u in enumerate(retrieved, 1):
        if u in gt_set:
            mrr = 1.0 / rank
            break
    return recall, prec, hit1, mrr


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    golden = load_golden(conn)
    cands = load_candidates(conn)
    print(f"golden={len(golden)}  candidates={len(cands)}  top_n={TOP_N}")

    # 每題只算一次 query embedding + 全表 cosine，得到排序後的候選清單
    per_query = []
    for q, gt in golden:
        qv = get_embedding(q)
        if qv is None:
            per_query.append((None, gt))
            continue
        scored = sorted(
            ((sid, cosine_similarity(qv, vec)) for sid, vec in cands),
            key=lambda x: x[1], reverse=True,
        )
        per_query.append((scored, gt))

    n_ok = sum(1 for s, _ in per_query if s is not None)
    print(f"embedded_ok={n_ok}/{len(golden)}\n")
    print(f"{'thresh':>7}{'recall':>8}{'prec':>8}{'hit@1':>8}{'mrr':>8}{'avg_ret':>9}{'empty%':>8}")
    for t in THRESHOLDS:
        R = P = H = M = ret = empty = 0.0
        n = 0
        for scored, gt in per_query:
            if scored is None:
                continue
            n += 1
            top = [sid for sid, sc in scored[:TOP_N] if sc > t]
            r, p, h, m = metrics(top, gt)
            R += r; P += p; H += h; M += m; ret += len(top)
            if not top:
                empty += 1
        if n:
            marker = "  <-- 現行" if abs(t - 0.35) < 1e-9 else ""
            print(f"{t:>7.2f}{R/n:>8.3f}{P/n:>8.3f}{H/n:>8.3f}{M/n:>8.3f}{ret/n:>9.2f}{100*empty/n:>7.1f}%{marker}")

    # 決定性分析：top-N 中 hit(命中 gt)vs miss(誤召回）的 score 分布是否可分
    import statistics as st
    hit_scores, miss_scores = [], []
    for scored, gt in per_query:
        if scored is None:
            continue
        gt_set = set(gt)
        for sid, sc in scored[:TOP_N]:
            (hit_scores if sid in gt_set else miss_scores).append(sc)

    def dist(name, xs):
        if xs:
            print(f"{name}: n={len(xs):>4} min={min(xs):.3f} p50={st.median(xs):.3f} "
                  f"avg={st.mean(xs):.3f} max={max(xs):.3f}")

    print("\n── hit vs miss score 分布（阈值可分性）──")
    dist("hit  命中gt ", hit_scores)
    dist("miss 誤召回 ", miss_scores)
    if hit_scores and miss_scores:
        print(f"分離度: hit_avg - miss_avg = {st.mean(hit_scores) - st.mean(miss_scores):+.3f}  "
              f"(接近 0 → 閾值無法區分，需 rerank；明顯為正 → 存在好閾值)")


if __name__ == "__main__":
    main()
