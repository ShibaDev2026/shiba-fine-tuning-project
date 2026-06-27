# VeriGuard: Enhancing LLM Agent Safety via Verified Code Generation

> arXiv: https://arxiv.org/abs/2510.05156
> 作者: Lesly Miculicich, Mihir Parmar, Hamid Palangi, Krishnamurthy Dj Dvijotham, Mirko Montanari, Tomas Pfister, Long T. Le（Google）｜ 2025-10
> ⚠ 後截止日論文（2025-10），本分析以 arxiv 全文內容為準。

## 關鍵詞
propose-check-execute, formal verification, Nagini, Hoare triple, offline policy generation, online runtime monitor, agent safety, ASR/TSR

## 對應 Layer / Roadmap 階段
- **Roadmap P3（Verifier）最直接藍本** — VeriGuard 的「離線生成+驗證 policy / 線上逐動作攔截檢查」就是本專案 Verifier（propose-check-execute 安全閘）的完整工程範式。本專案 L2 chamber 轉 Verifier 的設計可直接對標。

## 核心結論（帶實證數字）
1. **安全攻擊成功率（ASR）壓到 0、且維持任務成功率（TSR）**（Agent Security Bench）：
   - Claude-Sonnet-4：ASR **51.9%→0.0%**、TSR **85.1%**；GPT-4.1：63.7%→0.0%、TSR 57.1%。
2. **EICU-AC**：Accuracy/Precision/Recall **全 100%**（GPT-4o）；**Mind2Web-SC**：95.1–97.2% Acc。
3. **ablation**：純 Policy Generation 已把 ASR 53.5%→9.97%;完整管線→0%、TSR 51.87%→63.25%。
4. **勝過純 LLM 護欄**：GuardRail ASR 也 0% 但 TSR 僅 40.2%（過度阻擋）;VeriGuard 在安全-效用權衡上最佳——**直接對應本專案「擋危險但不過度阻擋」的 gate**。

## 方法機制拆解
### 離線階段（Policy 生成+驗證）
- 從自然語言安全需求 + agent spec 合成 policy function 與形式約束。
- 三步精煉：① Validation（解使用者意圖↔形式表示的歧義）② Code Testing（生成單元測試驗功能）③ **Formal Verification**（用 **Nagini** 驗證器,基於 Viper,以 Hoare triple `{Cpre} p {Cpost}` 數學證明 policy 合規）。
### 線上階段（Runtime Monitor）
- 驗證過的 policy 當 runtime monitor,**在執行前攔截 agent 動作**。
- 偵測違規時用五策略之一：Task Termination / Action Blocking / Tool Execution Halt / Collaborative Re-planning / 混合 CRP+TEH（混合策略 ASR 0.1%/TSR 63.6% 最平衡）。

## 速查（綁本專案具體設計決策）
| VeriGuard 機制 | 本專案落地 |
|---|---|
| **離線生成 policy + 線上攔截** | Verifier 架構藍本：把本專案 CLAUDE.md 的「危險操作確認規則」（rm/push main/reset --hard…）**編成可驗證 policy**,而非散落 prompt 規則。 |
| **執行前攔截、agent 無法繞過** | 本專案 Verifier 必須在「本地模型提案的指令」執行前攔（propose→**check**→execute）;呼應 AWM 教訓（召回的 pattern 是提案非保證 [[paper-05]]）。 |
| **五種違規策略** | 對應本專案分級回應：危險指令→Action Blocking;不確定→Collaborative Re-planning（回退 Claude 協作）。 |
| **GuardRail 過度阻擋（TSR 40.2%）的反例** | 本專案 gate「不過度阻擋」的量化警示——Verifier 設計要測 TSR 不只測 ASR。 |
| **formal verification（Nagini）** | ⚠ 重型;本專案初期可用規則+本地裁判的輕量版,formal 驗證留 P3 後期高危指令子集。 |

## 侷限 / 與本專案差異
1. **能力受限於 Nagini 驗證器**：grammar 有限、複雜屬性表達受限;LLM 生成約束需人工驗證（非確定性易錯）。
2. **跨語言擴展非平凡**:本專案指令是 bash/git/python 混合,formal spec 化成本高 → 初期不照搬 formal verification,先用 policy 規則 + 攔截框架。
3. **對需深層推理的攻擊不足**:hybrid LLM+確定性架構有上限。
4. domain:agent 工具呼叫安全;本專案高度契合（CLI agent 執行 bash/git 正是高危動作）。
