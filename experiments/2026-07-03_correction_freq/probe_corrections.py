#!/usr/bin/env python3
"""糾正頻率 probe（Task 1，唯讀）

母體＝「糾正/偏好型」user 訊息（對 Claude 行為的指正或持久偏好），
非任務指令（keystone/EV gate 量過的母體）。

輸出：
  candidates.tsv — 每行一候選（msg_id, session_id, 命中 pattern, 正規化片段）
  stats.txt      — 漏斗數字（總量→去噪→候選）+ 各 pattern 命中數
語意 fold 與 artifact audit 由人（Claude 主執行緒）逐筆做，不在腳本內。

卡控：sqlite URI mode=ro 唯讀；零模型依賴；數字可重現（無隨機性）。
"""
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "shiba-brain.db"
OUT_DIR = Path(__file__).resolve().parent

# ---- 去噪過濾（keystone 教訓：harness 噪音是 apparent-PASS 主源）----
NOISE_PREFIXES = ("<", "/", "!")
NOISE_SUBSTRINGS = (
    "Caveat:",                      # local-command 附言
    "[Request interrupted",         # 中斷訊息
    "Base directory for this skill",  # skill 載入全文
    "ARGUMENTS:",                   # skill 參數 echo
)
# 自動化/子代理 prompt 簽章（非 Shiba 自然語言）
AUTOMATION_SIGNATURES = (
    "You are summarizing",
    "Apply maximum non-destructive compression",
    "Implement the following plan",
    "You are a", "You are an",
    "Launching skill",
)
MIN_CHARS = 16  # 與 ingestion 最短長度閘一致

# ---- 糾正/偏好 pattern（高 recall，precision 靠人工 audit）----
PATTERNS = {
    # 否定/禁止（行為指正）
    "不要": r"不要",
    "不用": r"不用",
    "別": r"(?:^|[，。、\s])別(?!人|的|墅)",
    "不得": r"不得",
    "不准/禁止": r"不准|禁止",
    "不需要/不必": r"不需要|不必",
    # 糾錯
    "不對/錯了": r"不對|錯了|不是這樣|搞錯",
    "改用/改成/改回": r"改用|改成|改回",
    # 重複抱怨（最強訊號：說明已糾正過）
    "我說過/又": r"我說過|說過幾次|又忘|你又|又來|再次提醒",
    # 持久化措辭
    "一律/必須": r"一律|必須",
    "記住/以後/下次": r"記住|以後|下次|之後都|從現在起",
    "規範/慣例/原則": r"規範|慣例|原則",
    # 英文
    "en-dont/never/always": r"\b(?:don'?t|do not|never|always|stop doing|instead of|I told you)\b",
}
COMPILED = {name: re.compile(p, re.IGNORECASE) for name, p in PATTERNS.items()}


def is_noise(text: str) -> bool:
    """判斷是否 harness/自動化噪音（非 Shiba 自然語言）"""
    stripped = text.lstrip()
    if len(stripped) < MIN_CHARS:
        return True
    if stripped.startswith(NOISE_PREFIXES):
        return True
    if any(s in text for s in NOISE_SUBSTRINGS):
        return True
    head = stripped[:200]
    if any(sig in head for sig in AUTOMATION_SIGNATURES):
        return True
    return False


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, session_id, content FROM messages "
        "WHERE role='user' AND content IS NOT NULL ORDER BY id"
    ).fetchall()
    conn.close()

    total = len(rows)
    clean, candidates = 0, []
    pattern_hits = Counter()
    seen_norm = {}  # 正規化全文 → 首見 (msg_id)，跨 session 重複文字仍保留（頻率就是訊號）

    for msg_id, session_id, content in rows:
        if is_noise(content):
            continue
        clean += 1
        hits = [name for name, cre in COMPILED.items() if cre.search(content)]
        if not hits:
            continue
        for h in hits:
            pattern_hits[h] += 1
        # 片段：壓平換行、截 150 字供人工 audit
        snippet = re.sub(r"\s+", " ", content.strip())[:150]
        norm = snippet.lower()
        dup_of = seen_norm.setdefault(norm, msg_id)
        candidates.append((msg_id, session_id, "|".join(hits),
                           "dup" if dup_of != msg_id else "", snippet))

    out = OUT_DIR / "candidates.tsv"
    with out.open("w", encoding="utf-8") as f:
        f.write("msg_id\tsession_id\tpatterns\tdup\tsnippet\n")
        for row in candidates:
            f.write("\t".join(str(c) for c in row) + "\n")

    distinct_sessions = len({c[1] for c in candidates})
    stats = OUT_DIR / "stats.txt"
    with stats.open("w", encoding="utf-8") as f:
        f.write(f"user 訊息（有文字）: {total}\n")
        f.write(f"去噪後: {clean}\n")
        f.write(f"糾正/偏好候選: {len(candidates)}（跨 {distinct_sessions} distinct sessions）\n")
        f.write("\n各 pattern 命中（一訊息可多中）:\n")
        for name, n in pattern_hits.most_common():
            f.write(f"  {name}: {n}\n")
    print(stats.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
