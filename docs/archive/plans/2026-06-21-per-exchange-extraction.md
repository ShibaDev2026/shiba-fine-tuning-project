# 2026-06-21 per-exchange 抽取（D4 配對品質 → fine-tuning yield）

> 完成驗證後刪此檔。只記待做決策，不記已完成細節。

## 背景（一句）
fine-tuning 卡 approved yield（block1/2 各 7、需 30）。診斷定位真因＝extraction `_build_alpaca_sample`
用「`exchanges[0].user`（首句）× `exchanges[-1].assistant`（尾句）跨 over-merged session」**結構性製造
不連貫配對**。乾淨自包含 instruction 不缺（語料 716 個），瓶頸是配對形狀。
證據：experiments/2026-06-21_refiner_lever_probe/RESULT.md（gold 完美對 4/5 過 8.0、真實首尾配對 2-6）。
見 memory [[project-finetune-yield-diagnosis]]。

## 設計（已核可方案 A）
新增 **per-exchange 抽取路徑**：每個「自包含 instruction」的**單一 exchange** → 一個樣本
（instruction = 該 exchange 的 user_open、output = **同一 exchange** 的 final assistant），配對
**by construction 連貫**、繞過 D4 branch over-merge（每 exchange 是乾淨單元、不依賴 session 邊界正確）。
保留既有 per-session 路徑給真多輪任務（標 source 區分）。

## 待定決策（實作中要拍板）
1. **自包含判定**：啟發式（length 12-200 + 問句/祈使 + 非碎片開頭 + 非雜訊，零成本）vs LLM（refiner，準但慢+幻覺風險）→ **傾向先啟發式粗篩、judge 終審把關**（judge 已證會擋不連貫）。
2. **block 分配**：用該 exchange 自己的 event_type；`sessions.event_types` 可能多值 → 需確認 per-exchange 怎麼推導 event_type（或沿用 session 級）。
3. **dedup**：C3 已是 exchange-level（`source_exchange_ids`）→ 確認 per-exchange 路徑與既有 dedup 相容、不重複抽。
4. **雜訊**：per-exchange 的 user_open 仍含 41.6% 雜訊（`<command-*>`/`[Request interrupted]` 等）→ 自包含啟發式須一併排除（與 [[project-exchange-embeddings-ingestion-noise]] 對齊，但只在抽取端篩、不改寫入端）。

## 實作步驟（base-assumption-first：先驗 yield 再建）
- **Step 1（gate，Opus high）yield 驗證 at scale**：擴 `corpus_selfcontained.py` 樣本（n=8→50-100），
  量化「per-exchange 路徑下真實乾淨對的 judge 通過率」。若 ×716 估算 **< 30/block → 停、回報、不建**。
  （現有 n=8 給 1/8≈12.5%、×716≈90 對≈45/block，但區間寬，須擴樣確認。）
- **Step 2（Opus high）per-exchange 抽取路徑**：pipeline.py 新增路徑（如 `_extract_layer1_per_exchange`），
  TDD（紅→綠）；source 標記、instruction/output 同 exchange、自包含啟發式過濾。
- **Step 3（Sonnet medium）block 分配 + dedup 整合**：per-exchange event_type → block，C3 dedup 相容。
- **Step 4（Haiku low）驗證**：跑 extraction + judge，量 approved yield，對比 baseline。

## 驗證指令清單
- baseline（現況）：block1=7 / block2=7 approved。
- 目標：各 block ≥30 approved（觸發訓練）。
- `pytest tests/layer2/ -q`（extraction 子集）。
- yield 量測：`SELECT adapter_block,status,COUNT(*) FROM training_samples WHERE source='<新路徑>' GROUP BY 1,2`。

## /model /effort 切換
Step1/2 核心演算法 → Opus high；Step3 整合 → Sonnet medium；Step4 驗證 → Haiku low。
