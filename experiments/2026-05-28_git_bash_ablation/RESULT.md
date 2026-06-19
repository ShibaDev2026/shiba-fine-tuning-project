# Local Qwen 能力上限驗證 — RESULT

> 實驗：git+bash 30 樣本 × 3 config ablation；標註判準「我會不會原樣執行」。
> **常數**：think:false / temp 0.7 / num_ctx 8192 / RAG 三層共用。temp 0.7 單樣本有變異（limitation）。

## 採納率

| Config | 疊加 | 採納/有效 | 採納率 |
|---|---|---|---|
| A 基線 | production 複刻 | 0/30 | 0% |
| B +reframe | 指令生成器+JSON | 3/30 | 10% |
| C +grounding | +當下 git 環境 | 4/30 | 13% |

## Δ 分解（哪個方法論值得保留）

- A→B（角色/格式 reframe）：**+10%**
- B→C（grounding）：**+3%**
- 總提升 A→C：**+13%**

## failure_mode 分布

| failure_mode | A | B | C |
|---|---|---|---|
| hallucination | 0 | 2 | 1 |
| ok | 0 | 3 | 4 |
| role_confusion | 30 | 0 | 0 |
| wrong_command | 0 | 25 | 25 |

## ⚠ 標註者效度警告（最重要，先讀這段）

機械決策樹依 C=13% 判「砍 Layer 0/2/3」，但 **13% 不是 base 能力的乾淨量測**——分母被污染。實標時發現 `sample.py` 的 `is_real_request` 過濾太鬆，30 筆中只有 **6 筆是真正的「執行某指令」請求**，其餘 24 筆是：

| 類別 | 樣本 | 數 |
|---|---|---|
| 概念/分析問題 | #4 #7 #11 #16 #19 #21 #25 #26 #30 | 9 |
| 規劃請求 | #2 #6 #17 #24 | 4 |
| 雜訊（task-notification / skill 文件 / 對話 summary） | #12 #13 #15 #22 #23 #27 | 6 |
| 狀態查詢 | #3 #20 | 2 |
| meta/工作流程 | #10 #28 #29 | 3 |

B/C 的 system prompt 強制輸出 `{"commands":[...]}`，模型**無法回「這不是指令請求」**，於是把概念問題硬塞成指令 → 大量 `wrong_command` 是「題目就不該出」造成的，不是 base 能力差。

## 乾淨子集重算（只取 6 筆真指令請求 #1 #5 #8 #9 #14 #18）

| Config | 採納/有效 | 採納率 |
|---|---|---|
| A | 0/6 | 0% |
| B | 3/6 | **50%** |
| C | 4/6 | **67%** |

n=6 變異極大、**不足以下結論**，但已顯示：原始 13% 嚴重低估真指令上的能力。乾淨子集 ≈50–67%（低於 70% 目標但非 13% 的災難）。

## 修正後決策（覆蓋機械決策樹）

1. **不採信 13% 為能力天花板**——量測無效（抽樣污染）。任何 Layer 0/2/3 的砍/留決定前，須以**乾淨指令樣本（n≥30 真指令請求）重跑**。
2. **Config A 結論成立且乾淨**：production Layer 0 system prompt（「你是 Shiba 的本地助理…簡潔回答」）結構上**無法產出可執行指令**（0/30 全中文敘述）。這是 config 問題、可零成本修，不是 base 能力問題。
3. **Config C grounding 雙面刃**：對「指定檔案」任務有幫助（#5），但對非指令請求**主動有害**——傾印全部 untracked、甚至 `git rm`／提交使用者待決去留的檔（#10 #21，危險）。grounding 必須配 intent-gating，否則風險>收益。
4. **更強的策略發現**：抽樣顯示真實 Claude 對話語料中**機械指令占比僅約 20%**，其餘 80% 是推理/規劃/概念——這部分**正面挑戰「Claude 做大量重複 git/bash 可交給 Qwen 緩衝」的前提**。冷卻期 buffer 的可交棒量可能比假設小，須重估 Layer 0/2/3 的投資是否值得。

## 後續
- **重跑乾淨樣本**：收緊 `is_real_request`（排除概念問題/規劃/skill 文件/task-notification），抽 n≥30 真指令請求再測，才有資格下 Layer 0/2/3 決定
- B/C system prompt 加「非指令請求時回空 commands」逃生口，避免硬塞
- 更新 memory [[capability-upper-bound-validation]]：實測=量測無效+乾淨子集 50–67%（非定論）+語料機械指令占比 ~20%
- 刪除 plan 檔 `~/.claude/plans/sorted-watching-origami.md`（CLAUDE.md：驗證完即刪）— **建議待乾淨重跑後再刪**