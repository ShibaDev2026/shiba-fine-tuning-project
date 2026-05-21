"""
Golden Set 半自動建構工具

流程：sample_queries → build_candidates → annotate_with_claude → write_to_golden_set
所有步驟可獨立執行；Claude API 呼叫獨立成函數，Shiba 可在花錢前複核 prompt。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

# 將專案根加入 sys.path 以便 import layer_1_memory
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from layer_1_memory.lib.db import get_connection
from layer_1_memory.lib.rag import _vector_search, retrieve_relevant_sessions


# ── Query 抽樣黑名單（無意義 query，召回亦無資訊量）──────────────────────
_BLACKLIST = {
    "keep going", "繼續", "好", "ok", "okay", "yes", "對",
    "嗯", "好的", "可以", "了解", "謝謝", "請繼續",
    "next", "continue", "go", "好喔",
}


def sample_queries(n: int = 30, min_len: int = 8, max_len: int = 50) -> list[dict]:
    """
    從 exchange_embeddings.instruction 隨機抽 query 作為 Golden Set 候選。

    過濾規則：
    - 長度 [min_len, max_len]
    - 排除黑名單（無意義通用詞）
    - 排除高發散 instruction（與 _vector_search 一致：count(DISTINCT commands) >= 3）
    - 排除已在 retrieval_golden_set 的 query（防 PR-N.2 擴增時撞題；包含 is_active=0 的汰換題，
      避免 PR-L 棄置題被重新抽中）
    - 同 instruction 去重
    """
    placeholders = ",".join("?" * len(_BLACKLIST))
    sql = f"""
        SELECT instruction, MIN(session_uuid) AS sample_session_uuid
        FROM exchange_embeddings
        WHERE length(instruction) BETWEEN ? AND ?
          AND lower(trim(instruction)) NOT IN ({placeholders})
          AND instruction NOT IN (SELECT query FROM retrieval_golden_set)
          AND instruction IN (
              SELECT instruction
              FROM exchange_embeddings
              GROUP BY instruction
              HAVING count(DISTINCT commands) < 3
          )
        GROUP BY instruction
        ORDER BY RANDOM()
        LIMIT ?
    """
    params = [min_len, max_len, *[w.lower() for w in _BLACKLIST], n]
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{"query": r["instruction"], "sample_session_uuid": r["sample_session_uuid"]} for r in rows]


def build_candidates(query: str, vector_n: int = 15, fts_n: int = 5) -> list[dict]:
    """
    對 query 建構候選池：vector top_n + FTS5 top_n，合併去重後回傳。
    每筆含 source 標籤（'vector' / 'fts5' / 'both'）方便事後分析兩種召回的差異。
    """
    vec_results = _vector_search(query, top_n=vector_n)
    fts_results = retrieve_relevant_sessions(query=query, top_n=fts_n)

    by_uuid: dict[str, dict] = {}
    for r in vec_results:
        uid = r["session_uuid"]
        by_uuid[uid] = {
            "session_uuid": uid,
            "instruction": r["instruction"],
            "commands": r["commands"],
            "score_vector": round(r["score"], 4),
            "score_fts": None,
            "source": "vector",
        }
    for r in fts_results:
        uid = r["session_uuid"]
        if uid in by_uuid:
            by_uuid[uid]["source"] = "both"
            by_uuid[uid]["snippet"] = r.get("snippet", "")
        else:
            by_uuid[uid] = {
                "session_uuid": uid,
                "instruction": "",
                "commands": "",
                "snippet": r.get("snippet", ""),
                "score_vector": None,
                "score_fts": True,
                "source": "fts5",
            }
    return list(by_uuid.values())


# ── Claude 標註 prompt（Opus 設計的核心 IP，可獨立微調）──────────────────
_ANNOTATION_PROMPT = """你是 Layer 1 RAG 評估的標註者。任務：判斷哪些「歷史對話」在使用者問出當前 query 時，能提供有用的脈絡資訊。

【判斷標準】
✅ 相關：歷史對話的問題與當前 query 在意圖、領域、操作對象上相似，或它的回應/指令能直接幫助回答當前 query。
❌ 不相關：表面字詞重疊但語意無關；歷史對話過於通用無法提供具體幫助；只是同樣語言/格式但主題不同。

【重要原則】
- 不要把「答對」與「相關」混淆。歷史對話只要包含可供借鑑的脈絡就算相關。
- 寧缺勿濫：標 2-3 個高品質 > 標 5 個含雜訊。
- 若所有候選都不相關，relevant_session_uuids 回傳空 list。
- 若僅 1-2 個明確相關，不要為了湊數加入勉強的選項。

【當前 query】
{query}

【候選歷史對話】（共 {n} 筆）
{candidates}

請以 JSON 格式輸出（不要加 markdown code fence）：
{{
  "relevant_session_uuids": ["uuid1", "uuid2", ...],
  "confidence": "high",
  "reasoning": "1-2 句話解釋為何這幾個相關"
}}

confidence 只能是 "high" | "medium" | "low" 三選一。
"""


def format_candidates_for_prompt(candidates: list[dict]) -> str:
    """將候選清單格式化為 prompt 可讀的編號清單"""
    lines = []
    for i, c in enumerate(candidates, 1):
        instr = c.get("instruction") or c.get("snippet", "")
        cmds = c.get("commands", "")
        src = c["source"]
        score = c.get("score_vector")
        score_str = f"vec={score}" if score is not None else "fts5"
        block = f"[{i}] uuid={c['session_uuid']} | {src} | {score_str}\n    Q: {instr.strip()[:120]}"
        if cmds:
            block += f"\n    A: {cmds.strip()[:150]}"
        lines.append(block)
    return "\n\n".join(lines)


def build_annotation_prompt(query: str, candidates: list[dict]) -> str:
    """組合最終送給 Claude 的 prompt（dry-run 預覽用）"""
    return _ANNOTATION_PROMPT.format(
        query=query,
        n=len(candidates),
        candidates=format_candidates_for_prompt(candidates),
    )


def annotate_with_claude(
    query: str,
    candidates: list[dict],
    model: str = "claude-sonnet-4-6",
    keychain_ref: str = "anthropic-api-key",
    api_base: str = "https://api.anthropic.com/v1",
    effort: str = "medium",
) -> dict:
    """
    呼叫 Anthropic Messages API 標註，複用 teacher_service 既有基礎設施。
    回傳 dict 包含 relevant_session_uuids / confidence / reasoning。
    Key 來源：Keychain（keychain_ref）→ env fallback，與 teacher 同條路徑。
    """
    from layer_2_chamber.backend.services.teacher_service import (
        get_api_key, _call_anthropic, _strip_markdown,
    )

    api_key = get_api_key(keychain_ref)
    if not api_key:
        raise RuntimeError(f"找不到 API key：Keychain ref={keychain_ref}")

    prompt = build_annotation_prompt(query, candidates)
    text, _in, _out, status = _call_anthropic(
        api_key=api_key,
        api_base=api_base,
        model_id=model,
        prompt=prompt,
        max_tokens=1024,
        effort=effort,
    )
    if status != "success" or not text:
        raise RuntimeError(f"Anthropic 呼叫失敗：status={status}")

    return json.loads(_strip_markdown(text))


def write_to_golden_set(
    query: str,
    annotation: dict,
    annotator: str,
    notes: str | None = None,
) -> int:
    """寫入 retrieval_golden_set 表，回傳 lastrowid"""
    uuids_json = json.dumps(annotation.get("relevant_session_uuids", []), ensure_ascii=False)
    full_notes_parts = []
    if "reasoning" in annotation:
        full_notes_parts.append(f"reasoning: {annotation['reasoning']}")
    if "confidence" in annotation:
        full_notes_parts.append(f"confidence: {annotation['confidence']}")
    if notes:
        full_notes_parts.append(notes)
    full_notes = " | ".join(full_notes_parts) if full_notes_parts else None

    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO retrieval_golden_set
               (query, expected_session_uuids, annotator, notes)
               VALUES (?, ?, ?, ?)""",
            (query, uuids_json, annotator, full_notes),
        )
        conn.commit()
        return cur.lastrowid


# ── CLI ─────────────────────────────────────────────────────────────
def _action_sample(n: int) -> None:
    samples = sample_queries(n=n)
    print(f"抽到 {len(samples)} 筆 query：\n")
    for i, s in enumerate(samples, 1):
        print(f"{i:2d}. {s['query']}")


def _action_preview(n: int) -> None:
    """dry-run：抽 query → 建候選 → 印 prompt（不呼叫 Claude）"""
    samples = sample_queries(n=n)
    for s in samples:
        candidates = build_candidates(s["query"])
        prompt = build_annotation_prompt(s["query"], candidates)
        print("=" * 80)
        print(prompt)
        print()


def _action_annotate(n: int, model: str) -> None:
    """實際呼叫 Claude API 標註並寫入 DB"""
    samples = sample_queries(n=n)
    annotator = f"auto-by-{model}"
    success, skipped = 0, 0
    for i, s in enumerate(samples, 1):
        query = s["query"]
        candidates = build_candidates(query)
        if not candidates:
            print(f"[{i}/{n}] SKIP（無候選）：{query[:40]}")
            skipped += 1
            continue
        try:
            ann = annotate_with_claude(query, candidates, model=model)
            rid = write_to_golden_set(query, ann, annotator)
            n_rel = len(ann.get("relevant_session_uuids", []))
            print(f"[{i}/{n}] OK id={rid} relevant={n_rel} conf={ann.get('confidence')}：{query[:40]}")
            success += 1
        except Exception as e:
            print(f"[{i}/{n}] ERROR：{e}")
    print(f"\n總結：success={success} skipped={skipped} total={n}")


def _action_review() -> None:
    """列出待 Shiba 複核的 auto-annotated 項目"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, query, expected_session_uuids, annotator, notes
               FROM retrieval_golden_set
               WHERE annotator LIKE 'auto-by-%'
                 AND is_active = 1
               ORDER BY id"""
        ).fetchall()
    for r in rows:
        uuids = json.loads(r["expected_session_uuids"])
        print(f"#{r['id']} [{r['annotator']}] {r['query']}")
        print(f"   uuids={uuids}")
        print(f"   notes={r['notes']}\n")


def main():
    p = argparse.ArgumentParser(description="RAGAS Golden Set 半自動建構")
    p.add_argument("--action", required=True, choices=["sample", "preview", "annotate", "review"])
    p.add_argument("--n", type=int, default=30, help="樣本數（sample/preview/annotate）")
    p.add_argument("--model", default="claude-sonnet-4-6", help="標註器 Claude 模型")
    args = p.parse_args()

    if args.action == "sample":
        _action_sample(args.n)
    elif args.action == "preview":
        _action_preview(args.n)
    elif args.action == "annotate":
        _action_annotate(args.n, args.model)
    elif args.action == "review":
        _action_review()


if __name__ == "__main__":
    main()
