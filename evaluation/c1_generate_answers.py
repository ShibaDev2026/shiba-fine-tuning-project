"""
c1_generate_answers.py — Phase C.1 Golden Q&A 標準答案生成

流程：
  1. 從 retrieval_golden_set 讀取尚無 expected_answer 的 query
  2. 從 exchange_embeddings 取 relevant session 的 instruction+commands 作為 context
  3. qwen3:30b-a3b（本地）生成標準答案
  4. Gemini Flash 批次驗收評分（0-10），< 7 flag 給 Shiba 複核
  5. 寫回 retrieval_golden_set.expected_answer

執行：
  python -m evaluation.c1_generate_answers
  python -m evaluation.c1_generate_answers --dry-run      # 只印 prompt，不呼叫模型
  python -m evaluation.c1_generate_answers --skip-scoring # 跳過 Gemini 驗收
  python -m evaluation.c1_generate_answers --limit 5      # 只跑前 5 筆
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from clients.base import AIClientError
from layer_1_memory.lib.db import get_connection
from layer_2_chamber.backend.services.teacher_service import (
    _call_gemini_rest, get_api_key, _strip_markdown,
)

_OLLAMA_HOST = "http://localhost:11434"
_OLLAMA_MODEL = "qwen3:30b-a3b"
_SCORE_THRESHOLD = 7.0  # 低於此分數 flag 給複核

_GENERATE_PROMPT = """你是 Shiba 開發助理的知識庫管理員，負責為 RAG 評估建立標準答案。

根據以下「相關歷史對話」，為「使用者 query」撰寫一個理想的參考答案：

Query：{query}

相關歷史對話：
{context}

格式規則：
- 用繁體中文，50-120字
- 技術問題：給具體步驟或指令
- 狀態確認（是否已啟動等）：是/否 + 一句說明
- 任務指令（完成X後終止等）：「已執行：[任務描述] 完成」格式
- 若歷史對話無直接幫助：根據 query 本身給通用最佳答案

只輸出答案，不要解釋過程："""

_SCORE_PROMPT = """你是評估員。請評分：以下「生成答案」對「使用者 query」的回答品質。

【Query】
{query}

【生成答案】
{answer}

評分標準（0-10）：
- 10：完全切題、具體、準確
- 7-9：大致切題，可能有些遺漏
- 4-6：部分相關但不夠具體
- 0-3：無關或錯誤

只回覆 JSON：{{"score": <數字>, "reason": "<一句說明>"}}
"""


_NOISE_PATTERNS = (
    "<command-name>", "<local-command-stdout>", "<system-reminder>",
    "This session is being continued", "Set model to", "Set effort level",
)

def _is_noise(text: str) -> bool:
    """過濾系統訊息、工具名稱等無意義 context"""
    if not text or len(text.strip()) < 5:
        return True
    # 只含工具名稱（e.g. "Bash, Read, Edit"）
    if all(w.strip() in {"Bash","Read","Edit","Write","Glob","Grep","Agent","ToolSearch","AskUserQuestion","WebFetch","WebSearch","Skill"} for w in text.split(",")):
        return True
    return any(p in text for p in _NOISE_PATTERNS)


def _fetch_context(conn, session_uuids: list[str], max_per_session: int = 3) -> str:
    """從 exchange_embeddings 取 context，過濾雜訊後格式化"""
    if not session_uuids:
        return "（無相關歷史記錄）"
    lines = []
    for uuid in session_uuids[:3]:
        rows = conn.execute(
            "SELECT instruction FROM exchange_embeddings "
            "WHERE session_uuid=? ORDER BY id LIMIT ?",
            (uuid, max_per_session * 2),  # 多取以備過濾
        ).fetchall()
        added = 0
        for r in rows:
            instr = (r["instruction"] or "").strip()
            if _is_noise(instr):
                continue
            lines.append(f"- {instr[:100]}")
            added += 1
            if added >= max_per_session:
                break
    return "\n".join(lines) if lines else "（無可用歷史記錄，請根據 query 本身作答）"


def _generate_with_flash_lite(query: str, context: str) -> str | None:
    """用 Gemini Flash-Lite（1000 RPD free）生成 expected_answer"""
    api_key = get_api_key("gemini-api-key")
    if not api_key:
        print("  [Flash-Lite] 無 API key")
        return None
    prompt = _GENERATE_PROMPT.format(query=query.strip(), context=context)
    text, _, _, status = _call_gemini_rest(
        api_key, "gemini-2.5-flash-lite", prompt,
        force_json=False, max_tokens=200,
        caller_module="c1_generate_answers.generate",
    )
    if status != "success" or not text:
        print(f"  [Flash-Lite] 呼叫失敗（{status}）")
        return None
    return text.strip()


def _score_with_gemini(query: str, answer: str) -> tuple[float | None, str]:
    """用 Gemini Flash-Lite 驗收答案品質，回傳 (score, reason)"""
    api_key = get_api_key("gemini-api-key")
    if not api_key:
        return None, "無 API key"
    prompt = _SCORE_PROMPT.format(query=query.strip(), answer=answer.strip())
    text, _, _, status = _call_gemini_rest(
        api_key, "gemini-2.5-flash-lite", prompt, max_tokens=100,
        caller_module="c1_generate_answers.score",
    )
    if status != "success" or not text:
        return None, f"Gemini 呼叫失敗（{status}）"
    try:
        data = json.loads(_strip_markdown(text))
        return float(data["score"]), str(data.get("reason", ""))
    except Exception:
        return None, "解析失敗"


def run(
    limit: int | None = None,
    dry_run: bool = False,
    skip_scoring: bool = False,
) -> None:
    with get_connection() as conn:
        sql = """
            SELECT id, query, expected_session_uuids
            FROM retrieval_golden_set
            WHERE expected_session_uuids != '[]'
              AND expected_answer IS NULL
              AND is_active = 1
            ORDER BY id
        """
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql).fetchall()

    print(f"\n[C.1] 待生成：{len(rows)} 筆  model={_OLLAMA_MODEL}  dry_run={dry_run}\n")

    flags: list[dict] = []
    ok = 0
    aborted = False

    try:
        for i, row in enumerate(rows, 1):
            qid = row["id"]
            query = row["query"]
            session_uuids = json.loads(row["expected_session_uuids"])

            with get_connection() as conn:
                context = _fetch_context(conn, session_uuids)

            prompt_preview = _GENERATE_PROMPT.format(query=query, context=context)[:200]
            print(f"[{i:2d}/{len(rows)}] id={qid} q={query[:50]}")

            if dry_run:
                print(f"  prompt preview: {prompt_preview}...")
                continue

            # 生成（Gemini Flash-Lite Paid Tier 2000 RPM，仍預留 4s 間隔避免貼近上限）
            answer = _generate_with_flash_lite(query, context)
            time.sleep(4)
            if not answer:
                print(f"  ⚠ 生成失敗，跳過")
                continue

            print(f"  → {answer[:80]}...")

            # 驗收（同上 4s 間隔）
            score, reason = (None, "") if skip_scoring else _score_with_gemini(query, answer)
            if not skip_scoring:
                time.sleep(4)
            score_str = f"{score:.1f}" if score is not None else "N/A"
            flag = score is not None and score < _SCORE_THRESHOLD
            print(f"  score={score_str} {'⚠ FLAG' if flag else '✓'} {reason[:60]}")

            if flag:
                flags.append({"id": qid, "query": query, "answer": answer, "score": score, "reason": reason})

            # 寫回 DB
            with get_connection() as conn:
                conn.execute(
                    "UPDATE retrieval_golden_set SET expected_answer=?, notes=? WHERE id=?",
                    (
                        answer,
                        f"auto-by-qwen3 score={score_str} | {reason[:80]}" if score is not None
                        else "auto-by-qwen3",
                        qid,
                    ),
                )
                conn.commit()
            ok += 1
    except AIClientError as e:
        # 整批熔斷：AI 廠商永久錯誤或暫態重試仍失敗，停止剩餘 query
        # 已在 client 內 send_alert，這裡僅補一行 stderr 提示便於 CLI 觀察
        aborted = True
        print(
            f"\n⛔ 整批熔斷（已完成 {ok}/{len(rows)}）："
            f"{e.category.value} {e.vendor}:{e.model_id} http={e.status_code}",
            file=sys.stderr,
        )
        print(f"   原因：{e.message}", file=sys.stderr)

    status_tag = "中止" if aborted else "完成"
    print(f"\n── {status_tag} {ok}/{len(rows)}，flags={len(flags)} ──")

    if flags:
        print("\n⚠ 需 Shiba 複核（score < 7）：")
        for f in flags:
            print(f"  id={f['id']} score={f['score']:.1f} q={f['query'][:50]}")
            print(f"    → {f['answer'][:80]}")
            print(f"    reason: {f['reason']}")


def main():
    p = argparse.ArgumentParser(description="C.1 Golden Q&A 標準答案生成（qwen3:30b）")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-scoring", action="store_true", help="跳過 Gemini 驗收（節省配額）")
    args = p.parse_args()
    run(limit=args.limit, dry_run=args.dry_run, skip_scoring=args.skip_scoring)


if __name__ == "__main__":
    main()
