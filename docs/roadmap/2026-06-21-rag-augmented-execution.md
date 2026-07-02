# Roadmap：RAG-augmented 代理執行（2026-06-21 定）

> ⛔ **SUPERSEDED（2026-07-03）**：本 roadmap P1–P5 已全數廢止/擱置——P1 Pattern Library（EV gate + keystone probe 雙 FAIL：574 session 任務重複 freq≥3=0）、P2 召回餵本地執行（「召回 > 好模型+指令檔」前提未證＋13% 採納水位）、P3 Verifier（隨 P2 擱置）、P4 D4 回填（無下游）、P5 fine-tune（無資料）。現行主軸＝**author / curate / eval / route**，見 `AGENTS.md`／`CLAUDE.md`「主軸」節。本檔保留作歷史脈絡，不再更新。

> 主線重定向的完整版。CLAUDE.md 只放骨架，細節在此。運作宗旨（harness engineering 自主開發迴圈）見 CLAUDE.md。

## 為什麼重定向（證據）
原目標「累積對話資料 → 訓練本地模型接手任務」的**訓練資料前提斷了**：2026-06-21 全診斷證實，通往
30/block approved 的 **5 條 harvest 路徑在現有資料全不通**（per-exchange/error_repair 撞「真實 output
非答案形狀」牆、refiner 改 instruction 無效、#2 user_accepted 採納全是 auto-heuristic 非 manual gold；
gold 手撰對照 4/5 過 8.0 證判官沒壞、牆在 output）。詳見 memory [[project-finetune-yield-diagnosis]]
與 `experiments/2026-06-21_refiner_lever_probe/RESULT.md`。

**但 RAG 召回是唯一被嚴格驗證可行的資產**（bge-m3 召回足強，B 組 cosine-bound probe 關閉）。
故重定向：**累積「驗證過的指令模式」→ RAG/Agentic 召回 → 本地 in-context 代理執行**；fine-tune
退為「Library 夠大 + 高頻模式穩定才壓權重」的後期選項。

## 架構：執行迴圈
```
你與 Claude Code 對話
   │
   ├─[蒸餾]→ Pattern Library（驗證過的 instruction→指令 模式，RAG 索引）
   │            ↑ 飛輪：你「刻意 manual 採納」一個好的本地輸出 = +1 gold 模式
   │
執行時某任務 →[Layer 0 路由判本地]
   ├─[Agentic RAG 召回]→ 從 Library 取相關模式（few-shot in-context）
   ├─[本地模型 in-context 執行]→ 提案指令
   └─[Verifier 判官閘]→ 通過才執行 → 結果 →（你採納/否）回饋飛輪
```
核心轉變：資料的「終點」從「訓練集」→「**Pattern Library**」（可召回、可稽核、即時生效、零訓練）。

## 舊 Layer 去留
| Layer | 命運 | 理由 |
|-------|------|------|
| L0 路由 | ✅ 保留 | 判任務走本地/Claude（13% 起步、隨 Library 成長）|
| L1 記憶 RAG | ✅ **升級主引擎** | 唯一實證可行；召回模式給模型執行（Agentic RAG）|
| L2 chamber/judge | ♻️ **轉 Verifier** | 從訓練資料篩選器 → 執行前安全閘 |
| L3 fine-tune | ⬇️ **降後期（P5）** | Library 大 + 高頻模式穩定才壓權重 |
| gatekeeper gold(48 題) | ✅ **變 Library 種子** | 本無用的 seed → Library 初始 gold 模式 |
| D4(6.8× 灌水) | 🔧 前置（僅 history backfill 需）| 飛輪前向收集不依賴 D4；回填歷史模式時需去重 |
| ingestion 雜訊 / feature_registry | 🔧 收尾債 | 影響模式品質 / 架構債 |

## 分階段（每階段帶 gate，過了才進下一個）

### P1 — Pattern Library + Manual-accept 飛輪（地基、先做）
- Pattern Library schema：`instruction → 指令/輸出 + 來源 + 採納標記 + 頻率`，RAG 索引。
- **Manual-accept UI**：取代 auto 啟發式（`infer_acceptance_from_text`）——讓 Shiba**有意識地** gate
  一個本地輸出為 gold。每次採納 = Library +1 fabrication-free gold（解掉「沒有 manual gold」根問題）。
- **Gate（決定整個 roadmap EV）**：(a) 先量 Shiba 的指令任務**到底多常重複**（用現有 RAG 資料算，低重複則
  Library 召回價值有限）；(b) 採納摩擦夠低、Shiba 會持續用（飛輪依賴行為改變，不用就轉不起來）。

### P2 — Agentic 召回 + in-context 執行
- 本地模型從 Library few-shot 執行；重用 L1 RAG（可進化成多跳/帶推理的 Agentic RAG）。
- **Gate**：召回的模式真能讓本地正確執行（小規模實測通過率 + 對比直接讓本地裸跑）。

### P3 — Verifier（propose-check-execute）
- 本地提案指令 → L2 judge 基建轉「執行前驗證閘」→ 通過才執行。
- **Gate**：能擋危險/錯誤指令、且不過度阻擋（precision/recall 平衡）。

### P4 —（並行/按需）D4 修復 + 歷史回填
- 修 branch over-merge（6.8× 灌水）→ 把歷史對話的高頻模式**去重後**回填 Library。
- 注意：飛輪（P1）是前向的、不必等 D4；D4 只在要挖歷史模式時成為前置。

### P5 —（後期/選配）fine-tune
- Library 夠大且確認高頻穩定模式 → 壓進權重（原 L3 pipeline）。非主線目標。

## 設計約束（硬限制，非裝飾）
1. **13% 採納天花板**（能力驗證實測）：本地只接手**高信心模式**、其餘**優雅回退 Claude**；不假設本地接管多數。
2. **指令重複頻率未知**：是 P1 第一個要量的——若低重複，整個 Library 路線 EV 受限，須先驗。
3. **飛輪依賴 Shiba 行為**：刻意採納若不持續，飛輪停。UI 摩擦要極低。

## 可加入的新技術（依知識到 2026-01）
- **In-context 技能庫**（P1 核心）：驗證模式蒸餾成可召回範例庫，few-shot，零 fine-tune、可解釋、即時生效。
- **Agentic RAG**（P2）：模型自決召回什麼、多步檢索，非單次 top-k。
- **Verifier / propose-check-execute**（P3）：judge 轉執行安全閘。
- **後期**：高頻模式 distillation 進權重（P5）。

## 運作方式（harness engineering 自主迴圈）
每 session 推進一個 gate：先 base-assumption 實驗驗 gate → 過了才建 → 證據留 `experiments/<date>_<slug>/RESULT.md`
→ 更新 memory（Active Plan + 下一個 gate）。負結果照實寫。詳見 CLAUDE.md `## 運作宗旨`。
