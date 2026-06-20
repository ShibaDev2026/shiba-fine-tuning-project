# B 組 Retrieval Delta — leave-one-out kill-switch

> 性質：**kill-switch 實驗**，非建 infra。一個下午回答「召回是否有 generalizable value，B 組 recall 路線值不值得投」。完成驗證後刪本檔。

## Base assumption 待驗證
「用 RAG 召回過去高品質對話 → 放系統提詞 → 小模型模仿」這條路，**召回的記憶對最終答案品質有可測的 generalizable 增益**。

目前**測不出**：現有評估資產雙重 source-session-bound——
1. retrieval gt（`expected_session_uuids`）cosine+FTS5 抽樣 → cosine-bound（reranker PoC 已揭）
2. `expected_answer` 由 Gemini 看同一批 cosine session 生成（`c1_generate_answers.py:116`）+ c2_e2e 召回**無 leave-one-out** → dynamic few-shot 會召回答案來源、結構性灌水 delta

## 設計

**復用**（c2_e2e 既有）：judge + `delta=sa-sb`（L444）+ golden loading。
**新寫**：
- **leave-one-out**：c2_e2e 召回時排除當題 `expected_session_uuids` 指向的 source session。
- **static few-shot arm**：固定一組高品質範例（跨題共用、不依 query），當對照組。現有 `rag_window=0` 仍是 per-query 召回，static 不存在。

**三臂對照**（同題、同模型、同 judge，只差召回方式）：
| arm | 召回 | 角色 |
|-----|------|------|
| static | 固定範例，不依 query | baseline |
| dynamic+LOO | 依 query 召回，排除 source session | 受測 |
| (可選) no-context | 不放記憶 | 地板 |

**指標**：c2_e2e answer-quality judge mean_score；`delta = dynamic(LOO) − static`。
**樣本**：現有 65 題（有 expected_answer）。統計力弱，僅判方向，不下精細結論。

## Kill-switch 判讀
- **dynamic(LOO) >> static**（delta 顯著正）→ 召回有 generalizable value → 路線活，**才**進「放大乾淨 golden + 投 few-shot 技術」
- **dynamic(LOO) ≈ static**（delta≈0）→ 每答案只能從自己來源找到 → 此 golden set 無法測 generalizable retrieval value → 重建乾淨 golden 或 B 組 recall 路線喊停

## 待決策（開跑前需 Shiba 拍板）
- **D-a judge 選型**：gemini-2.5-flash 現 `is_active=0`。臨時開付費（保 delta 數字與歷史可比）vs 改本地 panel（省配額、但與舊 delta 不可比）。傾向**臨時開付費**跑這一輪。
- **D-b static 範例組成**：固定幾筆？選 gatekeeper_golden_samples（48 凍結 Tier B）裡的高分樣本，跨題共用一組。
- **D-c LOO 粒度**：先只排 source session（最小）；near-dup 相似 session 是否也排，待首輪結果再定。

## Caveat（不在 kill-switch 範圍，但 delta 為正後必須處理）
- **expected_answer 目的錯位**：是 Gemini 生成、非過去 Claude 回應 → judge 測「像不像 Gemini」非「像不像過去高品質對話」。delta 為正只證明「召回助某種模仿」，要對齊 Shiba 目的須換獨立 expected_answer。
- **content vs style**：judge 評語意吻合+資訊完整性＝content fidelity，非回答 style；Shiba 要 style 模仿，指標與目標相鄰非重合。

## 步驟 × model/effort
1. **LOO patch + static arm**（核心正確性）→ Opus high
2. **跑三臂 + 判讀 delta**（整合執行）→ Sonnet medium
3. **結論入 memory + 刪本檔**（收尾）→ Haiku low

## 否決的替代（記錄供後）
- 直接建 dynamic few-shot infra / 放大 golden：違反 base-assumption-first，且在污染儀器上＝reranker 重演。
- 重建獨立 expected_answer 的乾淨 golden：成本高，**僅在本 kill-switch 出正 delta 後**才重開（屆時知道值得投）。
