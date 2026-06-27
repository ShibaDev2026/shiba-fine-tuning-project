# Towards Verifiably Safe Tool Use for LLM Agents

> arXiv: https://arxiv.org/abs/2601.08012 ｜ ICSE NIER 2026
> 作者: Aarya Doshi, Yining Hong, Congying Xu, Eunsuk Kang, Alexandros Kapravelos, Christian Kästner｜ 2026-01
> ⚠ 後截止日論文（2026-01），本分析以 arxiv 全文內容為準。

## 關鍵詞
STPA hazard analysis, capability labels, MCP extension, blocklist/mustlist/allowlist/confirmation, Alloy formal modeling, tool-call sequence safety

## 對應 Layer / Roadmap 階段
- **Roadmap P3（Verifier）** — 提供「工具呼叫序列安全規格」的方法論層（VeriGuard [[paper-14]] 是執行框架,本篇是**如何系統性導出該擋什麼**）。其四層 enforcement 幾乎是本專案 CLAUDE.md「危險操作確認規則」的形式化版本。

## 核心結論（帶實證數字）
> ⚠ 本篇是 NIER（New Ideas / 初步成果）,**無實證評估數字**,僅用 Alloy 形式建模證明「不安全流被消除、安全流仍可行」的可行性。價值在方法論與規格框架,非 benchmark。

1. 用 **STPA**（System-Theoretic Process Analysis）系統性導出 agent hazard：找 stakeholder → 期望值 → 反轉成潛在損失 → 分析致損行為 → 導出安全需求。
2. 擴展 **MCP**（Model Context Protocol）加結構化標籤三維度：Capabilities（read-only/write/execute…）、Data Confidentiality（是否敏感）、Trust Level（輸出是否可信）。
3. 四層 enforcement：**Blocklist**（自動拒）/ **Mustlist**（強制要求某流程）/ **Allowlist**（安全流免確認）/ **Confirmation**（模糊動作要使用者確認）。

## 方法機制拆解
- **工具邊界攔截器**:每個工具呼叫執行前被攔截評估,agent 無法繞過（與 VeriGuard 線上階段同理）。
- **Alloy 窮舉驗證**:用形式建模語言證明不安全流（如「私密資料流入 send_email」）被擋,安全 trace 仍保留。
- 範例規格:「private data 不得流入 send_email」(blocklist);「每次 update_event 後須對每位與會者各呼叫一次 send_email」(mustlist)。

## 速查（綁本專案具體設計決策）
| 本篇機制 | 本專案落地 |
|---|---|
| **capability labels（read-only/write/execute）** | 給本專案工具/指令打標：`git status`=read-only 免確認;`rm`/`git reset --hard`=execute+destructive→Confirmation;對應 CLAUDE.md 危險操作清單。 |
| **四層 enforcement** | **直接形式化本專案 CLAUDE.md 危險規則**:Allowlist=自動執行的安全指令;Confirmation=rm/push main/覆蓋非暫存檔;Blocklist=洩漏 Key/IP/個資的動作（秘密規範）。 |
| **STPA 導出 hazard** | 系統性盤點本專案 agent 該擋什麼,而非臨時加規則——補 Verifier 設計的完備性。 |
| **Data Confidentiality 標籤** | 對應本專案「不得輸出 Key/token/本地 IP/個資」——把秘密規範升級為可機器檢查的 confidentiality 標籤。 |

## 侷限 / 與本專案差異
1. **無實證、僅初步形式建模**:採用時須自行補評估。
2. **需開發者手動指派 MCP 標籤**:本專案工具集有限,手動打標可行（成本低）。
3. **針對 task-specific agent;通用 agent 難保證**:本專案是 CLI/code agent（半通用）,標籤覆蓋需謹慎。
4. 與 VeriGuard 互補:本篇給「規格框架（該擋什麼）」,VeriGuard 給「驗證+攔截引擎（怎麼擋）」——本專案 Verifier 可取兩者:用本篇方法導出規則、用 VeriGuard 式攔截器執行。
