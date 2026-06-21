# Harness cosine-bound probe — RESULT

- n_query = 10（active golden, seed=20260621）
- 標註者 = local-qwen 盲標（qwen/qwen3.5-35b-a3b）｜第二 embedding = snowflake-arctic-embed2
- **cosine_miss_rate = 1/14 = 7.1%**
- 判定門檻 = 25%（>25% 缺陷有後果）→ **cosine 召回足強 → B 組關閉**

| # | n_miss/n_rel | pool | query |
|---|---|---|---|
| 1 | 0/1 | 14 | 根據我們規劃的主軸方向 是偏向短期還是中期？ |
| 2 | 0/2 | 15 | 在Layer 0、Layer 1與Layer 3各別使用了什麼模型？ |
| 3 | 1/1 | 15 | 無法顯示表格資料 |
| 4 | 0/2 | 12 | 前端路由部分我該如何進行測試與確認 |
| 5 | 0/2 | 9 | 我在測試前端路由時，反覆切換 Ollama 的上下線狀態幾下，結果後端直接當機了。 |
| 6 | 0/0 | 18 | 先行保存方案，目前不作異動。 |
| 7 | 0/2 | 14 | Let git .idea/ into ignore |
| 8 | 0/1 | 12 | 無法存取localhsot:8890 |
| 9 | 0/2 | 10 | 評估該案子的所有執行企劃，確認是否應做內容精簡，接著歸檔整理來更新系統記憶 |
| 10 | 0/1 | 19 | 麻煩你協助進行這項作業 |

## 每 query cosine 漏掉的 relevant session

- #3 `無法顯示表格資料` → 漏 ['8a48dbf7...'']（該 session 實為「檢查 plan 精簡」，cross-topic 牽強）

## 解讀與限制（誠實切窄）

### 核心證據＝pool broadened 後 miss 反而下降（非 floor artifact）
| run | lexical 源 | union pool | cosine_miss_rate |
|-----|-----------|-----------|------------------|
| 1 | sessions_fts（餓死 \|fts\|=0） | 4–12（小） | 2/16 = 12.5% |
| 2 | char-bigram over instruction | **9–19（健康）** | **1/14 = 7.1%** |

run2 的 lexical 每 query 帶進 **4–13 個 cosine 外候選**（audit: lex_outside_cos），但盲標 qwen 幾乎全判不 relevant → **擴大候選池反而讓 miss 下降**。這排除了「pool 小是因擴展源餓死、12.5% 是 floor」的不利讀法（最初的關鍵盲點）：cosine top-15 確實涵蓋了幾乎所有真 relevant。

### 所有 surviving miss 皆 cross-topic 噪音
- run2 唯一 miss #3「無法顯示表格資料」→ 漏「檢查 plan 精簡」（語意弱關聯）
- run1 的 #1「規劃主軸短期/中期」→ 漏「四份論文值得參考」、#7「git .idea ignore」→ 漏「git log -10」
- 三個 miss-instance 全是 qwen 寬鬆標註的牽強 relevance → **7.1% 已高估真語意 gap**。

### 殘餘限制（語意維度）＋ 為何結論仍成立
- lexical 修好補的是 **lexical 維度**；但 B 組關切是**語意召回**（reranker / 新 embedding），該維度仍只靠 arctic 一個 dense model（arc_outside_cos 僅 0–4/query）→ probe 無法完全分辨「cosine 抓全語意 relevant」vs「兩個 dense embedding 共享盲點」。
- **救援＝probe × reranker PoC 雙角度收斂**：reranker PoC 已用強 cross-encoder（bge-reranker-v2-m3）獨立測語意維度、找到**零增益**；本 probe 從召回涵蓋角度得**同結論**。兩個獨立方法收斂於「cosine/bge-m3 在此 domain 已足強」= 最強論點。
- n=30 不需：7.1% 遠離 spec 的 20–25% 擴測邊界，且方向跨兩個**不同** pool 穩定。

## 結論

cosine-bound golden set 大致**良性**、bge-m3 召回足強 → **B 組（no-regret）關閉**，Shiba「接受 bge-m3 現狀」決策被 **probe × reranker PoC 雙角度證實**。reranker / 新召回法在當前 domain EV 不成立；harness 大修 ROI 不存在。
