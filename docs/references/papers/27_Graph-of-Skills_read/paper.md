# Graph-of-Skills: Dependency-Aware Structural Retrieval for Massive Agent Skills

> arXiv: https://arxiv.org/abs/2604.05333 ｜ html: https://arxiv.org/html/2604.05333
> 作者: Dawei Liu, Zongxia Li, Hongyang Du, Xiyang Wu, Shihang Gui, Yongbei Kuang, Lichao Sun｜ 2026-04（v3 2026-05）
> ⚠ 後截止日論文（2026-04），本分析以 arxiv 全文內容為準。

## 關鍵詞
skill dependency graph, reverse-aware Personalized PageRank, hybrid semantic-lexical seeding, budgeted hydration, prerequisite recovery, context budget

## 對應 Layer / Roadmap 階段
- **Roadmap P1（Pattern Library）靶心** — GoS 把「大量 agent 技能 + 前後置依賴」組織成可檢索的 typed 圖,**幾乎是本專案 Pattern Library 的工程藍圖**：召回一個指令模式時連同其前置（prerequisite）一起拉出，且按 context 預算截斷。

## 核心結論（帶實證數字）
1. **依賴感知圖檢索贏過向量/全載基線**（SkillsBench 1000 技能 + ALFWorld，三模型 Claude Sonnet 4.5 / MiniMax M2.7 / GPT-5.2 Codex）：
   - GPT-5.2 Codex on SkillsBench：reward **+25.55%**、token **−56.72%** vs 全量載入基線。
   - 六個 model×benchmark 區塊**全部**平均 reward 最高；SkillsBench +10.97 / ALFWorld +2.87 vs Vector Skills。
2. **規模化保持優勢**：1000 技能時 GoS 34.4% reward vs Vanilla 27.4% / Vector 21.5%；2000 技能仍領先。

## 方法機制拆解
### 離線建圖
- typed directed graph，每節點 = 正規化可執行技能記錄；四種邊：**dependency / workflow / semantic / alternative**。
- dependency 邊「當 I/O schema 重疊超固定閾值時 deterministic 加入」；其餘三種用「sparse LLM validation」避免 O(N²)。
### 線上三階段檢索
1. **Hybrid Seeding**：`z_i(q) = η·s_sem(q) + (1−η)·s_lex(q)`（語意+詞彙融合，呼應 [[paper-19]] CC 融合）。
2. **Reverse-Aware Graph Diffusion**：Personalized PageRank + type-specific 反向邊（dependency 權重最大、alternative 最小）→ 從命中種子**回溯補出前置技能**。
3. **Budgeted Hydration**：用 graph score + query↔技能欄位（name/capability/artifacts/entrypoints）直接匹配重排，截到 context 預算。

## 速查（綁本專案具體設計決策）
| GoS 機制 | 本專案落地 |
|---|---|
| **技能依賴圖 + 前置回溯** | Pattern Library 不只存扁平模式，存模式間依賴（如「git rebase 前須 stash」）；召回主模式時連帶拉前置——直接對應本專案 CLAUDE.md「切 branch 前必先 stash」這類前後置規則。 |
| **I/O schema 重疊 deterministic 建 dependency 邊** | 指令模式的「前一步輸出=後一步輸入」可 deterministic 連邊，省 LLM 成本。 |
| **budgeted hydration（context 預算截斷）** | 直接解本專案「擴 top-k 爆 context」兩難（呼應 RankRAG N→k [[paper-17]]）。 |
| **hybrid seeding（sem+lex）** | 與 bge-m3 dense + sparse（修壞掉 FTS5 arm [[paper-12]]）+ CC 融合 [[paper-19]] 完全一致的方向。 |

## 侷限 / 與本專案差異
1. **圖品質依賴技能文件品質**：文件差→邊品質差。本專案蒸餾模式須描述清楚（呼應 AWM 的 NL description [[paper-05]]）。
2. **★圖是離線建、不從執行軌跡/使用者回饋更新**：這正是本專案 **manual-accept 飛輪要補的**（GoS 缺 evolving，本專案 Shiba 採納可動態更新圖）。
3. 只測 SkillsBench/ALFWorld，未測 web/multimodal；本專案 CLI 場景需自驗。
