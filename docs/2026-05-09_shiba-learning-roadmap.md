# Shiba 技術學習歷程路線圖

> **目的**：按部就班累積 shiba-fine-tuning-project 所需的核心知識，每天 30 分鐘，混合概念與可驗證實驗。
> **監督指標**（供 Notebook LM 使用）：
> 1. 今日實驗是否完成？（有無輸出結果）
> 2. 概念是否對應到專案實際程式碼？
> 3. 是否有「一句話筆記」記錄學到什麼？

---

## 學習日誌格式

每天完成後，在本檔案底部新增一筆：

```
### [YYYY-MM-DD] D{n}：{主軸} — {今日主題}
- **概念摘要**：（一句話）
- **實驗指令**：`指令或程式碼`
- **實驗結果**：（貼輸出或截圖說明）
- **對應專案**：（哪支檔案 / 哪個功能）
- **疑問留存**：（未解的問題，下次追）
```

---

## 六大主軸總覽

| # | 主軸 | 為什麼需要 | 對應專案 |
|---|------|-----------|---------|
| A | SQLite 內部原理 | 已遇 5 次 corruption，需能預判風險 | `shiba_db.py`、PR2 SAVEPOINT |
| B | Embedding 與向量搜尋 | RAG 召回品質是 Layer 1/2 核心 | `rag.py`、`exchange_embeddings` |
| C | LLM Fine-tuning 基礎 | LoRA/GGUF/量化用但不理解，調參靠感覺 | Layer 3 MLX pipeline |
| D | 非同步 Python 與 FastAPI | APScheduler race、連線池、async context | `background.py`、`main.py` |
| E | 分散式系統入門 | 計劃多人架構、Redis MQ，需建立思維框架 | 長期計畫 Redis Streams |
| F | Docker 與 Linux 核心概念 | bind mount vs volume、SHM、file descriptor | docker-compose、Virtualization.framework |

---

## 每天執行模板

```
[概念] 15 min
→ 讀一篇官方文件段落，精確找目標，不漫遊

[實驗] 15 min
→ 在專案上跑一個最小可驗證指令
→ 記錄輸出（terminal 結果 / 數字比較）

[筆記] 一句話
→ 「今天學到 X，對應專案中的 Y」
```

---

## Week 1–2：主軸 A — SQLite 內部原理

**學習目標**：能讀懂 PRAGMA 輸出、預判鎖定衝突、設計 SAVEPOINT 事務。

| 天 | 概念（15 min） | 實驗（15 min） | 完成 |
|----|--------------|--------------|------|
| D1 | SQLite page 結構：B-tree、page size、header | `sqlite3_analyzer data/shiba-brain.db \| head -60` | ☐ |
| D2 | journal_mode：DELETE vs WAL vs WAL2 差異 | `PRAGMA journal_mode; PRAGMA page_count;` | ☐ |
| D3 | 鎖定協定：SHARED/RESERVED/PENDING/EXCLUSIVE | `lsof data/shiba-brain.db` 後端運行時拍快照 | ☐ |
| D4 | SAVEPOINT vs BEGIN TRANSACTION 語意 | 手寫巢狀 SAVEPOINT 測試 rollback 行為 | ☐ |
| D5 | busy_timeout 與 retry 邏輯 | 用兩個 Python 進程同時寫 DB，觀察 timeout 觸發 | ☐ |
| D6 | integrity_check / quick_check 差異 | 寫 Shell 一行驗證指令，計時比較兩者速度 | ☐ |
| D7 | VACUUM / VACUUM INTO 原理 | 改 `make_analysis_copy.sh` 輸出前後 page count | ☐ |
| D8 | FTS5 原理：倒排索引、trigram token | `INSERT / DELETE / REBUILD` 觀察 fts_data 表大小 | ☐ |
| D9 | mmap_size 效果 | 改 PRAGMA 前後用 `time` 測查詢速度 | ☐ |
| D10 | 索引選擇：何時全表掃描比索引快 | `EXPLAIN QUERY PLAN` 跑 training_samples 慢查詢 | ☐ |

---

## Week 3–4：主軸 B — Embedding 與向量搜尋

**學習目標**：能調整召回策略、診斷 RAG 召回品質問題、設計 hybrid search。

| 天 | 概念（15 min） | 實驗（15 min） | 完成 |
|----|--------------|--------------|------|
| D11 | 什麼是 embedding：語意壓縮到向量空間 | `ollama embed nomic-embed-text "測試句子"` 看維度 | ☐ |
| D12 | cosine similarity 數學：點積 / 模 | 手寫 3 行 numpy 計算，不用 library | ☐ |
| D13 | 向量資料庫 vs 線性掃描：何時值得升級 | 計算 1458 rows × 768 dim 掃描時間 | ☐ |
| D14 | 召回率 vs 精確率 trade-off | 調整 `rag.py` threshold 0.35→0.50，看結果變化 | ☐ |
| D15 | BM25 vs TF-IDF vs FTS5 | 相同 query 測 FTS5 與 vector 兩條路召回比較 | ☐ |
| D16 | Hybrid search：向量 + 關鍵字融合 | 設計 RRF（Reciprocal Rank Fusion）合併兩路結果 | ☐ |
| D17 | Chunking 策略：句子 / 段落 / 固定長度 | `user_text_preview` 截斷是否影響 embedding 品質 | ☐ |
| D18 | 中文 tokenization 問題 | jieba 分詞後 FTS5 vs 原始 FTS5 查詢比較 | ☐ |
| D19 | 向量壓縮：PQ / scalar quantization 概念 | nomic-embed-text 768d BLOB 大小計算 | ☐ |
| D20 | Re-ranking：cross-encoder 概念 | 閱讀 `multi_judge.py` — judge 評分就是一種 re-ranking | ☐ |

---

## Week 5–6：主軸 C — LLM Fine-tuning 基礎

**學習目標**：能看懂訓練 log、理解 LoRA 超參數意義、判斷訓練是否收斂。

| 天 | 概念（15 min） | 實驗（15 min） | 完成 |
|----|--------------|--------------|------|
| D21 | Transformer 架構：attention 一句話版 | 畫出 input→embedding→attention→output 流程圖 | ☐ |
| D22 | LoRA 原理：低秩矩陣 ΔW = A×B | 計算 7B model LoRA rank=8 節省多少參數 | ☐ |
| D23 | GGUF 格式：為何比 safetensors 快 | `ollama show qwen3:30b-a3b --verbose` 看量化資訊 | ☐ |
| D24 | 量化：Q4_K_M vs Q8_0 vs nvfp4 差異 | 你的 model yaml 中 num_ctx 與記憶體關係計算 | ☐ |
| D25 | MLX vs CUDA：Apple Silicon 為何選 MLX | `mlx_lm.lora --help` 看各參數意義 | ☐ |
| D26 | Instruction tuning 資料格式：Alpaca/ChatML | `training_samples` schema 對應哪種格式 | ☐ |
| D27 | DPO vs SFT：rejected 樣本有沒有用 | 閱讀 memory `project_rejected_samples_reuse.md` | ☐ |
| D28 | Catastrophic forgetting：為何要 replay | 你的 70/20/10 資料比例背後的理論 | ☐ |
| D29 | Eval metric：BLEU vs human rating | 你的 multi_judge score 算哪種 eval | ☐ |
| D30 | LoRA adapter merge：何時 merge 何時分離 | block1/block2 兩個 adapter 為何不 merge | ☐ |

---

## Week 7–8：主軸 D — 非同步 Python 與 FastAPI

**學習目標**：能診斷 async/thread 衝突、設計安全的 DB 連線池、理解 lifespan hook。

| 天 | 概念（15 min） | 實驗（15 min） | 完成 |
|----|--------------|--------------|------|
| D31 | Python GIL：thread vs process vs async 差異 | `background.py` 的 APScheduler 跑在哪個 thread？ | ☐ |
| D32 | asyncio event loop：coroutine / task / future | `asyncio.get_event_loop()` 在 FastAPI 中的狀態 | ☐ |
| D33 | FastAPI lifespan hook：startup/shutdown | 閱讀 `main.py` 的 lifespan context manager | ☐ |
| D34 | SQLite connection pool 問題：為何不能 pool | `check_same_thread=False` 的風險與 workaround | ☐ |
| D35 | APScheduler：AsyncIOScheduler vs BackgroundScheduler | 你的 scheduler 為何選 AsyncIO | ☐ |
| D36 | Dependency Injection in FastAPI | `Depends()` 與 `conn_factory` 的關係 | ☐ |
| D37 | HTTP middleware：logging / error handling | 在 `main.py` 加一個計時 middleware | ☐ |
| D38 | Pydantic model：validation 邊界 | Layer 2 API 的 request/response schema 在哪裡 | ☐ |
| D39 | httpx vs requests：async HTTP client | `_run_finetune_check` 為何用 httpx | ☐ |
| D40 | 背壓（backpressure）：queue 滿了怎麼辦 | APScheduler `coalesce=True` 的實際效果 | ☐ |

---

## Week 9–10：主軸 E — 分散式系統入門

**學習目標**：能設計 Redis Streams consumer group、理解 CAP 定理對你架構的影響。

| 天 | 概念（15 min） | 實驗（15 min） | 完成 |
|----|--------------|--------------|------|
| D41 | CAP 定理：Consistency / Availability / Partition | 你的 SQLite 架構在 CAP 三角的哪個位置 | ☐ |
| D42 | Message Queue 基礎：pub/sub vs point-to-point | Redis Streams vs Kafka vs RabbitMQ 一表比較 | ☐ |
| D43 | Redis Streams：XADD / XREAD / XGROUP | `docker run redis` + `redis-cli` 跑最小範例 | ☐ |
| D44 | Consumer Group：single-writer 保護 | 設計一個 Python consumer 讀 Redis Stream | ☐ |
| D45 | Idempotency：重複訊息不重複執行 | 你的 extraction job 如果跑兩次會怎樣 | ☐ |
| D46 | 分散式鎖：Redis SETNX / Redlock | APScheduler `max_instances=1` 等價物 | ☐ |
| D47 | 事件溯源（Event Sourcing）概念 | `router_decisions` 表是不是一種 event log | ☐ |
| D48 | gRPC vs REST：何時選哪個 | 你的 Layer 0→2 HTTP 呼叫延遲計算 | ☐ |
| D49 | 服務發現：DNS vs service registry | docker-compose 的 service name 解析原理 | ☐ |
| D50 | 資料一致性：eventual vs strong consistency | multi_judge 三票投票算哪種一致性模型 | ☐ |

---

## Week 11–12：主軸 F — Docker 與 Linux 核心概念

**學習目標**：能看懂 `lsof` / `strace` 輸出、設計安全的 volume 策略、理解 bind mount 限制。

| 天 | 概念（15 min） | 實驗（15 min） | 完成 |
|----|--------------|--------------|------|
| D51 | Linux file descriptor：open / close / fork | `lsof -p $(pgrep uvicorn)` 數 fd 數量 | ☐ |
| D52 | inode vs file path：為何 rename 是原子的 | SQLite `.recover` SOP 中 swap 步驟的原理 | ☐ |
| D53 | bind mount vs named volume：核心差異 | 你的 DB corruption 根因：bind mount + SHM | ☐ |
| D54 | Docker network：bridge / host / overlay | `docker network inspect` 你的 compose 網路 | ☐ |
| D55 | cgroup：記憶體 / CPU 限制原理 | `docker stats` 看各 container 使用量 | ☐ |
| D56 | POSIX 鎖：flock vs fcntl lock | SQLite 用哪種？`strace` 驗證 | ☐ |
| D57 | Virtualization.framework：macOS VM 架構 | 你的 SHM corruption 根因的系統層解釋 | ☐ |
| D58 | fsync / fdatasync：何時保證寫入 | `synchronous=NORMAL` vs `FULL` 的 fsync 次數 | ☐ |
| D59 | Multi-stage Dockerfile：減小 image 大小 | 你的 `backend/Dockerfile` 有幾個 stage | ☐ |
| D60 | docker-compose restart policy：on-failure:3 | 你現在的設定是什麼，為何選這個數字 | ☐ |

---

## 進度追蹤

| 主軸 | 總天數 | 已完成 | 最後更新 |
|------|-------|-------|---------|
| A — SQLite | 10 | 0 | — |
| B — Embedding | 10 | 0 | — |
| C — Fine-tuning | 10 | 0 | — |
| D — 非同步 Python | 10 | 0 | — |
| E — 分散式系統 | 10 | 0 | — |
| F — Docker/Linux | 10 | 0 | — |
| **合計** | **60** | **0** | — |

---

## 學習日誌

<!-- 每天完成後在此新增一筆，格式如上方說明 -->

### 範例：[2026-05-09] D1：A — SQLite page 結構
- **概念摘要**：SQLite 以固定大小 page（預設 4096 bytes）組織 B-tree，header 前 100 bytes 存 schema version / page count
- **實驗指令**：`sqlite3_analyzer data/shiba-brain.db | head -60`
- **實驗結果**：training_samples 佔 23 pages，sessions 佔 8 pages
- **對應專案**：`shiba_db.py` 的 mmap_size 設定對 page 讀取的影響
- **疑問留存**：fragmentation ratio > 10% 要 VACUUM 嗎？

---

*路線圖由 Claude Code 根據 shiba-fine-tuning-project 實際技術瓶頸設計，2026-05-09*
