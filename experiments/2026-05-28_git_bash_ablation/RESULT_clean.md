# 誠實能力重跑 — 乾淨子集 RESULT（取代污染版 13%/n=6）

> 樣本：`clean_samples.csv` n=30，從 5,733 筆「乾淨 exchange」（不受 `branch_messages.seq` 退化污染）
> 蒸餾過濾出的**真指令請求**（qwen3:30b 保守判 + gold 去重，30 unique）。
> 三層 config 同 ablation（A 基線 / B reframe+JSON / C +grounding），常數 think:false / temp 0.7 / num_ctx 8192。
> 判準：「我會不會原樣執行以完成該請求」（labels_clean.csv，第一輪由 Claude 初判，邊界案例見下）。

## 採納率（乾淨 n=30）

| Config | 疊加 | 採納/30 | 採納率 |
|---|---|---|---|
| A 基線 | production 複刻 | 0/30 | **0%** |
| B +reframe | 指令生成器+JSON | 4/30 | **13.3%** |
| C +grounding | +當下 git 環境 | 4/30 | **13.3%** |

Δ 分解：A→B **+13.3%**；B→C **+0%（grounding 零淨貢獻，且引入新失效）**。

## 與先前數字對照（為什麼這版才算數）

| 版本 | n | A | B | C | 效度 |
|---|---|---|---|---|---|
| ablation 原始（污染） | 30 | 0% | 10% | 13% | ❌ 分母含 24 筆非指令請求 |
| ablation 手取乾淨子集 | 6 | 0% | 50% | 67% | ⚠ n 太小、子集自污染樣本挑出、上偏 |
| **本次乾淨重跑** | **30** | **0%** | **13.3%** | **13.3%** | ✅ 獨立乾淨抽樣 + 蒸餾過濾 + 去重 |

→ **n=6 的 50–67% 是上偏假象**。獨立乾淨 n=30 上，真指令請求的採納率僅 ~13%，遠低於 70% 目標。

## 三個決定性發現

### 1. C 的 grounding 不是雙面刃，是淨負
13/30（43%）落入 `grounding_poison`：模型把注入的「當下 git status 未追蹤檔」（`*.db.bak` / `docs/note/` …）**原樣吐成 `git add <那些檔>`**，完全無視使用者真正的請求（grep / pytest / 啟服務 …）。B→C 採納率 +0%，卻新增 43% 的危險輸出（含 #12 `git reset --hard` / `git clean -fd`）。**grounding 無 intent-gating 時主動有害**，此版量化坐實 ablation 的定性警告。

### 2. 「成功」幾乎都是 RAG 逐字複製，不是生成
4 筆採納中 3 筆（#8 `git stash`、#9 `git log --oneline -5`、#23 `powermetrics … smc … grep temp`）與 gold **逐字相同** —— vector 召回 30/30 命中，模型是把召回到的前次指令**抄出來**，不是生成。唯一「生成型」成功是 #7（切 4 個 PR 分支，通用樣板）。
→ 價值不在「Qwen 生成指令」，而在「RAG 召回到近乎相同的前次指令」。這是**遠比『Qwen 接手 git/bash』狹窄**的命題。

### 3. B 的主失效是 git 樣板幻覺
13/30 `hallucination`：SYSTEM_B 強迫輸出指令，模型對非 git 請求（brew/grep/pytest/啟服務）一律退化成 `git add/commit/push` 樣板。format escape hatch（空 commands）只在 2 筆觸發 → 逃生口不足以止血。

## failure_mode 分布

| failure_mode | B | C |
|---|---|---|
| ok（採納） | 4 | 4 |
| hallucination | 13 | 0 |
| wrong_command | 9 | 11 |
| grounding_poison | 0 | 13 |
| placeholder_unfilled | 1 | 1 |
| format_error | 1 | 0 |
| empty | 2 | 1 |

## 邊界案例（待 Shiba 覆核，可能 ±1）
- **#7**（判採納）：請求「執行 4 個 PR 切分支」→ B/C 給 4× `git checkout -b`。算字面達成，但實務上一次切 4 分支非常見工作流。若判否 → B/C 各降至 3/30 = 10%。
- **#3**（判否）：請求「啟動名為 shiba-ollama-grafana 的容器」→ B 給 `docker run --name shiba-ollama-grafana grafana/grafana-enterprise`（可執行、命名對，但非使用者真實的 compose stack，會起出流氓容器）。若放寬「可執行即可」→ B 升至 5/30 = 17%。

## 依決策樹的結論

C 採納率 13.3% **<< 70%** → 決策樹判定：**base 能力差距 fine-tune 救不了，砍 Layer 0/2/3，留 Layer 1 + RAGAS**。

更強的解讀（覆蓋單純決策樹）：
1. **零成本方法論（reframe/grounding）救不了 base**：A→B 靠 reframe 從 0% 拉到 13% 是「格式可執行化」，但天花板就壓在 ~13%；grounding 零貢獻且有害。
2. **真正起作用的是 RAG 召回，不是模型能力**：成功＝抄到前次近乎相同指令。這指向**純檢索式輔助**（召回前次指令供人確認執行，不生成）才是有效形態，而非生成式接管。
3. **冷卻期 buffer 假設大幅減弱**：可交棒量 = 機械指令(~20% 語料) × 近乎重複可被召回命中的比例（這 13% 裡多數），交集很小。Layer 0/2/3 投資不划算。

## 後續（待 Shiba 拍板）
- [ ] 覆核 #7 / #3 兩個邊界，定終值（不影響 << 70% 的結論）。
- [ ] 依此更新 memory `project_capability_upper_bound_validation.md`：實測=乾淨 n=30 → 13%（非 50–67%）+ 成功多為 RAG copy + grounding 淨負。
- [ ] Layer 0/2/3 處置決定（建議：砍生成式接管，保留 Layer 1 RAG + 純檢索輔助形態 + RAGAS）。
- [ ] 上游 root cause（`branch_messages.seq` 退化，82% branch）獨立記錄 → Phase B（gated，非本實驗範圍）。
- [ ] 驗證完刪 plan 檔 `~/.claude/plans/sorted-watching-origami.md`。
