"""
驗證 Gate — 蒸餾品質小批驗證（base-assumption-first，必過才 backfill）。

目的：在動 schema / backfill 36k 前，先用本地 gemma 對 ablation 的 30 筆樣本做蒸餾，
人工抽查三件事：intent 對不對、command_template 變數抽得對不對、is_command_request 分類對不對。

關鍵附帶診斷（2026-05-29 實查發現）：部分 exchange 邊界錯亂（ended_at < started_at、
message_count 過大），user 請求與實際工具指令不相符（over-merge）。本 gate 一併印出
結構旗標（msg_count / n_tools / ended<started），讓 Shiba 判斷「蒸餾差」是 gemma 弱
還是 exchange 單位本身就髒。

純讀 DB（mode=ro）+ 純呼叫本地 Ollama，不寫任何表、不碰 production code。$0、無速率限制。
輸出：distill_validation_{model}.csv + stdout 比對表。
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from shiba_config import CONFIG  # noqa: E402
from sample import parse_command, redact  # noqa: E402 — 複用同一套指令解析 + 遮罩

HERE = Path(__file__).parent
SAMPLES_CSV = HERE / "samples.csv"

# ── 人工 ground-truth typing（取自 RESULT.md 標註者效度警告段）──────────────
#   只有這 6 筆是真正「要求執行某指令」；其餘 24 筆非指令請求。
GROUND_TRUTH: dict[int, str] = {
    1: "command", 5: "command", 8: "command", 9: "command", 14: "command", 18: "command",
    4: "conceptual", 7: "conceptual", 11: "conceptual", 16: "conceptual", 19: "conceptual",
    21: "conceptual", 25: "conceptual", 26: "conceptual", 30: "conceptual",
    2: "planning", 6: "planning", 17: "planning", 24: "planning",
    12: "noise", 13: "noise", 15: "noise", 22: "noise", 23: "noise", 27: "noise",
    3: "status", 20: "status",
    10: "meta", 28: "meta", 29: "meta",
}

# ── gemma 蒸餾 prompt（核心方法論）──────────────────────────────────────────
SYSTEM = (
    "你是 Claude Code 對話蒸餾器。輸入是一段對話 exchange：使用者的請求，"
    "以及助理在這段內實際執行的工具指令。請抽取結構化資訊，只輸出 JSON：\n"
    "- intent：用一句話正規化描述「使用者真正想達成什麼」，供語意檢索用（繁體中文，不要照抄原句）。\n"
    "- command_template：若這是『要求執行 git/bash 指令』的請求，把實際指令的變數"
    "（檔名、分支、commit 訊息）抽象成模板，例如 git add <files> && git commit -m <msg>；"
    "若非指令請求，填空字串。\n"
    "- is_command_request：使用者請求是否為『要求執行某個具體 git/bash 指令』→ 1；"
    "若為概念問答 / 規劃討論 / 狀態查詢 / 系統雜訊 → 0。\n"
    "- request_type：command / conceptual / planning / noise 四選一。\n"
    "- outcome：若工具有任一失敗則 error，否則 success。\n"
    "判斷以『使用者請求』為意圖主體；若請求與實際指令明顯無關（對話邊界錯亂），"
    "intent 仍以使用者請求為準。"
)

FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "command_template": {"type": "string"},
        "is_command_request": {"type": "integer", "enum": [0, 1]},
        "request_type": {"type": "string", "enum": ["command", "conceptual", "planning", "noise"]},
        "outcome": {"type": "string", "enum": ["success", "error"]},
    },
    "required": ["intent", "command_template", "is_command_request", "request_type", "outcome"],
}

# gemma3 無 thinking；qwen3 有 → 依模型決定是否送 think
THINK_MODELS = ("qwen3",)
TIMEOUT = 180.0
MAX_USER_CHARS = 800
MAX_CMD_CHARS = 220
MAX_TOOLS = 20


def reconstruct(conn: sqlite3.Connection, exchange_id: int) -> dict:
    """重建整段 exchange：metadata + user 請求 + 依序所有工具指令（請求→執行單位）。"""
    meta = conn.execute(
        "SELECT message_count, tool_use_count, user_text_preview, started_at, ended_at "
        "FROM exchanges WHERE id = ?",
        (exchange_id,),
    ).fetchone()
    if meta is None:  # exchange 已不存在（rebuild 後 id 漂移）→ 回報缺失，續跑
        return {"msg_count": 0, "tool_use_count": 0, "ended_before_started": False,
                "user_text": "", "tools": [], "any_error": False, "missing": True}
    # user_open 真正請求文字
    user_row = conn.execute(
        """SELECT m.content FROM exchange_messages em JOIN messages m ON m.id = em.message_id
           WHERE em.exchange_id = ? AND em.role_in_exchange = 'user_open' ORDER BY em.seq LIMIT 1""",
        (exchange_id,),
    ).fetchone()
    user_text = (user_row["content"] if user_row and user_row["content"] else meta["user_text_preview"]) or ""
    # 依序所有工具
    tool_rows = conn.execute(
        """SELECT te.tool_name, te.is_error, te.input_cmd
           FROM exchange_messages em JOIN tool_executions te ON te.message_id = em.message_id
           WHERE em.exchange_id = ? ORDER BY em.seq, te.id""",
        (exchange_id,),
    ).fetchall()
    tools = []
    any_error = False
    for t in tool_rows:
        any_error = any_error or bool(t["is_error"])
        if t["tool_name"] == "Bash":
            arg = parse_command(t["input_cmd"]) or ""
        else:
            try:
                obj = json.loads(t["input_cmd"]) if t["input_cmd"] else {}
                arg = obj.get("file_path") or obj.get("url") or obj.get("pattern") or ""
            except (json.JSONDecodeError, TypeError):
                arg = ""
        tools.append({"name": t["tool_name"], "is_error": bool(t["is_error"]), "arg": str(arg)})
    return {
        "msg_count": meta["message_count"],
        "tool_use_count": meta["tool_use_count"],
        "ended_before_started": bool(meta["ended_at"] and meta["started_at"]
                                     and meta["ended_at"] < meta["started_at"]),
        "user_text": user_text,
        "tools": tools,
        "any_error": any_error,
    }


def build_distill_input(rec: dict) -> str:
    """組蒸餾輸入：請求 + 依序工具指令（Shiba 框架的 請求→執行 單位）。"""
    lines = [f"[使用者請求]\n{redact(rec['user_text'].strip())[:MAX_USER_CHARS]}", "", "[助理依序執行的工具指令]"]
    if not rec["tools"]:
        lines.append("（無工具呼叫）")
    for i, t in enumerate(rec["tools"][:MAX_TOOLS], 1):
        flag = ",error" if t["is_error"] else ""
        arg = redact(t["arg"])[:MAX_CMD_CHARS] if t["arg"] else ""
        lines.append(f"{i}. [{t['name']}{flag}] {arg}")
    extra = len(rec["tools"]) - MAX_TOOLS
    if extra > 0:
        lines.append(f"…（另有 {extra} 次工具呼叫省略）")
    return "\n".join(lines)


def distill(model: str, distill_input: str) -> tuple[dict, int]:
    """呼叫本地 Ollama 蒸餾，回傳 (parsed_json, latency_ms)。"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": distill_input},
        ],
        "stream": False,
        "format": FORMAT_SCHEMA,
        "options": {"temperature": 0.0, "num_ctx": 8192, "num_predict": 512},
        "keep_alive": "10m",
    }
    if any(model.startswith(p) for p in THINK_MODELS):
        body["think"] = False
    t0 = time.monotonic()
    resp = httpx.post(f"{CONFIG.services.ollama_base_url}/api/chat", json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    latency = int((time.monotonic() - t0) * 1000)
    content = resp.json()["message"]["content"].strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"intent": f"<PARSE_FAIL: {content[:120]}>", "command_template": "",
                  "is_command_request": -1, "request_type": "?", "outcome": "?"}
    return parsed, latency


def main() -> None:
    p = argparse.ArgumentParser(description="蒸餾品質驗證 gate")
    p.add_argument("--model", default="gemma3:4b", help="蒸餾用本地模型")
    p.add_argument("--ids", default="", help="只跑指定 sample_id（逗號分隔）；空=全 30 筆")
    args = p.parse_args()

    with SAMPLES_CSV.open(encoding="utf-8") as f:
        samples = list(csv.DictReader(f))
    if args.ids:
        want = {int(x) for x in args.ids.split(",")}
        samples = [s for s in samples if int(s["sample_id"]) in want]

    db_path = CONFIG.paths.db
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows_out = []
    print(f"模型 {args.model} | 樣本 {len(samples)} 筆\n")
    print(f"{'#':>3} {'gt_type':<10} {'結構':<14} {'gemma_cmd?':<10} {'gemma_type':<10} intent / template")
    print("─" * 110)
    try:
        for s in samples:
            sid = int(s["sample_id"])
            rec = reconstruct(conn, int(s["exchange_id"]))
            if rec.get("missing"):
                print(f"{sid:>3} {GROUND_TRUTH.get(sid, '?'):<10} {'<缺失>':<14} exchange {s['exchange_id']} 不存在（id 漂移），跳過")
                continue
            try:
                d, latency = distill(args.model, build_distill_input(rec))
            except Exception as e:  # noqa: BLE001 — 單筆失敗記錄續跑
                d, latency = {"intent": f"<ERR: {e}>", "command_template": "",
                              "is_command_request": -1, "request_type": "?", "outcome": "?"}, 0
            gt = GROUND_TRUTH.get(sid, "?")
            gt_is_cmd = 1 if gt == "command" else 0
            struct = f"m{rec['msg_count']}/t{rec['tool_use_count']}"
            if rec["ended_before_started"]:
                struct += " ⚠端序亂"
            cmd_match = "✓" if d["is_command_request"] == gt_is_cmd else "✗"
            print(f"{sid:>3} {gt:<10} {struct:<14} "
                  f"{str(d['is_command_request'])+cmd_match:<10} {d['request_type']:<10} "
                  f"{d['intent'][:50]} / {d['command_template'][:30]}")
            rows_out.append({
                "sample_id": sid, "exchange_id": s["exchange_id"],
                "gt_type": gt, "gt_is_command": gt_is_cmd,
                "msg_count": rec["msg_count"], "tool_use_count": rec["tool_use_count"],
                "ended_before_started": int(rec["ended_before_started"]),
                "gemma_intent": d["intent"], "gemma_command_template": d["command_template"],
                "gemma_is_command_request": d["is_command_request"],
                "gemma_request_type": d["request_type"], "gemma_outcome": d["outcome"],
                "is_command_match": int(d["is_command_request"] == gt_is_cmd),
                "latency_ms": latency,
                "user_text": redact(rec["user_text"].strip())[:300],
            })
    finally:
        conn.close()

    # ── 摘要：is_command_request 對 ground-truth 命中率 + 結構髒樣本標記 ──
    valid = [r for r in rows_out if r["gemma_is_command_request"] in (0, 1)]
    hit = sum(r["is_command_match"] for r in valid)
    dirty = [r["sample_id"] for r in rows_out if r["ended_before_started"]]
    cmd_samples = [r for r in rows_out if r["gt_type"] == "command"]
    cmd_hit = sum(r["is_command_match"] for r in cmd_samples)
    print("─" * 110)
    print(f"is_command_request 命中 {hit}/{len(valid)}（含真指令子集 {cmd_hit}/{len(cmd_samples)}）")
    if dirty:
        print(f"⚠ 結構錯亂（ended<started）樣本：{dirty} — 這些 exchange 單位本身髒，蒸餾結果不可信")

    out_csv = HERE / f"distill_validation_{args.model.replace(':', '_').replace('.', '_')}.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"✓ 寫入 {out_csv}（{len(rows_out)} 筆）")


if __name__ == "__main__":
    main()
