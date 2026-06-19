# D3 Judge 可信度診斷 — 混淆矩陣（2026-06-19）

## 目的
量化本地 panel（multi_judge 三方投票：Qwen3.5-35B / GLM-4.7-Flash / Gemma-4-e4b）對**真實 session 輸出**評分的可信度。動機：grading harness Tier B 實證 panel 對乾淨高分內容頂端飽和，懷疑 D3 文獻講的 agreeableness/self-preference bias（TPR>96% / TNR<25%，爛樣本被放行）。

## 方法
- **GT 來源優先序**：Shiba 人類標記（`router_decisions.user_accepted`）> Claude in-session 盲評。
- **盲評破循環**：Claude 只看 scrubbed `instruction/input/output`，**不看 panel 判定**（grader≠author）。
- **池**：`training_samples` status∈{approved,rejected} **AND `question_id IS NULL`**（排除 48 筆 Tier B 題庫橋接 gold——那些 approved 是 Claude 親評、非本地 panel 判定，納入會污染成 Claude-vs-Claude）。→ **乾淨池 74 筆**（14 approved + 60 rejected）。
- **PII**：全程 `grading_harness.scrub_for_export` + `assert_clean` fail-closed；74 筆 0 殘留。
- 工具：`scripts/judge_confusion_matrix.py`（export/compute + `tests/layer2/test_judge_confusion_matrix.py`）。

## 結果（positive = good＝該進訓練集）

原始混淆矩陣（**下節證明此矩陣的 panel-approved 軸被污染、作廢**）：

| | GT good | GT bad |
|--|--|--|
| **panel approved** | TP=10 | FP=4 |
| **panel rejected** | FN=11 | TN=49 |

TPR=0.476、TNR=0.925、n=74。Claude-vs-Shiba agreement = **27%**（good 1/9、bad 2/2）。

## ⚠ 核心發現：兩層污染，主矩陣作廢，但仍有穩固結論

### (1) Claude 作為 GT 失效（穩固，不受下節影響）
9 筆 Shiba **親自採納**的 good，Claude 盲評只認同 **1/9**（8 筆判 bad）。**Claude 不適合當此資料的 GT**——它的「訓練樣本價值」標準（自包含、可泛化）系統性比 Shiba 的「實用採納」標準嚴。63/74 筆 GT 來自 Claude 盲評 → 主矩陣的 GT 軸不可信。這是本診斷**真正的貢獻**，呼應 advisor #1（Claude 也是 LLM judge，當 GT 前須人類錨校準）。

### (2) panel-approved 軸被 high_value override 污染（advisor 抓到，我漏抓）
我排除了 Tier B（`question_id`）的 status 污染，**卻漏抓同一機制的 `user_accepted` override**：`multi_judge` 對 `user_accepted=1` **強制 approved 覆蓋 judge**。實查 **14 筆 approved（question_id IS NULL）：13 筆是 override，僅 1 筆自然 approve**（score 6.67）。9 筆 shiba-good 錨全在 override 內，panel 獨立 score avg 3.4（0.5–6.67）。

→ **panel-approved 軸 13/14 是 override artifact**——是 Shiba 採納設了 status，不是 panel 判定。panel 獨立分數（avg 3.4）**不支持這些 approval**（approve 是投票制非分數閾值，不能逐筆斷言 would-reject，但 avg 3.4 遠不到背書水準）。我先前「panel vs 人類 11/11、是 Claude 不一致」的反轉 **證偽**。

### (3) 修正後的真相
| 錨 | n | Shiba | panel 獨立(score) | Claude |
|----|---|-------|------------------|--------|
| good | 9 | good（採納） | 不背書（avg 3.4） | 8 bad / 1 good |
| bad | 2 | bad | reject ✓ | bad ✓ |

**panel 與 Claude 兩個 AI judge 都比 Shiba 嚴**：扣掉 13 override，panel **自然只 approve 1/74（≈1.4%）**。唯一三方乾淨一致的是 **2 個 bad 錨**（薄）。

**這是 construct divergence，非「Claude 壞了」**：三種「good」測不同東西——Shiba `user_accepted`＝**採納於情境**、Claude verdict＝**訓練價值**、panel score＝第三種。它們在 good 側分歧因為測不同 construct。Claude 判「參數找到了，更新計劃」是差的 standalone 訓練資料**對訓練價值而言是對的**；`user_accepted` 從來不是訓練價值信號。連到能力驗證的 judge-vs-採納背離主題——**方向對比可引用**：彼時付費 judge 太鬆（92% 通過 vs 13% 採納）、此處本地 panel 太嚴（自然 approve 1.4%）。

## 對 D3 原始問題的結論

1. **D3 文獻的 agreeableness/放水病（TNR<25%）在本專案 panel 上未觀察到——靠 aggregate 成立，不靠錨。** panel 對真實 session 輸出 reject 60/74、自然 approve 僅 **1/74（≈1.4%）**，**極嚴，與「放水」相反**。
2. **校準的原始動機（怕 panel 放水漏網）不成立。** → **D3「judge 校準」可結案：放水病不存在。**
3. **主混淆矩陣數字作廢**：GT 軸不可信（Claude 1/9）+ panel 軸 9 筆 override 污染。TPR/TNR 不可引用。
4. **浮現的新張力（非本次 scope，記錄供後）**：panel 與 Claude 的「品質標準」系統性嚴於 Shiba 的「實用採納」——兩個 AI 都濾掉 Shiba 覺得有用的 session 中間步驟回應。對 gold 篩選（要嚴）無害；對「不誤殺 Shiba 採納的實用樣本」有潛在代價。呼應能力驗證的 judge-vs-採納背離主題（方向相反：彼時 judge 太鬆，此處本地 panel 太嚴）。

## FP/FN 清單（Claude 標準下，複查候選非已證）
- **FP（panel approved 但 Claude 判 bad）**：sid 46, 47, 53, 54。
- **FN（panel rejected 但 Claude 判 good）**：sid 6, 11, 20, 27, 37, 55, 56, 65, 66, 69, 73（多為完整診斷/解釋/正確權限邊界處理，但 panel 偏嚴 reject）。

## 對 grading harness 的意涵
panel 對真實 session 輸出**極嚴、無放水漏網**（自然 approve ≈1.4%）→ 用本地 panel 做 Tier A 篩選/負例把關，「放水讓爛樣本混入」的風險不存在。**D3「judge 校準」可結案：放水病不存在、不需校準。** 唯一殘留風險是反向的——panel 過嚴可能誤殺 Shiba 採納的實用樣本，但對 gold 篩選（本就要嚴）無害，故不阻 D3 結案。

## Corollary（落出本診斷，超出 D3 scope、記錄不追）
若「採納於情境」≠「訓練價值」，則 `high_value` override 正把 panel 獨立分數 avg 3.4 的樣本**強制 approved 成 weight-1.0 訓練資料**（14 approved 中 13 筆如此）。這是真實的 L2/L3 資料品質隱患——進 MLX 的「approved」多數非 panel 背書、而是 Shiba 情境採納，品質尺度與訓練價值不一定對齊。屬 Layer 3 樣本品質議題，待 [[project_rejected_samples_reuse]] / 能力驗證脈絡一併評估，本次不開。

## 產物
- `scripts/judge_confusion_matrix.py`、`tests/layer2/test_judge_confusion_matrix.py`（3 passed）
- `experiments/2026-06-19_d3_confusion/{blind,oracle,verdicts}.json`（中間產物，未入版控）
