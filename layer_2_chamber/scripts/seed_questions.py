"""
seed_questions.py — 種子題目集初始化

為 block1（git_ops/terminal_ops/code_gen）與 block2（debugging/architecture/knowledge_qa）
各建立一批初始題目，供 Layer 2 主動生成訓練樣本。

執行：
    python layer_2_chamber/scripts/seed_questions.py
    python layer_2_chamber/scripts/seed_questions.py --list
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from layer_2_chamber.backend.core.config import init_layer2_db

# ── 題目集定義 ────────────────────────────────────────────────────────────

QUESTION_SETS = [
    # ── Block 1：bash/tools 執行 ──────────────────────────────────────────
    {
        "name": "git_ops_基礎",
        "event_type": "git_ops",
        "description": "Git 操作基礎：commit、branch、merge、rebase",
        "questions": [
            ("如何建立一個新 branch 並切換過去？", 3),
            ("如何撤銷最後一次 commit 但保留檔案修改？", 5),
            ("如何解決 merge conflict？說明步驟。", 6),
            ("git rebase 與 git merge 的差異是什麼？各適用什麼場景？", 7),
            ("如何查看某個檔案的完整修改歷史？", 4),
            ("如何將特定 commit 從一個 branch cherry-pick 到另一個？", 6),
            ("如何建立並推送 annotated tag？", 4),
            ("git stash 的用途是什麼？如何恢復 stash？", 3),
        ],
    },
    {
        "name": "terminal_ops_基礎",
        "event_type": "terminal_ops",
        "description": "終端機操作：檔案管理、程序控制、環境設定",
        "questions": [
            ("如何用一行指令找出目錄下所有超過 100MB 的檔案？", 5),
            ("如何查看並終止某個 port 上的程序？", 4),
            ("如何用 jq 從 JSON 檔案中擷取特定欄位？", 5),
            ("如何設定 cron job 每天凌晨 2 點執行腳本？", 4),
            ("如何監控實時 log 並過濾特定關鍵字？", 4),
            ("如何壓縮一個目錄並排除某些子目錄？", 5),
            ("如何查看系統目前的記憶體與 CPU 使用狀況？", 3),
            ("如何用 ssh tunnel 將遠端 port 轉發到本機？", 7),
        ],
    },
    {
        "name": "code_gen_Python",
        "event_type": "code_gen",
        "description": "Python 程式碼生成：常見模式與最佳實踐",
        "questions": [
            ("寫一個 Python context manager 來計算程式區塊的執行時間。", 4),
            ("實作一個 LRU cache decorator，不使用 functools。", 7),
            ("寫一個非同步函式，並行呼叫多個 API 並合併結果。", 6),
            ("實作一個 retry decorator，支援指數退避（exponential backoff）。", 6),
            ("寫一個 SQLite WAL 模式下的 connection pool。", 7),
            ("實作一個 dataclass 的深度複製方法，處理巢狀結構。", 5),
            ("寫一個 CLI 工具，接受 stdin 或檔案路徑作為輸入。", 4),
            ("如何用 pathlib 遞迴搜尋符合 glob pattern 的檔案？", 3),
        ],
    },
    # ── Block 2：中文推理與知識回應 ───────────────────────────────────────
    {
        "name": "debugging_系統性",
        "event_type": "debugging",
        "description": "系統性除錯：從錯誤訊息到根本原因",
        "questions": [
            ("SQLite OperationalError: database is locked 如何診斷與修復？", 5),
            ("Python 程式記憶體持續增長，如何找出 memory leak？", 7),
            ("FastAPI endpoint 偶發性 timeout，如何系統性排查？", 7),
            ("git push 後 CI 失敗但本地測試通過，可能原因有哪些？", 5),
            ("SQLite FTS5 查詢回傳空結果但資料確實存在，如何除錯？", 6),
            ("Python import 時出現 circular import error，如何解決？", 6),
            ("APScheduler job 沒有按時觸發，如何診斷原因？", 6),
            ("zlib.decompress 失敗並拋出 Error -3，可能原因是什麼？", 5),
        ],
    },
    {
        "name": "architecture_設計",
        "event_type": "architecture",
        "description": "軟體架構與設計決策",
        "questions": [
            ("SQLite 與 PostgreSQL 在 multi-process 寫入場景下如何選擇？", 6),
            ("解釋 WAL 模式為何能改善 SQLite 的並發讀寫效能。", 5),
            ("設計一個支援多個 LLM provider fallback 的路由架構。", 7),
            ("FTS5 全文索引與向量搜尋各自適合哪種查詢場景？", 6),
            ("如何設計一個零停機的 schema migration 流程？", 7),
            ("LoRA fine-tuning 與 full fine-tuning 的取捨是什麼？", 6),
            ("解釋 MoE（Mixture of Experts）模型為何適合在有限記憶體下運行。", 7),
            ("設計一個本地 AI agent 的三層模型路由架構（fast/primary/heavy）。", 8),
        ],
    },
    {
        "name": "knowledge_qa_MLX",
        "event_type": "knowledge_qa",
        "description": "Apple MLX 框架與本地 LLM 相關知識",
        "questions": [
            ("MLX 的 unified memory 架構與傳統 GPU 記憶體的差異是什麼？", 6),
            ("llama.cpp 的 --mmap 參數如何讓 16GB 機器跑 35B MoE 模型？", 7),
            ("LoRA 訓練的 rank 參數如何影響訓練效果與記憶體用量？", 6),
            ("GGUF 格式相比 safetensors 有哪些優勢？", 5),
            ("量化（quantization）對模型推論速度與品質的影響？", 6),
            ("Ollama 的 OLLAMA_MAX_LOADED_MODELS 設定在 16GB 機器上為何要設為 1？", 4),
            ("think: false 在 Qwen/Gemma 模型的 Ollama API 中有什麼作用？", 5),
            ("nomic-embed-text 與 text-embedding-ada-002 在本地部署上的比較。", 6),
        ],
    },
]


def cmd_seed(conn):
    """寫入所有種子題目集"""
    total_sets = 0
    total_questions = 0

    for qs in QUESTION_SETS:
        # 檢查是否已存在
        existing = conn.execute(
            "SELECT id FROM question_sets WHERE name = ?", (qs["name"],)
        ).fetchone()

        if existing:
            print(f"  ○ 已存在：{qs['name']}，跳過")
            continue

        cur = conn.execute(
            "INSERT INTO question_sets (name, event_type, description) VALUES (?, ?, ?)",
            (qs["name"], qs["event_type"], qs["description"]),
        )
        set_id = cur.lastrowid

        for prompt, difficulty in qs["questions"]:
            conn.execute(
                "INSERT INTO questions (set_id, prompt, difficulty) VALUES (?, ?, ?)",
                (set_id, prompt, difficulty),
            )
            total_questions += 1

        print(f"  ✓ {qs['name']} ({qs['event_type']})：{len(qs['questions'])} 題")
        total_sets += 1

    conn.commit()
    print(f"\n完成：新增 {total_sets} 個題目集，{total_questions} 道題目")


def cmd_list(conn):
    """列出現有題目集"""
    rows = conn.execute(
        """SELECT qs.id, qs.name, qs.event_type,
                  COUNT(q.id) as q_count
           FROM question_sets qs
           LEFT JOIN questions q ON q.set_id = qs.id
           GROUP BY qs.id ORDER BY qs.event_type"""
    ).fetchall()

    if not rows:
        print("（無題目集，請執行 seed）")
        return

    print(f"{'ID':<4} {'名稱':<25} {'event_type':<18} {'題數'}")
    print("-" * 58)
    for r in rows:
        print(f"{r['id']:<4} {r['name']:<25} {r['event_type']:<18} {r['q_count']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layer 2 種子題目集設定")
    parser.add_argument("--list", action="store_true", help="列出現有題目集")
    args = parser.parse_args()

    conn = init_layer2_db()
    if args.list:
        cmd_list(conn)
    else:
        print("=== 種子題目集初始化 ===\n")
        cmd_seed(conn)
        print()
        cmd_list(conn)
    conn.close()
