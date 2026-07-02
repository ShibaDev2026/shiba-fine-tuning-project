#!/usr/bin/env python3
"""個人評測集 v1 — A/B 兩臂生成（Task 3）

A 臂＝qwen3:30b-a3b + 全域/專案 CLAUDE.md（system）
B 臂＝A + retrieve_for_eval(question) production 召回（含 answer 欄）

真實依賴：Ollama（qwen3:30b-a3b 生成、bge-m3 供召回 embedding）——
執行前由呼叫者確認服務已啟動；本腳本開頭再做一次 health check，失敗即中止。
checkpoint：results.jsonl 逐筆 append，重跑自動跳過已完成 (qid, arm)。
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from layer_1_memory.lib.rag import retrieve_for_eval  # noqa: E402

OLLAMA = "http://localhost:11434"
MODEL = "qwen3:30b-a3b"
RESULTS = HERE / "results.jsonl"


def _post(url: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def health_check() -> None:
    """真實依賴卡控：Ollama 不通就中止，不得改用 mock"""
    with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as resp:
        names = [m["name"] for m in json.loads(resp.read())["models"]]
    assert MODEL in names, f"{MODEL} 不在 Ollama 模型清單"


def build_system() -> str:
    """A/B 共用 system＝真實 CLAUDE.md 資產（全域+專案全文）"""
    global_md = (Path.home() / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    project_md = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    return (
        "你是 shiba-fine-tuning-project 專案的開發助手，回答務必具體、可直接執行、繁體中文。"
        "直接給最終答案，不要展示思考過程、不要逐條複誦規範。\n\n"
        f"=== 全域開發規範 ===\n{global_md}\n\n=== 專案規範 ===\n{project_md}"
    )


def generate(system: str, user: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,  # qwen3 關 thinking（Ollama 原生參數）
        # num_predict 1200：qwen3 thinking 常混入 content，須留足額度讓最終答案出現
        "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 1200},
    }
    t0 = time.time()
    resp = _post(f"{OLLAMA}/api/chat", payload)
    return {"response": resp["message"]["content"].strip(), "seconds": round(time.time() - t0, 1)}


def main() -> None:
    health_check()
    eval_set = json.loads((HERE / "eval_set.json").read_text(encoding="utf-8"))
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["qid"], r["arm"]))

    system = build_system()
    with RESULTS.open("a", encoding="utf-8") as out:
        for q in eval_set["questions"]:
            for arm in ("A", "B"):
                if (q["id"], arm) in done:
                    continue
                if arm == "A":
                    user = f"問題：{q['question']}"
                    contexts = None
                else:
                    hits = retrieve_for_eval(q["question"], top_n=3)
                    contexts = hits.get("retrieved_contexts") or []
                    assert isinstance(contexts, list), "retrieve_for_eval 回傳結構變更"
                    ref = "\n---\n".join(contexts) if contexts else "（無召回結果）"
                    user = f"過往工作記錄（RAG 召回，供參考）：\n{ref}\n\n問題：{q['question']}"
                g = generate(system, user)
                row = {"qid": q["id"], "arm": arm, **g, "contexts": contexts}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(f"{q['id']}/{arm} done ({g['seconds']}s)", flush=True)
    print("ALL DONE")


if __name__ == "__main__":
    main()
