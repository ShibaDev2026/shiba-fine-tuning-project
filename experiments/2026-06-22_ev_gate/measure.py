"""EV gate 量測腳本（Phase 1，唯讀離線分析）。

量測 exchange_embeddings 清洗後的指令任務重複頻率與 EV，輸出 gate 判決。
不改 production code、不寫 DB。
"""
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

# 讓 measure.py 可 import 專案 layer_1_memory.lib.rag（從 experiments 子目錄執行）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from layer_1_memory.lib import rag  # noqa: E402

# 參數化規則：順序重要（先吃較長/較具體的樣式）
_PR_RE = re.compile(r"#\s*\d+|PR\s*\d+", re.IGNORECASE)
_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")            # git commit hash
_PATH_RE = re.compile(r"[\w./-]*/[\w./-]+")             # 含 / 的路徑
_FILE_RE = re.compile(r"\b[\w-]+\.[A-Za-z0-9]{1,5}\b")  # 檔名.副檔名


def parametrize_instruction(text: str) -> str:
    """把具體路徑/檔名/PR/hash 替換成變數槽，歸併同型任務。

    ⚠ 僅做 lexical 歸併（path/file/PR/hash），不做語意同義詞折疊：
    措辭不同的同型任務（修改↔改動）不會合流 → 重複頻率偏低估（FAIL 方向）。
    反向風險：regex 貪婪可能誤吃日期/小數/版本號（2026/06/22、8.0、v1.8.0）
    → 不同指令被誤併 → 頻率高估（PASS 方向，較危險）。RESULT.md 的 Top-20
    即為人工驗證閘：PASS 須逐筆確認高頻 pattern 是真任務、非 regex 併接 artifact。
    """
    s = text or ""
    s = _PR_RE.sub("{pr}", s)
    s = _HASH_RE.sub("{hash}", s)
    s = _PATH_RE.sub("{path}", s)
    s = _FILE_RE.sub("{file}", s)
    return s.strip()


def is_junk_instruction(text: str) -> bool:
    """短控制詞或系統 meta query 視為 junk（複用 production 查詢側閘）。"""
    return rag.is_short_query(text) or rag.is_system_meta_query(text)


def compute_pattern_frequencies(rows: list[dict]) -> dict[str, int]:
    """去 junk → 去 D4 verbatim 灌水 → 參數化 → 計頻。

    frequency 單位 = distinct (session_uuid, commands) per parametrized-pattern。
    """
    seen: set[tuple[str, str]] = set()
    counter: Counter[str] = Counter()
    for r in rows:
        instr = r["instruction"]
        if is_junk_instruction(instr):
            continue
        d4_key = (r["session_uuid"], r["commands"])
        if d4_key in seen:
            continue  # 同 session 同 commands = D4 跨 branch verbatim 副本
        seen.add(d4_key)
        counter[parametrize_instruction(instr)] += 1
    return dict(counter)


def evaluate_gate(
    freqs: dict[str, int],
    min_patterns: int = 20,
    min_freq: int = 3,
    min_coverage: float = 0.25,
    adoption_ceiling: float = 0.13,
) -> dict:
    """計 gate 判決：合格 pattern 數 / 覆蓋率 / EV，回傳判決字典。"""
    total_occurrences = sum(freqs.values())
    qualifying = {k: v for k, v in freqs.items() if v >= min_freq}
    qualifying_occurrences = sum(qualifying.values())
    coverage = (qualifying_occurrences / total_occurrences) if total_occurrences else 0.0
    # EV = 合格 pattern 的重複占用量 × 採納天花板（可省的 Claude 呼叫上界）
    ev_calls_saved = qualifying_occurrences * adoption_ceiling
    passed = (len(qualifying) >= min_patterns) and (coverage >= min_coverage)
    # 頻率直方圖
    buckets = {"1": 0, "2-4": 0, "5-9": 0, "10+": 0}
    for v in freqs.values():
        if v == 1:
            buckets["1"] += 1
        elif v <= 4:
            buckets["2-4"] += 1
        elif v <= 9:
            buckets["5-9"] += 1
        else:
            buckets["10+"] += 1
    return {
        "passed": passed,
        "qualifying_patterns": len(qualifying),
        "coverage": round(coverage, 3),
        "ev_calls_saved": round(ev_calls_saved, 1),
        "total_patterns": len(freqs),
        "total_occurrences": total_occurrences,
        "histogram": buckets,
    }


_DEFAULT_DB = str(_PROJECT_ROOT / "data" / "shiba-brain.db")

# 與 production _vector_search 一致：過濾「一句話對應 >=3 種 commands」的高發散控制詞
_LOAD_SQL = """
    SELECT session_uuid, instruction, commands
    FROM exchange_embeddings
    WHERE instruction IN (
        SELECT instruction FROM exchange_embeddings
        GROUP BY instruction HAVING count(DISTINCT commands) < 3
    )
"""


def load_rows(db_path: str = _DEFAULT_DB) -> list[dict]:
    """唯讀讀 exchange_embeddings，套 production 高發散過濾。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(_LOAD_SQL).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _render_result_md(report: dict, top_patterns: list[tuple[str, int]]) -> str:
    verdict = "✅ PASS" if report["passed"] else "❌ FAIL"
    lines = [
        "# EV Gate 量測結果（Phase 1）",
        "",
        f"> 判決：**{verdict}**（門檻：≥20 patterns 頻率≥3 且覆蓋≥25%）",
        "",
        "## 指標",
        f"- 清洗後 distinct task-pattern：{report['total_patterns']}",
        f"- 總 occurrence（去 junk+去 D4）：{report['total_occurrences']}",
        f"- 合格 pattern（頻率≥3）：{report['qualifying_patterns']}",
        f"- 覆蓋率：{report['coverage']}",
        f"- EV（可省 Claude 呼叫上界 @13%）：{report['ev_calls_saved']}",
        "",
        "## 頻率直方圖",
        f"- 1（一次性）：{report['histogram']['1']}",
        f"- 2-4：{report['histogram']['2-4']}",
        f"- 5-9：{report['histogram']['5-9']}",
        f"- 10+：{report['histogram']['10+']}",
        "",
        "## Top 20 重複 pattern",
    ]
    for pat, freq in top_patterns[:20]:
        lines.append(f"- [{freq}×] {pat}")
    return "\n".join(lines) + "\n"


# 人工 sanity-pass 解讀（advisor 要求：FAIL/PASS 都不可只交 boolean）寫入 RESULT 末段
_INTERPRETATION = """
## 解讀（人工全量 sanity-pass：freq-1 尾巴 + 漏斗 + 發散濾殺名單）

**判決：FAIL 穩健（robust）。base-assumption-first 觸 STOP——不建 Pattern Library。**
前提「Shiba 夠常重複同型原子指令任務、足以撐 Library」**不被資料支持**。

### 證據漏斗（raw → 最終）
- raw 2578 rows / 1155 distinct instruction
- 發散濾（一句對 ≥3 commands）殺 1092 rows（僅 76 distinct）→ 餘 1486
- junk 閘殺 644 rows（43%）→ 餘 842
- (session,commands) 去 D4 灌水：842 → 146（5.8× 壓縮）
- 最終：124 distinct patterns / 146 occurrence；頻率天花板 = **2×**；合格(≥3)=**0**

### 三項判讀（皆已實證、非臆測）
1. **無 PASS 方向 regex artifact**（advisor 主風險未觸發）：天花板 2×，無 pattern 因
   {path}/{file} 貪婪併接虛胖過門檻。
2. **freq-1 尾巴（102 筆）真異質**：逐筆掃過為各自不同的一次性設計/除錯/前端提問；
   僅極小數措辭叢集（prompt-injection 疑慮 ~4、續接摘要雜訊 ~2、effort echo ~3），
   且多屬雜訊。**無**被弱歸併藏起的重複原子任務群——完美語意歸併也到不了 20×(≥3)。
3. **發散濾殺的是雜訊不是任務**：被殺 top 是 harness/控制詞（`/model` 150r、
   `<local-command-caveat>` 132r、`go` 75r、`/effort` 70r、`Set model to…` echo、`ok` 37r、
   `<bash-input>`、skill dir header），非重複原子任務（「開PR push and merge main」反而存活、
   出現在保留集 freq-2）。故濾器未藏重複。

### 為何「資料未就緒」不成立（修正先前過寬讀法）
去噪只會從**分母**移除雜訊，**不會製造** freq-3 重複。語料最高頻字串本身就是
harness 噪音與控制詞（go/ok/繼續/`/model`），非 Shiba 的工程任務 → 即便修好
ingestion 原子化，重複頻率仍上不去。

### 殘留誠實 caveat（不改判決方向）
- `instruction` 欄確含非原子大塊（整份 plan 貼上、grok dump）與漏過 junk 的系統雜訊。
- 發散濾確實連帶殺掉少數真實 step-control（「先做A4結束後停止」型）。
- 兩者皆真，但即使全額補回也跨不過 2×→20×(≥3) 的鴻溝 → FAIL 方向不變。

### Gate 後路徑（plan §決策）
FAIL（穩健）→ 高價值負結果：省下 Phase 2+ Library build。退路＝**不建 Library、
改純查詢側召回改善（HyDE）**，回 advisor 校準；或重新定義「pattern」單位
（非逐字指令，而是更高階任務類型）再量——但那是新前提，需另證。
"""


def _render_result_md_full(report: dict, top_patterns: list[tuple[str, int]]) -> str:
    return _render_result_md(report, top_patterns) + _INTERPRETATION


def main() -> None:
    rows = load_rows()
    freqs = compute_pattern_frequencies(rows)
    report = evaluate_gate(freqs)
    top = sorted(freqs.items(), key=lambda kv: kv[1], reverse=True)
    out_path = Path(__file__).resolve().parent / "RESULT.md"
    out_path.write_text(_render_result_md_full(report, top), encoding="utf-8")
    print(f"gate passed={report['passed']} qualifying={report['qualifying_patterns']} "
          f"coverage={report['coverage']} -> {out_path}")


if __name__ == "__main__":
    main()
