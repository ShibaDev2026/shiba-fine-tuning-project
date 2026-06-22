# RAG 召回改善 / Agentic RAG 演進 — Design Doc

> 狀態：DISCUSS（待 Shiba review）｜ 日期：2026-06-22｜ slug：rag-recall-improvement
> 來源：papers 05–46 深讀（subagent 報告）+ 實測 DB 事實 + 四方向可行性對比
> 關聯 memory：[[project-rag-injection-transparency]] [[project-finetune-yield-diagnosis]] [[project_b_group_harness_probe_closed]] [[reference_rag_agentic_paper_library]]

---

## 1. 問題與背景

主線（2026-06-21 重定向）：累積驗證過的指令模式 → RAG/Agentic 召回 → 本地 in-context 代理執行。本 design 聚焦「**提升召回 / 把單一 Router RAG 演進為 Agentic RAG**」。

**實測現況（DB，非 memory 數字）**：

| 指標 | 值 | 約束意義 |
|------|----|---------|
| `exchange_embeddings` 列 / distinct instruction | 2578 / 1155 | RAG 語料 |
| 指令重複(≥2)占比 | 15.1% distinct / 61.9% 列 | ⚠ raw 含 junk + D4 灌水，真實有意義重複遠低 |
| 高頻 10+ 指令 | 34 個 = 1123 列(43.6%) | ⚠ 高度疑似 junk/控制詞，須剝離 |
| `router_decisions` accepted（auto/manual/空）| 161（167/**19**/1578）| ⚠ **manual gold 僅 19**，飛輪真實燃料極少 |
| `sessions_fts` / `exchanges` | 573 / 45629 | ⚠ FTS5 lexical arm 壞死（涵蓋 1.3%）|
| `_vector_search` 排序 | 純 cosine 單因子 + floor 0.35 | 排序只有 relevance 一軸 |

**已知約束牆（設計必須繞開或正面處理）**：
1. **golden-set cosine-bound** — RAGAS gt 抽自 bi-encoder+FTS5，結構上無法公平評「打敗 cosine 的召回法」（殺死 reranker PoC）。
2. **B 組已結案** — bge-m3 召回足強（miss≤7.1%）；單純換 embedding/加 reranker/擴 top-k EV 不成立。
3. **FTS5 lexical arm 壞死** — 涵蓋 1.3%，sparse/hybrid 融合在修好前是死的。
4. **macro-exchange 切割死路** — 召回整段軌跡淨負，須召回單一指令步。
5. **語料 D4 灌水** — exchanges 切片重複，量測前須去重。

---

## 2. 目標與非目標

**目標**：用 base-assumption-first（最小本地實驗、~$0、gate 不過就停）驗證並落地「真實能提升召回 / 啟動 Agentic 化」的最小改動，全程繞開 cosine-bound 測量牆（以**下游採納 A/B**量測，不依賴壞掉的 golden set）。

**非目標**（YAGNI）：
- ❌ 重啟 B 組（換 embedding / 獨立 reranker / 擴 top-k）。
- ❌ 建 Graph RAG（paper-34 煞車：local-fact 任務 vanilla≈勝、40× token 膨脹）。
- ❌ 修 golden set / sparse-hybrid 融合（除非走 Phase 4 離線量測分支）。
- ❌ fine-tune（roadmap P5 後期選配，非本 design 範圍）。

---

## 3. 整體架構：四階段 gated 程式（每階段過 gate 才進下一階段）

```
①EV gate ──pass──> ②HyDE 召回增強 ──pass──> ③Agentic 化(路由+Verifier)
  (元決策)            (真實召回增益)            (架構升級)
                                          ④DREAM 補標(按需，僅離線量測分支才啟動)
```

每階段對應一個獨立可理解/可測單元（SRP）；後階段透過明確介面消費前階段產出，不耦合內部實作。

---

## 4. Phase 1（立即可實作）— EV gate 量測

**目的**：在建任何 Library 基礎建設前，先證偽/證實前提「指令任務重複頻率夠高，使 in-context 召回的省 Claude-call 紅利 > 採納摩擦成本」。

**單元邊界（SRP）**：一支離線分析腳本 `experiments/2026-06-22_ev_gate/measure.py`，**零 production code 改動**，唯讀 DB。

**做什麼**：
1. **去 junk**：套用既有 `is_low_signal_query` / `is_short_query`（≤15 字）/ `is_system_meta_query` 三閘，濾掉控制詞與系統 meta。
2. **去 D4 灌水**：以 `exchange_embeddings.session_uuid + instruction` 折疊跨 branch 複製（同一 distinct message 多 branch 重複只計一次）。
3. **參數化正規化（輕量版）**：把 repo 路徑 / 檔名 / branch / PR 號替換成變數槽（regex，對應 AWM 參數化），讓「逐字具體」的同型任務歸併。
4. **算重複頻率直方圖** + **EV 估算**：對清洗後的 distinct task-pattern，算頻率分布；估「若 Library 命中可省的 Claude 呼叫次數」= Σ(pattern 頻率 × 採納機率上界 13%)。

**產出**：`experiments/2026-06-22_ev_gate/RESULT.md`（清洗前後對比表 + 直方圖 + EV 估值；負結果照實寫）。

**Gate 判準（待 Shiba 確認門檻）**：
> **PASS** 若清洗後存在 **≥ 20 個** distinct 有意義 task-pattern 重複 **≥ 3×**，且這些 pattern 覆蓋 **≥ 25%** 的非-junk 任務量。
> 理由：13% 採納天花板下只需「適度的重複頭部」即值得建 Library；門檻刻意保守，寧可 gate 不過也不空建。
> ⚠ **此數字是提案、可調**——Shiba 可依風險偏好調整 20/3×/25% 任一參數。

**成本**：~0.5 天 / $0。**不直接改善召回**（元決策）。

---

## 5. Phase 2（Gate 1 過後）— HyDE 查詢側召回增強

**目的**：最獨立、不撞牆的真實召回增益。

**單元邊界**：改動集中在 `rag.py:_vector_search()`（622 行檔案中單一函數），不動 router、不動 schema。

**機制**：
- **HyDE**：在 line 493 `get_embedding(query)` 前插一步——本地模型依 Shiba 短指令生成「假設指令模式文件」（含預期工具鏈）→ embed 假設文件而非原始 query → bge-m3 dense 召回真實 Pattern。dense bottleneck 濾掉生成的錯誤細節（paper 09）。
- **前置守衛**：query 先過 `is_low_signal_query`（模糊詞不 HyDE，避免跑偏）。
- **介面（DIP）**：HyDE 生成抽象成 `expand_query(query) -> str`，預設實作呼本地模型；可注入 no-op 實作（=現狀）做 A/B 與回退。
- **可選子項 — 三因子排序**（paper 30，0.5 天）：line 535 sort key 由純 cosine 改 `α·cosine + β·importance + γ·recency`；importance = `router_decisions` 採納次數（先用 auto 167 當弱訊號 + manual 19），recency = 既有 access 統計指數衰減。**獨立 flag，可不與 HyDE 同時上**。

**量測（繞開 cosine-bound）**：下游**採納率 A/B**（HyDE on/off 各跑一段，比採納 vs 回退），不碰 golden set。

**錯誤處理**：本地模型不可用 → `expand_query` 回原 query（優雅降級，等同現狀）；HyDE 召回為空 → 既有 FTS5 fallback 不變。

**測試**：`tests/memory/test_rag.py` 加（a）HyDE on 短指令召回非空、（b）本地模型失敗時 fallback 回原 query 不報錯。一行為一測（短+長 roundtrip 各一）。

**成本**：HyDE 1–2 天；三因子 +0.5 天。每次召回多一次本地推論（延遲 +數百 ms）。

**Gate 2 判準**：HyDE on 的採納率 ≥ off baseline（A/B，非劣化即 PASS 保留；顯著優則確立）。

---

## 6. Phase 3（Gate 2 過後）— Agentic 化（路由 + Verifier）

> 設計層描述，細節待 Phase 2 結果再具體化（YAGNI：召回未證強前不細設）。

- **L0 三檔路由**（paper 16 Adaptive-RAG）：`router.py` route 前加複雜度分類 A（不召回/本地直答）/ B（單步召回）/ C（回退 Claude）。**先規則版**（現有 gate 即雛形）；學習版受 manual=19 限制，暫不訓分類器。
- **P3 Verifier**（paper 13 CRAG + 11 Self-RAG）：route() 後、執行前插 propose-check 階段，本地裁判 prompt-based 自評 IsSup（pattern 是否支撐任務）/ IsUse（提案有用度），低信心**優雅回退 Claude**（對應 13% 天花板）。
- **Gate 3 判準**：Verifier 本地裁判自評準確率須先小規模驗（能否接近論文 84%）；過度阻擋（paper 14 警示 TSR 掉到 40%）為否決條件。

**成本**：3–5 天。

---

## 7. Phase 4（按需，非主線）— DREAM 補標解測量牆

> 僅當 Shiba 要系統性評比多種召回法（sparse 復活 / reranker / RankRAG）時才啟動。

- 本地三裁判辯論補標 → 產出獨立於 cosine 的 golden-set gt（paper 08，論文 95.2% 準確 / 3.5% 人工）。
- 改 `modules/ragas/golden_set_builder.py:build_candidates`，不動 production 召回。
- **硬 gate**：先小規模驗本地裁判補標準確率能否接近 95%。
- **成本**：5–7 天+。**是解鎖器、不改善召回本身**。

---

## 8. SOLID 自檢

- **SRP** ✅：每 Phase 一單元一職責；Phase 1 純量測、Phase 2 純召回增強、Phase 3 純路由/驗證。
- **OCP** ✅：HyDE 經 `expand_query` 抽象擴展 `_vector_search`，不改其核心 cosine 邏輯；三因子為可選 flag。
- **LSP** ✅：`expand_query` no-op 實作可完全替換真實實作、行為退回現狀。
- **ISP** ✅：HyDE / 三因子 / 路由 / Verifier 各自獨立 flag，不強迫一起啟用。
- **DIP** ✅：召回增強依賴 `expand_query` 抽象而非具體本地模型；Verifier 依賴裁判抽象。

---

## 9. 副作用清單

1. **Phase 1**：純唯讀腳本 + 新增 `experiments/` 目錄，無 production 副作用。
2. **Phase 2 HyDE**：每次召回多一次本地 LLM 推論 → 延遲 +數百 ms、本地模型負載上升；本地模型故障時靜默退回原 query（已設計優雅降級，但須測試覆蓋以防靜默失效）。
3. **Phase 2 三因子**：改排序權重 → 既有 recall_log 召回原因記錄格式可能需同步（importance/recency 分數）。
4. **Phase 3**：router 新增「執行線」是新管線，引入 propose-check-execute 的失敗模式（過度阻擋/漏放）。
5. **跨 Phase**：HyDE/三因子改變召回行為 → 既有 `recall_logs/<date>.txt` 稽核日誌語意改變，須在文件註記基準點。

---

## 10. 推薦執行順序與 model/effort

| Phase | 內容 | /model + /effort | 時機 |
|-------|------|------------------|------|
| 1 | EV gate 量測腳本 | Sonnet medium（樣板分析）| 立即 |
| 2 | HyDE 核心 + expand_query 抽象 | **Opus high**（核心召回演算法）| Gate 1 過 |
| 2b | 三因子排序（可選）| Sonnet medium | 同上 |
| 3 | 路由 + Verifier | Opus high（架構）| Gate 2 過 |
| 驗證/收尾 | 各 Phase 測試 + RESULT.md | Haiku low | 各 Phase 末 |

---

## 11. 開放決策（需 Shiba 拍板）

1. **EV gate 門檻**：20 patterns / ≥3× / 25% 覆蓋 是否接受？（§4）
2. **Phase 2 範圍**：HyDE 單獨先上，還是 HyDE + 三因子一起？
3. **是否現在就把 Phase 3/4 納入本 design**，還是 Phase 1/2 為一個 spec、Agentic 化另開 spec（decomposition）？
