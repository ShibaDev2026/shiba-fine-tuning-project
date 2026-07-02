# 個人評測集 v1 — A vs B 定召回生死（2026-07-03）

## 判定：FAIL（無實質差異，召回不加分）

**A（qwen3:30b-a3b + CLAUDE.md）= 36/48；B（A + production 召回）= 37/48；diff = +1**，遠低於 pre-registered 門檻 +5。翻車數（B 使 2→0）= 0。依 pre-registered 規則：**「召回 > 好模型+CLAUDE.md」前提不成立**——roadmap P2 廢止決策獲實測背書。

## 設計（避開已知陷阱）

- 24 題三組：P=隱性專案知識 10（**刻意偏袒召回**的小生境）／O=專案 ops 8／G=一般開發 6。
- 題目與 key facts **先於跑分註冊**（`eval_set.json`）；題目獨立人工出、不從召回候選抽（避 golden-set cosine-bound / grader=author 舊陷阱）。
- 兩臂同 system（全域+專案 CLAUDE.md 全文）、temperature 0、同模型；B 加 `retrieve_for_eval(q, top_n=3)`（production 路徑、含 answer 欄新索引）。
- **盲評**：X/Y 隨機臂（run2 seed=43）、rubric 0/1/2、評完才解盲。判定規則 pre-registered：|diff|<5=無差異。
- 真實依賴：Ollama 由本 session 自行啟動並 health check（qwen3:30b-a3b 生成、bge-m3 召回 embedding），零 mock。

## 分組結果

| 組 | A | B | 解讀 |
|----|---|---|------|
| P 隱性專案知識（滿分 20） | 10 | 12 | 召回的主場也只 +2（見下） |
| O 專案 ops（滿分 16） | 16 | 16 | **CLAUDE.md 一項就全飽和**，召回零邊際 |
| G 一般開發（滿分 12） | 10 | 9 | 模型能力決定（G4 兩臂同錯 `--lf`） |

## 核心發現：召回給 +4、同時拿走 -3

B 的真實增益全來自召回撈到的歷史知識：**P10 +2**（reranker eval 無效的 cosine-bound 結構原因——A 臂完全答錯、B 臂命中 key facts）、**P8 +1**（從召回的鄰居 exchange 推出 `deprecated_exchange_embeddings_old`）、**P6 +1**（從召回的 gate 討論猜到 `is_short_query` 但無門檻）。

但召回雜訊同時造成退化：**P3 -1**（加了錯誤時區註解）、**P5 -1**（順著垃圾 context 幻覺出假檔名/假流程）、**G1 -1**（召回 context 觸發危險操作規則、拒答只反問確認）。淨 +1 ≈ 零。

**索引 answer 品質實measured**：召回帶回的「答案」多為收尾碎片（「跑全量。」「error」「更新 Last Session 為 RAGAS」）——印證 [[project-recall-answer-rebuild-phase1]] 已知的 answer=最後一則 assistant 訊息缺陷。就算召回命中對的 exchange，answer 欄常無資訊量。

兩臂共同天花板：P1（測試隔離 patch `shiba_db.CONFIG`）、P9（Ollama env vars，兩臂皆幻覺出不存在的變數）雙雙 0 分——**不在 CLAUDE.md 的知識，召回也救不回**（P1 明明在語料裡但沒被 surface）；P9 其實在 AGENTS.md 有（本次 system 只餵 CLAUDE.md，其 Ollama env 段 2026-06-21 外移到 memory）→ 佐證「知識放進指令檔=穩拿、指望召回=賭運氣」。

## 誠實邊界

- 判官=Claude 盲評（rubric 固定、X/Y 隨機、評完才解盲），非人工雙盲；n=24 單模型單次，偵測不了 <10% 的細微差異——但 pre-registered 門檻本來就設在「值得投工程」的量級，未達即 FAIL。
- run1 兩個 harness bug 被卡控攔下並修正：①qwen3 thinking 混入 content + 450 token 截斷（→num_predict 1200+取 `</think>` 後段）②**我的 runner 讀錯回傳 key（`contexts` vs `retrieved_contexts`）→ B 臂 24/24 靜默拿到空召回**——被「0 hits 全審計」抓到，正是 Shiba「不得假驗證」紀律的實例。run1 無效結果留 scratchpad 不作數。
- A 臂 P 組拿到 10 分部分因為近期決策已被 curate 進 CLAUDE.md（P2/P3/P4/P5/P7 都在檔內）——這不是 bias，這正是結論本身：**curation 把知識放進 context 的效率遠高於召回**。

## 對主軸的含義

1. **eval 軌首戰完成使命**：P2 廢止從「前提未證」升級為「實測 FAIL」，召回線正式結案（要翻案須先修索引 answer 品質+證明 P 組能拉開 ≥5）。
2. **curate 軌獲直接證據**：O 組 16/16 滿分全靠 CLAUDE.md；P9 反例（外移出檔就掉分）→ 高頻操作知識該進指令檔，不該指望召回。
3. 評測集可重用：`eval_set.json`+`run_eval.py`+盲評流程，之後換模型/改 CLAUDE.md 都能重跑比分。
