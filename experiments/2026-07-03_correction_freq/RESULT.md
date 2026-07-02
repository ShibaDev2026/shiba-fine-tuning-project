# 糾正頻率 probe — RESULT（2026-07-03）

## 問題

「重複糾正/偏好 ≥3（distinct sessions）」是否存在？——此母體（對 Claude 行為的指正與持久偏好）與 keystone/EV gate 證死的母體（任務指令重複）不同，且是 CLAUDE.md 的原料訊號，此前從未被量過。

## 方法（唯讀、零模型依賴）

`probe_corrections.py`：`messages` 表 `role='user'` 全量（sqlite URI `mode=ro`）→ 去噪（tag 前綴/slash/Caveat/interrupted/<16 字/skill 載入/自動化 prompt 簽章）→ 13 組糾正 pattern 高 recall 抽取 → 人工（主執行緒）逐筆語意 audit + fold。數字可重現：兩次執行輸出 diff 一致。

## 漏斗

| 階段 | 數量 |
|------|------|
| user 訊息（有文字） | 2,987 |
| 去噪後 | 896 |
| pattern 候選 | 168（54 distinct sessions） |
| audit 判 artifact | ~90（54%） |
| 真實糾正/偏好 | ~78 |

**Artifact 帳**（keystone 教訓再驗證——apparent hits 大半是 harness）：context 續傳摘要「This session is being continued…」62 筆（摘要引用 CLAUDE.md 條文的「不得/一律/必須」而誤中）；`/loop` skill echo 11；`/insights`、`/init`、`/remember`、code-review、update-config 等 skill 全文 9；貼上的 AI 建議/表格/transcript 7。

## Fold 結果（distinct-session 計數）

| 群組 | sessions | 證據（msg_id@session） | 現況 |
|------|----------|------------------------|------|
| **先討論/只給建議，不要直接動作** | **4 強**（17, 55, 170, 463）+1 弱（575） | 3801@17「先跟我討論就好不用動作」、6332@55「請先不要做任何動作只要討論」、10979@170「說明舉例但不要動作」、23113@463「只給建議不要動作」 | ✅ 已編入 CLAUDE.md（Scope Discipline + Request Modes [PLAN]/[DECIDE]，s347 有 /remember 編碼痕跡） |
| **不要浪費 token** | **3 強**（8, 449, 578）+1 相關（575 預算暫停） | 922@8「不要過冗餘於測試 會感覺你在偷我token」、22440@449「不要一直在無意義的任務上消耗token」、30738@578「避免…消耗大量token」 | ✅ 已編入（Token 使用紀律 + [[feedback-no-endless-goals]]） |
| plan/memory 衛生 | 2–3（147, 400, +370 弱） | 9992@147「**我記得…已經規範過一次**要求將plan跟目錄機制都更新在主記憶內」（教科書級重複抱怨）、20587@400「plan不可行就不需要保留 直接將結論記憶」 | ✅ 已編入（plan 擺放/完成即刪/DoD memory 同 commit） |
| 本地優先/不用付費 API | 2（463, 493） | 23156@463、25459@493 | ✅ 已編入（teacher 本地切換段） |
| 其餘（docker 來源、config 外部化、CLAUDE.md 分層、Gemini 速率、SOLID…） | 各 1 | — | ✅ 幾乎全部已有對應 feedback memory / CLAUDE.md 條目 |

## Gate 判定：PASS（訊號存在）——但捕獲迴圈已飽和

1. **存在性 PASS**：至少 2 群穩健跨 ≥3 distinct sessions（4 與 3），與任務指令母體（574 session 掃出 0）形成鮮明對比——**糾正母體確實會重複，Shiba 的「重複糾正≥3」單訊號設計正確**。
2. **但無新可收割項**：所有 freq≥2 群組**已全部**被現行人工迴圈（當場糾正 → /remember → feedback memory → CLAUDE.md）編碼完畢。逐群比對 CLAUDE.md 與 feedback_* memory，殘餘未捕獲的 freq≥3 群＝**0**。
3. **推論：不建自動偵測器**。偵測器的 EV＝殘餘未捕獲量＝0；現行迴圈自熄性運作良好（糾正重複 2–4 次即被編碼、之後停止出現）。本腳本保留作按需安全網（幾個月手動重跑一次即可，~1 分鐘）。

## 誠實邊界

- **自熄迴圈造成低估**：糾正一旦編碼進 CLAUDE.md 就停止重複，縱向計數天然低估「若無迴圈會重複幾次」——但這不影響 gate 結論（問的是「訊號存在嗎/需要建偵測嗎」，不是「真實頻率多高」）。
- Pattern recall 非完備：無否定詞的糾正（如純語氣不滿）不會被抽中；snippet 截 150 字，長訊息尾部糾正可能漏。方向性結論（存在、已飽和）對此穩健——漏抽只會多算未捕獲量，而未捕獲量已是 0。
- 去噪簽章清單為手工維護，續傳摘要 62 筆靠人工 audit 剔除而非腳本（腳本層可加 `This session is being continued` 前綴，未加以保留 audit 透明度）。

## 行動結論（餵 Task 2）

- CLAUDE.md **無新條目需要增補**（curation 結果：現有覆蓋完整）。
- 「節奏」定義：不建常設機制；本腳本留檔按需重跑。
- 附帶佐證 Task 2 的窄車道/authoring 方向：糾正→編碼迴圈是全系統唯一實證跑通的「累積→增值」路徑（對比：任務模式挖掘 0、fine-tune 0、召回前提未證）。
