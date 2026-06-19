"""grading_harness.py — Claude(本 session) + 本地模型協作評分 harness（v1）。

職責（SRP）：把既有評分 pipeline 串成「可續、可餵 gold」的殼：
  export_gold_candidates → Claude 本 session 評 → ingest_grades 回寫 → freeze。
PII gate（scrub_for_export / assert_clean）：reuse refiner_service.scrub_pii + runtime handle。
不重造評分迴圈／freeze（走 multi_judge / scripts/freeze_golden_set.py）。
"""
from __future__ import annotations

import getpass
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .refiner_service import scrub_pii
from .teacher_service import _update_sample_score

# event_type 平衡選樣集合（對齊 freeze_golden_set.EVENT_TYPES）
EVENT_TYPES = [
    "git_ops", "terminal_ops", "code_gen",
    "debugging", "architecture", "knowledge_qa", "fine_tuning_ops",
]
_USER_PLACEHOLDER = "<USER>"
_EMAIL_PLACEHOLDER = "<EMAIL>"
_IP_PLACEHOLDER = "<LOCAL_IP>"
# refiner.scrub_pii 不含 email pattern（實機驗證：git_ops 樣本含 author/Co-Authored-By email，
# 含 Shiba 個人信箱）→ 在 export 邊界（送 Anthropic 前）補上 email redaction。
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# refiner.scrub_pii 的 IP pattern 只覆蓋 192.168/127.x → export 邊界補滿 RFC1918 私有網段
# （10.x、172.16-31.x）+ loopback，並讓 assert_clean 有 IP backstop（fail-closed）。
_PRIVATE_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
)


def _sensitive_tokens() -> list[str]:
    """runtime 衍生的機敏 token（不 hardcode）：OS 使用者名 + home 目錄名。"""
    toks = {getpass.getuser(), Path.home().name}
    return [t for t in toks if t and len(t) >= 2]


def scrub_for_export(text: str | None) -> str:
    """送 Claude 前 scrub：base refiner scrub + runtime handle → <USER>。None → ""。"""
    if text is None:
        return ""
    out = scrub_pii(text)
    for tok in _sensitive_tokens():
        out = out.replace(tok, _USER_PLACEHOLDER)
    out = _EMAIL_RE.sub(_EMAIL_PLACEHOLDER, out)  # email PII（scrub_pii 未覆蓋）
    out = _PRIVATE_IP_RE.sub(_IP_PLACEHOLDER, out)  # RFC1918 私有 IP（scrub_pii 只覆蓋 192.168/127）
    return out


def assert_clean(text: str) -> None:
    """fail-closed：殘留任一機敏 token → 拋 ValueError（caller 跳過該樣本不送）。

    錯誤訊息只印長度、不印 token 本身（避免機敏外洩到 log）。
    """
    low = (text or "").lower()
    for tok in _sensitive_tokens():
        if tok.lower() in low:
            raise ValueError(f"PII residue after scrub: token len={len(tok)}")
    if _EMAIL_RE.search(text or ""):
        raise ValueError("PII residue after scrub: email shape")
    if _PRIVATE_IP_RE.search(text or ""):
        raise ValueError("PII residue after scrub: private IP shape")


def bridge_questions(
    conn: sqlite3.Connection,
    *,
    source: str,
    event_types: list[str] | None = None,
) -> dict:
    """把題庫 questions 橋接成 training_samples 的 needs_review 列（Tier B 種子）。

    每個 active question → 一筆 output='' 的 needs_review 列，question_id 設來源題 id（冪等鍵）。
    status='needs_review' 不在 background.py 任何 drain 查詢內 → 本地裁判不搶評未親評題列；
    之後 export_gold_candidates(status='needs_review') 撈給 Claude 本 session 親評。
    source 為必填 keyword（migrate-vs-reuse 決策點，不給預設、強制呼叫端明示）。
    已橋接過的 question_id 跳過（skipped），可重複呼叫（冪等）。
    """
    types = event_types or EVENT_TYPES
    placeholders = ",".join("?" * len(types))
    rows = conn.execute(
        f"""SELECT q.id AS qid, q.prompt, qs.event_type
            FROM questions q
            JOIN question_sets qs ON qs.id = q.set_id
            WHERE q.is_active = 1 AND qs.event_type IN ({placeholders})
            ORDER BY q.id""",
        types,
    ).fetchall()
    already = {
        r[0] for r in conn.execute(
            "SELECT question_id FROM training_samples WHERE question_id IS NOT NULL"
        ).fetchall()
    }
    bridged = skipped = 0
    with conn:  # 退出時 commit（與本檔其餘寫入一致）
        for r in rows:
            if r["qid"] in already:
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO training_samples "
                "(source, question_id, event_type, instruction, input, output, status) "
                "VALUES (?, ?, ?, ?, '', '', 'needs_review')",
                (source, r["qid"], r["event_type"], r["prompt"]),
            )
            bridged += 1
    return {"bridged": bridged, "skipped": skipped}


def export_gold_candidates(
    conn: sqlite3.Connection,
    *,
    tier: str,
    batch_size: int,
    event_types: list[str] | None = None,
    status: str = "pending",
) -> dict:
    """選平衡批次 → scrub → 回傳 batch dict（candidates 已消毒）。

    status：撈哪個狀態的列（預設 'pending'＝Tier A/本地評分池；Tier B 傳 'needs_review'＝
    題庫橋接的待 Claude 親評列，與本地 drain 池隔離，避免兩條路徑搶同一池）。
    dirty（scrub 後仍殘留機敏）樣本 fail-closed 跳過，計入 skipped。
    instruction 優先取 refined_instruction（自包含改寫版）。
    """
    types = event_types or EVENT_TYPES
    per_type = max(1, batch_size // len(types))
    candidates: list[dict] = []
    skipped = 0
    for et in types:
        rows = conn.execute(
            """SELECT id, event_type,
                      COALESCE(refined_instruction, instruction) AS instruction,
                      input, output
               FROM training_samples
               WHERE status=? AND event_type=?
               ORDER BY id LIMIT ?""",
            (status, et, per_type),
        ).fetchall()
        for r in rows:
            instr = scrub_for_export(r["instruction"])
            inp = scrub_for_export(r["input"] or "")
            outp = scrub_for_export(r["output"])
            try:
                for field in (instr, inp, outp):
                    assert_clean(field)
            except ValueError:
                skipped += 1
                continue  # fail-closed：殘留機敏 → 不送 Claude
            candidates.append({
                "sample_id": r["id"], "event_type": r["event_type"],
                "instruction": instr, "input": inp, "output": outp,
            })
    return {
        "batch_id": uuid.uuid4().hex[:12],
        "tier": tier,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "candidates": candidates,
        "skipped": skipped,
    }


def ingest_grades(conn: sqlite3.Connection, graded: dict) -> dict:
    """把 Claude 評分回寫 training_samples（整批單一事務）。

    每筆呼叫 _update_sample_score(conn, sid, score, reason, status)（非 commit）；
    tier=='B' 且帶 expected_output → 同步寫 expected_answer。
    """
    tier = graded.get("tier", "A")
    grades = graded.get("grades", [])
    applied = 0
    with conn:  # 退出時 commit；與 _update_sample_score 的非 commit 約定一致
        for g in grades:
            _update_sample_score(
                conn, g["sample_id"], g["score"], g.get("reason", ""), g["status"],
            )
            if tier == "B" and g.get("expected_output"):
                conn.execute(
                    "UPDATE training_samples SET expected_answer=? WHERE id=?",
                    (g["expected_output"], g["sample_id"]),
                )
            applied += 1
    return {"applied": applied, "tier": tier}


def drain_pending(conn_factory, *, max_rounds: int = 10) -> dict:
    """包 background.score_pending_samples（LIMIT 20/輪），drain 至 pending 清空。

    conn_factory：呼叫後回傳新 connection（與 score_pending_samples 同約定，內部自 close）。
    回傳 {rounds, scored, failed}。function 內 import → 便於測試 monkeypatch。
    """
    from ..core.background import score_pending_samples
    rounds = scored = failed = 0
    for _ in range(max_rounds):
        res = score_pending_samples(conn_factory)
        rounds += 1
        scored += res["scored"]
        failed += res["failed"]
        if res["scored"] + res["failed"] == 0:
            break  # 無 pending 可評 → drain 完成
    return {"rounds": rounds, "scored": scored, "failed": failed}


def harness_progress(conn: sqlite3.Connection) -> dict:
    """per event_type 進度：training_samples 各 status 計數 + gold 已凍結數（續跑判斷）。"""
    ts: dict[str, dict[str, int]] = {}
    for et, status, n in conn.execute(
        "SELECT event_type, status, COUNT(*) FROM training_samples GROUP BY event_type, status"
    ).fetchall():
        ts.setdefault(et, {})[status] = n
    gold: dict[str, int] = {}
    try:
        for et, n in conn.execute(
            "SELECT event_type, COUNT(*) FROM gatekeeper_golden_samples "
            "WHERE is_active=1 GROUP BY event_type"
        ).fetchall():
            gold[et] = n
    except sqlite3.OperationalError:
        pass  # gold 表尚未建立（freeze 從未跑過）→ 視為 0
    return {"training_samples": ts, "gold": gold}
