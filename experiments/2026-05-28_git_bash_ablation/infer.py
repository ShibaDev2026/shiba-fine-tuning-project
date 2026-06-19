"""
Step 2+3 — RAG 召回 + 三層 Ablation 推論（recall 折入此檔，不過度切檔）。

三層 config（think:false / temp 0.7 / num_ctx 8192 為常數，三層一致）：
  A 基線（production 複刻）：複刻 router._call_qwen（yaml 通用助理 system + 相關記憶 + user，free-form 文字）
  B +角色/格式 reframe：換 system 為「指令生成器」+ JSON 輸出 {"commands":[...]}
  C +grounding：B + 注入當下 git status/branch/diff

零成本驗證：A→B→C 的 Δ 採納率 = 各方法論貢獻。不走 OllamaClient（不支援 think/format），
用 httpx 直打 /api/chat。純讀 DB（RAG）+ 呼叫本地 Ollama，不碰 production code。

輸出：outputs_A.csv / outputs_B.csv / outputs_C.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from shiba_config import CONFIG  # noqa: E402
from layer_1_memory.lib.rag import retrieve_for_eval  # noqa: E402

HERE = Path(__file__).parent
SAMPLES_CSV = HERE / "samples.csv"

MODEL = "qwen3:30b-a3b"
# 對齊 config/models/responder-qwen3-30b-a3b.yaml（三層常數）
OPTIONS = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.05,
    "num_ctx": 8192,
    "num_predict": 1024,
}
THINK = False
KEEP_ALIVE = "10m"
TIMEOUT = 120.0

# ── Config A：production 複刻（router._call_qwen / responder yaml）──────────
SYSTEM_A = "你是 Shiba 的本地助理。請以繁體中文簡潔回答，直接給結論再補理由。"

# ── Config B/C：指令生成器 role-framing ────────────────────────────────────
SYSTEM_B = (
    "你是 git/bash 指令生成器。根據使用者請求與『相關記憶』，輸出可直接在終端機執行的指令。\n"
    "規則：\n"
    "1. 只輸出指令本身，不要解釋、不要中文敘述、不要 markdown code fence。\n"
    "2. 不要自行編造 commit message 內文；若請求需要 commit，commit message 用佔位字串 <COMMIT_MSG>。\n"
    "3. 多步驟用 && 串接或分多筆。\n"
    "4. 變數（branch / 檔案路徑）若『環境資訊』有提供則填實際值，否則用 <PLACEHOLDER>。"
)

# Ollama structured output JSON schema
FORMAT_SCHEMA = {
    "type": "object",
    "properties": {"commands": {"type": "array", "items": {"type": "string"}}},
    "required": ["commands"],
}


def ollama_chat(messages: list[dict], use_format: bool) -> tuple[str, int]:
    """直打 Ollama /api/chat，回傳 (response_text, latency_ms)。"""
    body = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": OPTIONS,
        "think": THINK,
        "keep_alive": KEEP_ALIVE,
    }
    if use_format:
        body["format"] = FORMAT_SCHEMA
    t0 = time.monotonic()
    resp = httpx.post(
        f"{CONFIG.services.ollama_base_url}/api/chat",
        json=body,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    latency = int((time.monotonic() - t0) * 1000)
    return data["message"]["content"].strip(), latency


def get_rag_context(instruction: str) -> tuple[str, str]:
    """召回 top-3 → (context_str, source)。失敗回空字串。"""
    try:
        res = retrieve_for_eval(instruction, top_n=3)
        ctxs = res.get("retrieved_contexts", [])
        return "\n---\n".join(ctxs), res.get("source", "")
    except Exception as e:  # noqa: BLE001 — 召回失敗不應中斷實驗，記空 context
        print(f"  ⚠ RAG 召回失敗：{e}")
        return "", "error"


def get_grounding() -> str:
    """Config C：抓當下 git 環境（在專案 repo 執行）。"""
    parts = []
    for label, cmd in [
        ("branch", ["git", "branch", "--show-current"]),
        ("status", ["git", "status", "-sb"]),
        ("diff_stat", ["git", "diff", "--stat"]),
    ]:
        try:
            out = subprocess.run(
                cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
            ).stdout.strip()
            parts.append(f"[{label}]\n{out}")
        except Exception:  # noqa: BLE001 — grounding 抓不到就略過該項
            pass
    return "\n".join(parts)


def build_messages(config: str, instruction: str, context: str, grounding: str) -> list[dict]:
    """依 config 組 messages。"""
    msgs: list[dict] = []
    if config == "A":
        msgs.append({"role": "system", "content": SYSTEM_A})
        if context:
            msgs.append({"role": "system", "content": f"相關記憶：{context}"})
    else:  # B / C
        msgs.append({"role": "system", "content": SYSTEM_B})
        if context:
            msgs.append({"role": "system", "content": f"相關記憶：\n{context}"})
        if config == "C" and grounding:
            msgs.append({"role": "system", "content": f"環境資訊（當下 git 狀態）：\n{grounding}"})
    msgs.append({"role": "user", "content": instruction})
    return msgs


def extract_commands(config: str, raw: str) -> str:
    """A=free-form 原樣；B/C=解析 JSON {"commands":[...]} → 換行接；失敗回原文。"""
    if config == "A":
        return raw
    try:
        obj = json.loads(raw)
        cmds = obj.get("commands", []) if isinstance(obj, dict) else []
        if cmds:
            return "\n".join(str(c) for c in cmds)
    except (json.JSONDecodeError, TypeError):
        pass
    return raw  # JSON 解析失敗 → 留原文，標記 format_error 由人工標


def run_config(
    config: str,
    samples: list[dict],
    grounding: str,
    ctx_cache: dict[str, tuple[str, str]],
    dry_run: bool,
    suffix: str = "",
) -> None:
    out_csv = HERE / f"outputs_{config}{suffix}.csv"
    rows_out = []
    for i, s in enumerate(samples, 1):
        instruction = s["instruction"]
        context, src = ctx_cache[s["sample_id"]]  # 三層共用同一份召回，去除冷啟動 confound
        msgs = build_messages(config, instruction, context, grounding)
        if dry_run:
            print(f"\n===== Config {config} #{s['sample_id']} =====")
            for m in msgs:
                print(f"[{m['role']}] {m['content'][:200]}")
            continue
        try:
            raw, latency = ollama_chat(msgs, use_format=(config != "A"))
            extracted = extract_commands(config, raw)
            json_ok = 1 if (config == "A" or extracted != raw) else 0
            print(f"  [{config} {i}/{len(samples)}] #{s['sample_id']} {latency}ms json_ok={json_ok}")
        except Exception as e:  # noqa: BLE001 — 單筆失敗記錄後續跑，不中斷
            raw, extracted, latency, json_ok = f"<ERROR: {e}>", "", 0, 0
            print(f"  [{config} {i}/{len(samples)}] #{s['sample_id']} ERROR: {e}")
        rows_out.append({
            "sample_id": s["sample_id"],
            "instruction": instruction,
            "gold_commands": s["gold_commands"],
            "rag_source": src,
            "rag_context": context[:500],
            "raw_response": raw,
            "extracted_commands": extracted,
            "json_ok": json_ok,
            "latency_ms": latency,
        })
    if dry_run:
        return
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"✓ 寫入 {out_csv}（{len(rows_out)} 筆）")


def main() -> None:
    p = argparse.ArgumentParser(description="三層 ablation 推論")
    p.add_argument("--configs", default="A,B,C", help="逗號分隔，預設 A,B,C")
    p.add_argument("--limit", type=int, default=0, help="只跑前 N 筆（0=全部）")
    p.add_argument("--dry-run", action="store_true", help="只印 prompt 不呼叫 Ollama")
    p.add_argument("--samples", default=str(SAMPLES_CSV),
                   help="樣本 CSV 路徑（預設 samples.csv；乾淨重跑用 clean_samples.csv）")
    p.add_argument("--suffix", default="", help="輸出檔名後綴（如 _clean，避免覆蓋原 outputs）")
    args = p.parse_args()

    with open(args.samples, encoding="utf-8") as f:
        samples = list(csv.DictReader(f))
    if args.limit:
        samples = samples[: args.limit]

    grounding = get_grounding()
    print(f"樣本 {len(samples)} 筆 | grounding {len(grounding)} 字 | configs {args.configs}")

    # 先 warm-up embedder + 每樣本召回一次（三層共用，去冷啟動 confound）
    print("── 預召回 RAG context（三層共用）──")
    ctx_cache: dict[str, tuple[str, str]] = {}
    for s in samples:
        ctx_cache[s["sample_id"]] = get_rag_context(s["instruction"])
    srcs = [v[1] for v in ctx_cache.values()]
    print(f"  召回完成：vector={srcs.count('vector')} fts5={srcs.count('fts5')} 空/err={srcs.count('') + srcs.count('error')}")

    for config in args.configs.split(","):
        config = config.strip()
        if config not in ("A", "B", "C"):
            continue
        print(f"\n──── Config {config} ────")
        run_config(config, samples, grounding, ctx_cache, args.dry_run, args.suffix)


if __name__ == "__main__":
    main()
