"""
setup_teachers.py — 初始化 Teacher 設定

用途：
1. 將 API Key 存入 macOS Keychain
2. 在 DB 建立 Teacher 記錄
3. 驗證 API 連線（送一筆測試評分）

執行：
    python layer_2_chamber/scripts/setup_teachers.py --setup
    python layer_2_chamber/scripts/setup_teachers.py --verify
    python layer_2_chamber/scripts/setup_teachers.py --list
"""

import argparse
import getpass
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.core.config import init_layer2_db
from layer_2_chamber.backend.services.teacher_service import (
    get_active_teachers,
    get_api_key,
    upsert_teacher,
)

# ── Teacher 定義（對應 CLAUDE.md 免費師父清單）────────────────────────
TEACHERS = [
    {
        "name": "Gemini 2.5 Flash",
        "model_id": "gemini-2.5-flash",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "keychain_ref": "gemini-api-key",
        "priority": 0,
        "daily_limit": 250,
    },
    {
        "name": "Gemini 2.5 Flash-Lite",
        "model_id": "gemini-2.5-flash-lite",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "keychain_ref": "gemini-api-key",  # 共用同一組 key
        "priority": 1,
        "daily_limit": 1000,
    },
]

_TEST_SAMPLE = {
    "instruction": "使用 git commit 提交修改",
    "input": "",
    "output": "執行 git add . && git commit -m 'fix: 修正 FTS5 trigram migration'",
}


def cmd_setup():
    """互動式輸入 API Key → 存 Keychain → seed DB"""
    print("=== Layer 2 Teacher 設定 ===\n")

    # 收集需要 key 的唯一 keychain_ref
    refs = {t["keychain_ref"] for t in TEACHERS}
    for ref in refs:
        existing = get_api_key(ref)
        if existing:
            print(f"✓ Keychain '{ref}' 已存在，跳過")
            continue

        key = getpass.getpass(f"請輸入 '{ref}' 的 API Key: ").strip()
        if not key:
            print(f"✗ 跳過 '{ref}'（未輸入）")
            continue

        _save_keychain(ref, key)
        print(f"✓ '{ref}' 已存入 Keychain")

    # Seed DB
    conn = init_layer2_db()
    for t in TEACHERS:
        tid = upsert_teacher(
            conn,
            name=t["name"],
            model_id=t["model_id"],
            api_base=t["api_base"],
            keychain_ref=t["keychain_ref"],
            priority=t["priority"],
            daily_limit=t["daily_limit"],
        )
        print(f"✓ Teacher '{t['name']}' id={tid}")
    conn.close()
    print("\n設定完成，執行 --verify 驗證連線。")


def cmd_verify():
    """對每個 Teacher 送一筆測試評分，驗證 API 連線"""
    conn = init_layer2_db()
    teachers = get_active_teachers(conn)
    conn.close()

    if not teachers:
        print("✗ 無可用 Teacher，請先執行 --setup")
        return

    print("=== 驗證 Teacher 連線 ===\n")
    for t in teachers:
        api_key = get_api_key(t["keychain_ref"])
        if not api_key:
            print(f"✗ {t['name']}：Keychain 取不到 key")
            continue

        result = _test_call(t, api_key)
        if result:
            print(f"✓ {t['name']}：score={result['score']}，reason={result['reason']}")
        else:
            print(f"✗ {t['name']}：API 呼叫失敗")


def cmd_list():
    """列出目前 DB 的 Teacher 狀態"""
    conn = init_layer2_db()
    teachers = get_active_teachers(conn)
    conn.close()

    if not teachers:
        print("（無 Teacher，請執行 --setup）")
        return

    print(f"{'ID':<4} {'名稱':<25} {'模型':<25} {'優先':<6} {'限額/日':<8} {'啟用'}")
    print("-" * 75)
    for t in teachers:
        print(f"{t['id']:<4} {t['name']:<25} {t['model_id']:<25} {t['priority']:<6} {t['daily_limit']:<8} {'✓' if t['is_active'] else '✗'}")


def _save_keychain(ref: str, key: str) -> None:
    subprocess.run(
        ["security", "add-generic-password", "-s", ref, "-a", ref, "-w", key, "-U"],
        check=True, capture_output=True,
    )


def _test_call(teacher, api_key: str) -> dict | None:
    import urllib.request as urlreq

    prompt = (
        f"你是訓練資料評審。評估以下樣本品質（0-10），只回覆 JSON：\n"
        f"{{\"score\": <數字>, \"reason\": \"<一句話>\"}}\n\n"
        f"Instruction: {_TEST_SAMPLE['instruction']}\n"
        f"Output: {_TEST_SAMPLE['output']}"
    )
    try:
        if "generativelanguage.googleapis.com" in teacher["api_base"]:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{teacher['model_id']}:generateContent?key={api_key}"
            )
            body = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 100, "temperature": 0.1},
            }).encode()
            req = urlreq.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urlreq.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=teacher["api_base"])
            resp = client.chat.completions.create(
                model=teacher["model_id"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100, temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw[raw.index("\n") + 1:] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        data = json.loads(raw)
        return {"score": float(data["score"]), "reason": str(data.get("reason", ""))}
    except Exception as e:
        print(f"  錯誤：{e}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 2 Teacher 設定工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup", action="store_true", help="初始化 Keychain + seed DB")
    group.add_argument("--verify", action="store_true", help="驗證 API 連線")
    group.add_argument("--list", action="store_true", help="列出現有 Teacher")
    args = parser.parse_args()

    if args.setup:
        cmd_setup()
    elif args.verify:
        cmd_verify()
    elif args.list:
        cmd_list()
