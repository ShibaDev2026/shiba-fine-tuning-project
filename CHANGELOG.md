# Changelog

所有版本變更依照 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 格式記錄。
版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## [Unreleased]

### Added

- **B 組瓶頸 no-regret 結案：harness cosine-bound probe（2026-06-21）** — 判定 cosine(bge-m3) 召回是否真漏 relevant，證實 bge-m3 在此 domain 足強、reranker/新召回 EV 不成立、不修 golden set：
  - **`experiments/2026-06-21_harness_cosine_bound_probe/probe.py`**（唯讀 DB、不碰 production）：10 active golden、union pool = cosine top-15 ∪ char-bigram lexical top-50 ∪ arctic-embed2 top-15（第二正交 embedding）、local-qwen 盲標（遮 source/score + 洗牌 + LOO 剔自身），數 cosine top-15 漏掉的 relevant。全本地零 API（bge-m3 + arctic via ollama、qwen3.5-35b via LM Studio）。
  - **結果**：pool broadened 後 miss **反降**（lexical 餓死 pool4-12→12.5% → char-bigram pool9-19→7.1%）→ 非 floor、cosine 真涵蓋 relevant；3 miss 全 cross-topic 牽強。probe(涵蓋角度) × reranker PoC(排序角度，零增益) 雙角度收斂。結論見 `RESULT.md`。
- **Layer 1 RAG 召回稽核日誌 + macOS 通知（2026-06-21）** — 在 `feed_model=false`（召回不餵 Claude）下，給 Shiba 一份可稽核的「共現紀錄」+ 即時提醒：
  - **每日 append 日誌 `recall_logs/<yyyyMMdd>.txt`（log4j 風格）** — 有召回（`mem_count>0`，Layer 0 router 草擬不算）才寫：`UserPromptSubmit` hook append「`[毫秒時間戳][INFO][session][問題]` + 召回原因（vector 標 cosine `score=`、FTS5 標 `fts5#rank`）」；`Stop` hook 補「Claude 回答（完整保留、僅 scrub、不截斷）」+ `feed_model=false` 共現註記。**共現非因果**（召回未餵 Claude、回答未受其影響，僅並列供比對）。日檔由 append 當下日期決定、跨日自動換檔；`recall_log_retention_days`（預設 30）於 append 時順手刪超期日檔（解析檔名日期）。`recall_logs/` 入 `.gitignore`。
  - **跨 hook 配對（pending 標記）** — cause 寫入時建 `recall_logs/.pending_<sid8>`（內容=日檔路徑，解跨午夜 answer 落不同檔）；`Stop` hook 有 pending 才從 transcript 取最後 assistant 回答補入、清標記。`_append_recall_answer` 置於 `sync_session` 的 `finally`，sync 失敗仍補、不冒泡。
  - **macOS 桌面通知（方案 A，osascript）** — 有召回才發；標題 `yyyy/MM/dd HH:mm RAG 召回次數:N次`、內文＝議題（問題截 40 字）。`lib/notify.py` side-effect only、無 osascript/失敗回 False 不冒泡。首次需系統設定允許 Script Editor 通知。
  - **`rag.py` OCP 加法擴充** — 抽 `_retrieve()` 回 `(ctx, source, hits)`；`get_rag_context` 簽章不變（向後相容、既有 caller/測試零改），新增 `get_rag_context_with_hits()` 供 hook 取結構化 hits 記「召回原因」。
  - **rag_echo.md 寫入條件改「有召回才寫；無召回覆寫 `rag_count=0`」** — 維持 statusLine 即時歸零（無召回時不殘留上一筆計數）。
  - **新模組**：`layer_1_memory/lib/recall_log.py`（日檔 append/pending/prune，scrub 以 callable 注入＝DIP、不依賴 layer_2）、`layer_1_memory/lib/notify.py`。config 開關 `recall_log` / `recall_log_dir` / `recall_log_retention_days` / `notify_macos`。
  - **驗收**：新測 16 passed；全量 `tests/ -q` **218 passed**（4 pre-existing fail：3 `test_db` + 1 layer3 `trigger_policy`，皆與本次無關、隔離跑亦失敗且不引用本功能模組）；真實 DB smoke 三路徑通過（召回→日檔+score+pending+rag_echo+通知／無召回→rag_echo 歸零／Stop→完整回答補入+pending 清除）。

### Changed

- **Layer 1 RAG 注入透明化：top-k 改為「使用者參考、不餵 Claude」（2026-06-20，可回滾）** — 解決可見性不對稱（Claude 看得到 UserPromptSubmit 注入的 top-k + Layer 0 router 草擬答案、Shiba 看不到 → 無法分辨 Claude 結論 vs 夾雜的本地建議）：
  - **`feed_model` 旗標（新增，預設 false）** — `session_start_hook.py` 依此決定 stdout：false=本地召回 + router 草擬結果**不**注入 model context（stdout 輸出空物件 `{}`），改只走使用者寫檔通道；true=回復舊行為（注入 `additionalContext`，Layer 0 本地接管才生效）。可回滾旁路；route() 仍呼叫故 router_decisions telemetry 不受影響。
  - **使用者通道＝寫檔（取代 stderr）** — 原 `debug_echo`→stderr ANSI 區塊改為 `echo_to_file: true` + `echo_file: .remember/rag_echo.md`：hook 每次 prompt **覆寫**該檔（首行 `<!-- rag_count=N source ts -->` metadata + 人類可讀區塊），Shiba 側邊 `tail -F` 跟看完整 top-k。**改因**：查證官方 hooks 文件，**Claude Code 2.x 起 exit-0 hook 的 stderr 只進 debug log、正常 UI 與 transcript 皆不顯示**（實測 111 字元吐 stderr Shiba 全程看不到）→ stderr 通道對使用者已死，改寫檔不依賴 Claude Code UI、跨改版穩定。`.remember/.gitignore=*` 不入版控。
  - **自建 statusLine 指示燈** — 新增 `layer_1_memory/hooks/statusline_rag.sh`（model / 📁 dir / ⎇ branch / 🧠 RAG:N，N 讀 echo 檔首行 rag_count），掛專案 `.claude/settings.local.json` override（僅本專案、git-ignored、以 `bash <path>` 啟動免 chmod +x）。⚠ 過程發現原全域 statusLine 指的 **claude-hud 已被卸**（`~/.claude/plugins/claude-hud` 只剩 cache、無 dist/index.js、enabledPlugins 未列）→ Shiba HUD 早已空白（疑 plugin 系統改版所致），故自建不依賴它。
  - **寫檔前 scrub（fail-closed）** — 重用 `grading_harness.scrub_for_export`（IP/email/OS user handle 脫敏）；scrub 不可用則跳過寫檔不外洩原文。⚠ key/token 不在 scrub 範圍（沿用既有 export PII bar），echo 檔在 .remember/ 僅單機自用、要更嚴設 `echo_to_file: false`。
  - **`grading_harness.py`：`teacher_service` import 改 function-local** — 讓 Layer 1 hook 能輕量重用 `scrub_for_export`（每則訊息都跑、import 須輕），避免 PII regex 兩份漂移。
- **Layer 2 評分裁判：付費 API → 本地 LM Studio 硬切換（2026-06-16，可回滾）** — 自主性／去外部依賴；接受裁判品質些微下降換取完全本地化（L2 屬實驗平台，D1 已決）：
  - **切換**：`setup_teachers.py --cutover` 將 Gemini Flash / Flash-Lite / Claude Sonnet 4.6 設 `is_active=0`（保留 row 可一鍵回滾），新增 5 本地裁判（`keychain_ref=NULL`、`api_base=http://localhost:1234/v1`）：active 三家族 Qwen3.5-35B-A3B（`local-qwen`）+ GLM-4.7-Flash（`local-glm`）+ Gemma-4-e4b（`local-gemma`），bench 2 個（Qwen3.5-9B / GLM-4.6v-Flash）。三家族 vendor 標記滿足 `multi_judge` ≥2 vendor early-exit。回滾 snapshot：`data/teachers_snapshot_pre_cutover_*.json`。
  - **⚠ thinking 控制機制修正（實機證偽原設計）**：原 spec 的 `/no_think` prompt 注入對實際 GGUF（qwen3.5-35b-a3b / glm-4.7-flash via LM Studio）**完全無效**（reasoning_tokens 燒滿、content 空）；`chat_template_kwargs.enable_thinking` 同樣無效。**唯一有效機制 = OpenAI API 參數 `reasoning_effort:"none"`**（rtok→0、直接吐乾淨 JSON），僅 qwen/glm 帶；gemma 不帶（帶了反而碎念），走 `reasoning_content` 分流需 `max_tokens=2048` headroom。
  - **運維**：評分前需 `lms server start --port 1234`；裁判 JIT 循序載入不常駐（co-resident 因 LM Studio 記憶體 guardrail 在 64GB 上被阻擋，三裁判 ≈50GiB）。

### Fixed

- **Layer 1 RAG 查詢側同意詞前置 gate + `build_rag_query` fallback bug（2026-06-21）** — 起因：使用者輸入「不用」(2 字) 被 `build_rag_query` 的 `>= 3` 長度門檻擋下 → 掉進「專案名 fallback」→ query 變 `shiba-fine-tuning-project` → 拿專案名亂查 FTS5、召回無關結果 + recall_log「問題」失真記成專案名：
  - **Component 2（修 fallback bug，無條件解掉回報案例）**：`build_rag_query` 改為「只要 payload 有 `prompt` 欄位（UserPromptSubmit）就一律用真實 prompt」（移除長度門檻），只有**無 `prompt` 欄位**的其他 hook（PreToolUse 等）才走專案名 fallback。連帶修好 recall_log 失真（query == 真實 prompt）。
  - **Component 1（查詢側前置 gate，資料驅動「累積後再學」）**：新增 `rag.py:is_low_signal_query()`——拿正規化 query 精確比對 `exchange_embeddings.instruction`，若該 instruction 歷史衍生 `count(DISTINCT commands) >= 3`（無指向性，如「好/ok/繼續」或 slash-command 雜訊）即判定同意詞 → hook 最前面攔一刀：vector / FTS5 兩路都不走、不寫 recall_log、不彈通知。**沿用 `_vector_search` 結果側既有發散閾值 3**（同一原則查詢側對應）；走 SQLite 不依賴 Ollama、離線有效；新詞/發散未達閾值 → 照常召回（Shiba 決策：可接受新詞前幾次漏、不上模型零延遲）。任何 `sqlite3.Error` 一律 fail-open 回 False（不誤殺正常查詢）。
  - **範圍**：只做查詢側 + 修 bug，不碰寫入端 ingestion、不建 vocab 表（既有發散過濾器已在結果側排除同意詞、ingestion 再擋為冗餘）。⚠ 附帶揪出 out-of-scope 資料品質債：`exchange_embeddings.instruction` 混入大量非使用者輸入雜訊（slash command / `[Request interrupted]` / `<local-command-stdout>` / skill 全文）——stop_hook ingestion 清洗缺陷，未在本次處理（對 gate 反為好事，這些 div≥3 一併被攔）。
  - **驗收**：新測 4 passed（`is_low_signal_query` True/False + `build_rag_query` 短 prompt/無欄位 fallback）；`tests/memory/` 45 passed（3 pre-existing `test_db` fail 與本次無關、為既有 `lib.db.get_db_path` patch 對 `shiba_db` 無效之隔離弱點）；真實 DB smoke：「不用」→ source=none/hits=0 → 不寫日檔（3188→3188）、不通知（最佳結果，回報案例完全解決）；「go」→ gate→`{}`；實質問題 → 照常召回。
- **RAGAS 評估修復：feature 未初始化 + uuid 指標 over-count（2026-06-19）** — RAGAS runner 跑不動的兩個根因（+附帶一個）：
  - **Bug 1（feature 未初始化，非「讀錯表名」）**：PR-O 模組化把 ragas code 改用 `ragas_` 前綴表 + `feature_registry`，但 `apply_features` **從未接線到啟動流程**（`feature_registry.py` 自注「尚未接線」）→ `ragas_` 表從沒建、`migrate_legacy` 從沒跑、舊資料滯留無前綴舊表（`retrieval_golden_set` 111 / `evaluation_results` 909），runner 查 `ragas_retrieval_golden_set` 查無此表。修：`scripts/migrate_ragas_tables.py` 一次性套 `ragas.sql` schema + 跑 `migrate_legacy`（搬 909+111 筆，冪等、可重跑、row counts match）。**所有 active code 已寫 `ragas_` 前綴、無人寫舊名 → 舊表 vestigial、無雙寫衝突**（grep 證）。
  - **Bug 2（uuid_recall/precision over-count，latent）**：兩條 retrieve 路徑當前都已去重（vector path / `_with_context`）或 session-unique（FTS5 `sessions_fts`）→ over-count **非當前任一路徑觸發**；但 `_compute_uuid_metrics` 寫法 `hits=[u for u in ret_list if u in gt_set]`（分子含重複、分母 `gt_set` 去重）**允許** recall >1.0。修：硬化 metric 層用去重集合交集 `len(gt_set & set(ret_list))` + `rag.py` FTS5 路徑保序去重（一致性，防未來 schema 改 exchange 層級）。補 3 regression test（dup→recall 1.0 非 2.0）。
  - **Bug 3（附帶）**：runner `PROJECT_ROOT=parent.parent`=`modules/` 算錯（該 `parent×3` 至專案根）→ 直接執行 `ModuleNotFoundError`。修正後直接執行 / `-m` 皆可。
  - **驗收**：3 regression test passed；migration 冪等（二跑 0 搬移、`is_active` 68 正確帶過）；`tests/memory/` 30 passed（3 pre-existing `test_db.py` fail 與本次無關）。
  - **✅ RAGAS ready（Ollama up 真測，65 題全量）**：開 Ollama 後 vector 召回（bge-m3、`exchange_embeddings` 2541 筆）跑通，**uuid_recall=0.677 / hit@1=0.862 / mrr=0.867 / precision=0.833**，全 metric ≤1.0（無 over-count）；golden expected UUID 100% 匹配當前 sessions（27/27）。**此即 reranker 改善的 baseline 對照**（run_id `ragas-ollama-real` 留存 `ragas_evaluation_results`）。（先前 Ollama offline run recall 全 0 為 FTS5 fallback、非真值。）
  - **⚠ 未解架構債（與本修無關、記錄供後）**：`apply_features` 仍無呼叫者——「feature_registry 接線 main/server 啟動」未完成，本次只修 RAGAS 資料存取、**未完成 PR-O 接線**。
- **`grading_harness.harness_progress` 過寬吞 `OperationalError`（2026-06-19，L2 follow-up）** — 原 `except sqlite3.OperationalError: pass` 把 gold 表查詢的**所有** OperationalError 當「表尚未建立」吞成 0，連 DB locked / malformed 等真實故障也被靜默吞掉。改為只在訊息含 `no such table` 時吞（freeze 從未跑過視為 0），其餘 re-raise 不靜默。補 1 測試（gold 查詢遇 `database is locked` → re-raise）。
- **`hf_scraper.scrape_hf` `max_records` 全域上限 → 每 lane 配額（2026-06-16）** — 原本 `max_records` 為跨所有 lane 的全域上限，循序處理時第一條 lane（`lmstudio-community/gguf`）即吃光配額 return，後續 author（`mlx-community` / `ggml-org`）與所有 `mlx` lane 被**靜默餓死**（DB 0 筆 MLX）。改為**每 lane（author × format）**配額：起始重置 `lane_count`，配額用盡只停該 lane 不全域 return。重跑後 `v_search_model_latest` MLX 0 → 200 筆。同步更新 `runner.ScrapeParams.max_records` / `cli --max-records` 註解語意。

### Added

- **D3 judge 可信度診斷：混淆矩陣（2026-06-19，結論＝校準可結案）** — `scripts/judge_confusion_matrix.py`（+`tests/layer2/test_judge_confusion_matrix.py`，2 passed）：Claude in-session **盲評** + Shiba 人類標記（`user_accepted`）為 GT，對比本地 panel 對 74 筆真實 session 輸出（`question_id IS NULL` 排除 Tier B gold）的 approved/rejected，算混淆矩陣。**核心結論（誠實切窄）**：(1) Claude 不適合當 GT——9 筆 Shiba 採納的 good 僅認同 1/9，「訓練價值」標準系統性嚴於「實用採納」；(2) 9 筆 shiba-good 錨**全是 `user_accepted=1` high_value override**（panel 獨立 score avg 3.46、本會 reject）→ 主矩陣 panel 軸污染、TPR/TNR 作廢（同 Tier B `question_id` 機制，初版漏抓、advisor 抓出）；(3) **survives on aggregate**：14 approved 中 13 是 override、panel 自然 approve 僅 **1/74（≈1.4%）**，**D3 文獻 agreeableness/放水病未觀察到 → judge 校準可結案、放水病不存在**。**construct divergence**（採納於情境 ≠ 訓練價值 ≠ panel 分數），非 Claude 失準。報告：`docs/note/2026-06-19-d3-judge-confusion-matrix.md`。

- **評分 harness + Tier A/B 黃金樣本凍結（2026-06-17）** — 讓 `training_samples` / 黃金樣本評分可 session 續跑迭代評滿，評分者 = Claude（本 session 親撰，非付費 API）+ 本地三裁判：
  - **harness**：`services/grading_harness.py`（核心迭代評分 + 凍結門檻）+ `scripts/grading_harness_cli.py`（CLI）。**Tier A** = 本地三裁判（Qwen3.5-35B / GLM-4.7-Flash / Gemma-4-e4b）評 `training_samples`，drain 後 max **6.67** < freeze 門檻 9.0 → **未產生任何 gold，證實需 Claude 親撰**。**Tier B** = 由 48 題題庫橋接、Claude 親撰 gold（`question_id` FK 作冪等鍵 + L3 判別子，`status=approved`、寫 `expected_answer`，6 event_type × 8 = 48）。
  - **破 grader=author 循環**：48 gold 全經本地三裁判**獨立**複評（`_call_openai_compat` 直呼避 `output[:500]` 截斷、`max_tokens=2048`、thinking 關閉、judge-outer 序評）→ **48/48 PASS**（panel-mean 9.32–9.33，清楚高於 Tier A 地板 6.67）。誠實邊界：建立 provenance / floor-clearance，**非**逐筆品質排序（panel 頂端飽和：Gemma 釘 10.0、GLM 釘 9.0、僅 Qwen 區辨）。報告：`docs/note/2026-06-17-tierB-{batch1,21gold}-judge-reeval.md`。
  - **L3 汙染防護**：`extraction/dataset_formatter.py` 之 `_fetch_new_samples` + `_fetch_ebbinghaus_replay` 皆加 `AND question_id IS NULL`，排除 Tier B 橋接 seed 列（`output` 為空）混入 MLX 訓練集。
  - **凍結**：`scripts/freeze_golden_set.py`（`score>=9.0` + `approved`，各 event_type 均勻配額、上限 50）→ 48 gold 凍入 `gatekeeper_golden_samples`（8×6 event_type、無重複）。
  - **sid 121 前提糾正查證**：gold 主張「Gemma3 無原生 thinking 模式 → `think:false` no-op」經 web 查證確認（內建 thinking 是 **Gemma 4** 才加入；Gemma 3 社群可 fine-tune（GRPO）外加但**非 stock 開關**），gold polish 補註此細節堵裁判過度保守 hedge。
  - **merge 前自我 review fail-closed 補強（2026-06-19）**：(H1) `freeze_golden_set` query 加 `COALESCE(expected_answer, output) != ''`，擋 Tier B 種子列若漏帶 `expected_output` 卻被評 approved 時鑄出**空答案 gold**（fail-open → fail-closed）；(M1) `scrub_for_export` / `assert_clean` 補 RFC1918 私有網段（`10.x`、`172.16-31.x`）scrub + backstop（原 `scrub_pii` 只覆蓋 `192.168`/`127.x`，無 IP fail-closed 回查）。
  - **驗收**：`pytest tests/layer2/test_grading_harness.py tests/layer2/test_dataset_formatter.py -q` **27 passed**（+3：freeze 空答案守衛、私有 IP scrub、私有 IP backstop）。

- **`model_api_tools` 搜尋 API：`GET /models`（2026-06-16）** — `api.py` 原僅有 `POST /scrape/{source}` 觸發爬取，補上查詢端：走 `v_search_model_latest`（每 source×name 最新一批），支援 `source` / `format` / `author` / `q`（name 模糊比對）過濾與 `limit`(1–500)/`offset` 分頁，回 `{total, count, limit, offset, items}`。SQL 收斂於 `store.search_models` / `count_models`（共用 `_latest_filter`，DIP）；`get_conn` 為 yield 型 DIP seam（請求結束關閉、測試可 override）。驗收：3 tests（無過濾 / format=mlx / keyword+分頁，importorskip fastapi + in-memory 注入）。

- **`model_api_tools` name regex 回填 `param_size` / `quantization`（2026-06-16）** — HF `/api/models` **list** endpoint 規格上不回 config 細節（param/quant/ctx 淺層皆 NULL），規格 metadata 原僅本機 deep enrich 的 14 筆有值 → 表幾乎無法按 size/量化篩選。新增 `core/name_parser.py`（純函數、零 I/O/SQL）解析 repo name 編碼的規格：MoE（`35B-A3B`）/ effective（`E4B`）/ dense（`12B`/`270M`）參數量 + 量化精度（`4bit` / `Q4_K_M` / `mxfp4` / `bf16`，優先序 bit>Q>fp>half；方法修飾 QAT/AWQ 不計）。`backfill_specs` 經 `Protocol` duck typing 只補仍為 NULL 的欄位（**deep 實測權威 > name 解析 > NULL**），接進 `runner` deep enrich 後一步。重跑後 `v_search_model_latest` param **55→2149**、quant **14→2563**（70% / 83% 覆蓋）；剩餘 NULL 經抽樣確認為真無 size（whisper / OCR / 版本號家族如 GLM-4.7），非漏解析。驗收：`pytest tests/model_api_tools/ -q` **22 passed**（11 既有 + name_parser 11）。

- **`OpenAICompatClient.generate(disable_thinking=…)` + `_thinking_extra_body()`** — 本地 qwen/glm 裁判經 `extra_body={"reasoning_effort":"none"}` 關 thinking 穩定吐 JSON；`set_teacher_active()` teacher 啟用切換；`setup_teachers.py --cutover` 硬切換子指令、`--verify` 對齊 production（qwen/glm 帶 reasoning_effort、max_tokens=2048）。
- **`model_api_tools/` 模型清單爬蟲 → `search_model_list` 表（2026-06-15）** — 爬取 Ollama library 與 HuggingFace（LM Studio 風格 GGUF/MLX）模型來源寫入統一 DB，未來「要下載／分析／選用哪些模型」可直接查表判斷：
  - **schema** `config/db/schema_search_model_list.sql`：`search_model_list`（append-only 快照，帶 `scrape_run_id` / `scraped_at`）+ `model_local_detail` 子表（本機深層 raw metadata）+ `v_search_model_latest` view（每 `source`+`name` 取最新 `scraped_at` 列）
  - **core 模組（SRP 拆分、I/O 全 DIP 注入免網路）**：`store.py`（`ModelRecord` / `write_batch` 單 txn / `get_latest`）、`ollama_scraper.py`（ollama.com/library HTML，`x-test-*` 錨點 + wrapping span `title` 精確 UTC 時戳、relative-time fallback）、`hf_scraper.py`（huggingface.co/api/models，lane=gguf/mlx 權威標記 format、`lastModified` 降序停損 + `Link` header cursor 分頁）、`local_scanner.py`（`/api/tags`+`/api/show`、`lms ls --json` 掃本機已裝 → `enrich_catalog` 升 deep + `is_local_installed`）、`runner.py`（`ScrapeParams` 編排、`uuid4` run_id、預設範圍 today−365d→today）
  - **觸發 adapter**：`cli.py`（`python -m model_api_tools.cli --source {ollama,hf,both}`，正解為單次 `both`，避免本機模型在缺 library slug 比對下裂成 slug + `:tag` 兩列）+ `api.py`（獨立 FastAPI app，**不掛** Layer 2 backend）+ `requirements.txt`
  - **驗收**：8 tests（store roundtrip×3 / ollama 解析 / hf 解析+停損 / local 掃描+enrich），全 in-memory + 注入 fake 免網路；雙來源 real-source 實跑寫入成功

### Added

- **session_start_hook `debug_echo` 觀測旁路（2026-05-23）** — `rag.debug_echo` flag 啟用時將召回內容以 ANSI 區塊 echo 到 stderr，僅顯示給使用者（Claude Code 對 exit 0 的 stderr 不回灌 model context，不消 token）。實作經 /code-review xhigh 15-finding 修復後 ship：
  - **safety**：`_echo_to_stderr` 自包 try/except + `sys.stderr.buffer.write(... .encode("utf-8", errors="replace"))`，避免 ASCII stderr 環境（LANG=C / launchd / CI runner）遇中文或 router `🤖` emoji 拋 UnicodeEncodeError、或 BrokenPipeError 連坐毀掉 `additionalContext`；echo 失敗只進 logger.warning
  - **順序**：`main()` 改為先 `print(json.dumps(output))` + `sys.stdout.flush()` 保證主契約落地，再執行 debug echo；避免 echo blocking 拖延 hook timeout
  - **logger 兩階段**：`context prepared` / `context emitted` 兩條訊息分別記錄，避免 echo 失敗時 log 撒謊『已注入』但 stdout 實吐 `{}`
  - **預設關閉**：`config.yaml::rag.debug_echo: false`（避免把含路徑/secret 的歷史記憶外洩到終端 / log / screen recording，違反 ~/.claude/CLAUDE.md 全域 secret 規則）
  - **`_CONFIG_PATH` 吃 SHIBA_PROJECT_ROOT env**：原本 `_LAYER1_DIR / config.yaml` 只看 hook 自身相對路徑，hook 被複製到 plugin 目錄時讀的是 plugin 版 config.yaml，repo config 改 `debug_echo` 完全失效；改為 `_PROJECT_ROOT / layer_1_memory / config.yaml` 與 sys.path 設定對齊
  - **TTY 偵測 + 單次 write**：`sys.stderr.isatty() and not NO_COLOR` 才掛 ANSI 色碼，避免 pipe / log file / SSH 無 TTY 環境看到 literal `\033[1;36m...` 雜訊；三段內容組成單一字串、一次 `buffer.write`，避免並發 hook 進程下三段 syscall 交錯
  - **source classification refactor（DIP / OCP）**：`get_rag_context` 簽名改 `tuple[str, RagSource]`（`Literal["vector", "fts5", "none"]`），來源由 callee 顯式回傳；刪 hook 內 `_infer_rag_source` 字串 sniff；補 2 條整合測試守住 producer↔caller 契約，未來加 reranker / HyDE 新路徑不會靜默誤分類 `unknown`
  - **polish**：`rstrip("\n")` 取代 `rstrip()` 保留 markdown 有意義的尾隨空白；ANSI label 改 `[=== ... ===]` 補閉合括號；刪除不可達的 `source_label = "empty"` fallback（caller 已 gate `if combined_context:`）

### Added

- **PR-O 系列：核心瘦身 + 功能模組化重構（2026-05-21~22，refactor 分支）**
  - PR-O-1 `ab37835`：`core/feature_registry.py` 基礎設施（`FeatureSpec` dataclass + topological sort + `register_hook`/`get_hook`/`reset_*` API）；`config/db/schema_core.sql` 雙寫並存 — 核心 schema 不再含任何 feature 表
  - PR-O-2 `0584c57`：解 V6 `finetune_runs` 雙重 DDL — server.py 啟動改 sanity check（schema_core 為唯一來源）
  - PR-O-3 gatekeeper 拆出：`modules/gatekeeper/{__init__,service,migrations,db/gatekeeper.sql}` + Stage A/B/dep-violation 隔離驗證；表名加前綴 `gatekeeper_golden_samples`；`layer_3_pipeline/runner.py` 改 `get_hook("gate")`
  - PR-O-4 ebbinghaus_trigger 拆出：`layer_3_pipeline/trigger_policy_basic.py`（核心 fallback：approved≥30 即觸發）+ `modules/ebbinghaus_trigger/service.py`（feature on 走 Ebbinghaus + drift signals）；runner 改 `get_hook("trigger") or should_trigger_basic`
  - PR-O-5 multi_judge_v2 拆出：`core/judge_strategy.py` Protocol；`modules/multi_judge_v2/{service,migrations,db/multi_judge_v2.sql}` 強制 vendor 多樣性 ≥ 2 + 寫 `multi_judge_v2_agreement_logs`（含 vendor_diversity 欄位）；`background.py::score_pending_samples` 改 `get_hook("judge_score") or multi_judge_score`
  - PR-O-6 ragas 拆出：`evaluation/` → `modules/ragas/`（含 launchd plist + setup.sh）；建 `ragas_evaluation_results` / `ragas_retrieval_golden_set` 加前綴版表 + idempotent `INSERT...SELECT` 搬舊資料；9 個檔內 40+ SQL refs 改名；`judge_agreement_logs` → `multi_judge_v2_agreement_logs`；`depends_on=("multi_judge_v2",)` 強制 fail-fast
  - PR-O-7 paraphrase 拆出：`layer_2_chamber/backend/services/paraphrase_service.py` → `modules/paraphrase/service.py`；`background.py::_run_paraphrase_job` 改 `get_hook("paraphrase")` → 無 hook 即排程 tick noop；不建專屬表（`source_instruction` 留在核心 `exchange_embeddings`）
  - PR-O-8 advanced_compressor 拆出：`layer_0_router/compressor.py` 改為「截斷 fallback + hook 注入」入口（無 hook=取前 300 字+`...`）；Gemma 壓縮邏輯搬到 `modules/advanced_compressor/service.py`；`tests/layer0/test_compressor.py` 4 case 重寫覆蓋 hook on/off/fail
  - PR-O-9 舊 schema 清理：刪 `evaluation/migration_evaluation.sql`（完全由 `db/ragas.sql` + `multi_judge_v2.sql` 取代）；註腳審查通過
  - PR-O-10 文件 + 組合驗證：`config/shiba.yaml::features` 區塊補完整依賴鏈/模組對應/hook 名稱註解；`tests/test_pr_o_10_combinatorial.py` 10 case（all-off / single-on×4 / dep-pair×2 / dep-violation×2 / all-on）
  - **驗收**：6 個 `modules/*/tests/verify_isolation.py` 全綠 + `tests/test_pr_o_10_combinatorial.py` 10/10 + 全 pytest 145 passed（6 個預存環境性失敗：numpy/apscheduler 缺失 + projects.path UNIQUE，與本次重構無關）
  - **架構不變式**：全 7 個 flag 預設 `false` → 系統行為 = 純核心 4-layer；核心層只透過抽象 hook 名取得 feature 實作（DIP 落地，無 `modules.*` import 在核心層）

### Added

- **PR-L `aa9ec8c` golden-set 汰換（2026-05-21）**：`retrieval_golden_set` 加 `is_active INTEGER DEFAULT 1` soft-delete 欄位；C 段 12 題低分（score<4 或無法判定，含 ack-only 短句）標 `is_active=0` 保留審計軌跡；`c2_e2e_evaluation` / `ragas_runner` SQL 加 `AND is_active=1` 篩選；active set 縮為 16 題
- **PR-M macro-exchange RAG 擴展 infra（2026-05-21，pr-m-rag-cross-exchange-context 分支）**：
  - PR-M.1 `9ad697a` schema：`exchange_embeddings.exchange_id` 外鍵 + 雙階段 backfill（原始 99.5% + paraphrase 98.2% = 總體 99.0% 命中）
  - PR-M.2 `42f198b` `rag.py::retrieve_for_eval_with_context(window_k=K)`：WITH CTE 拉鄰居 ±K exchange，preview_chars=200 截斷
  - PR-M.3 `11228da` `c2_e2e_evaluation` + `ragas_runner` 加 `--rag-window K` CLI 旗標
  - PR-M.4 `f53828c` Claude generation sleep 動態化 `max(0.5, 4 - elapsed)`，Phase 4 wall time −25%

### Operations

- **PR-M Phase 4 A/B 結果（16 題 × Claude judge）**：K=0 baseline 7.13 / K=1 6.50 / K=2 6.38 / K=3 6.69 — **K≥1 全敗**，唯一受益短句題（qid=2 +3）抵不過高分指令類題（qid=8/13/14 −3~−5）被鄰居稀釋；決策按 plan 矩陣 Δ<−0.1 → 退回 K=0；API/CLI/schema 保留當 OCP 基礎建設，Phase 5 持久化不啟動
- **Conditional Expansion 棄計畫 `7ab03f6`（2026-05-21）**：Phase 1-5 全部驗證 — 規則分類器 precision=1.0/recall=0.875/F1=0.933，auto:2 mean=6.6875 vs K=0 7.1333（Δ=−0.4458）；三條獨立證據（macro-exchange 整體無效、命中題不受益、受益題抓不到）；DROP COLUMN needs_context_label + 刪 classifier 三檔 + revert 三檔；retrospective 寫入 `docs/archive/plans/2026-05-21-conditional-expansion.md`
- **PR-N judge noise 治理 + golden set 擴增（2026-05-21）**：
  - N.1.1 `6eeb468`：4 vendor client（anthropic/openai_compat/ollama/gemini）`generate()` 加 `temperature: float = 0.0` 參數，原硬編碼 0.1 改參數化；caller 不傳即 deterministic（評估友善），需要多樣性者顯式傳
  - N.1.2 `a1cb3d5`：`c2_e2e_evaluation` 加 `--n-runs K` flag，K>1 對每題 judge 重跑 K 次取 mean，raw_scores 寫 metadata
  - N.1.3 noise floor 量化：16 active 題 × K=3 judge，median std=0，mean std=**0.18**（14/16 完全 deterministic）；舊 PR-M 觀察 ~0.3 → 治理後降約 40%；雖略超 ≤0.15 目標，但 <<<0.5 N.2 子集對比門檻可接受
  - N.2.0 `828f170`：`golden_set_builder.sample_queries` 加 `NOT IN (SELECT query FROM retrieval_golden_set)` 防擴增時撞題（含 `is_active=0` 已汰換題）
  - N.2 golden set 16 → 65 active：annotate 80 候選 → embedding 去重 17 題（13 paraphrase 組）→ Shiba 4-tier 審查 drop 7 題（uuids=[] 3 + 自動回答可解 4）→ C.1 expected_answer 生成 56 新題 → 7 FLAG（score<7）全 drop；最終 `is_active=1 AND expected_answer IS NOT NULL` = **65**（16 EXIST + 49 NEW）
  - N.2 雙 baseline（tag=`n50-baseline`）：Claude `e2e-claude-20260521T120858` mean=5.5968 / Qwen `e2e-ollama-20260521T122023` mean=5.8281；16 EXIST 子集 vs 舊 baseline 偏移雙方向（Claude −0.57 / Qwen +1.48）— 主因為 judge temperature 0.1→0 + PR-M retrieval API 改動，舊 baseline invalidate，本次數字為 **PR-N 後新基準**

## [1.6.0] - 2026-05-21

RAGAS 評估框架完整落地（Phase 0/A/B/C 全部完成）；Teacher 配額治理改寫（Gemini Paid Tier 升級 + RPM 速率管控 + 429 分流 + UTC TZ 對齊）；`clients/` 共用 AI 呼叫包誕生（vendor 分包 + 三類錯誤 + ai_api_call_logs）；中文召回核心升級（nomic-embed-text → bge-m3，1024-dim）；4 vendor client 統一 exponential backoff。

### Added

- **RAGAS Phase 0/A/B/C（commits `ea50cee` ~ `e9e17fc`）**：
  - Phase 0 schema：新增 `retrieval_golden_set` / `evaluation_results` / `evaluation_runs` 三表，`evaluation/schemas.py` 含 migrate 函式
  - Phase A.1 `layer_1_memory/lib/rag.py::retrieve_for_eval()`：UUID 型召回介面
  - Phase A.2 `evaluation/golden_set_builder.py`：31 筆 golden query（Anthropic Sonnet medium 生成）
  - Phase A.3 `evaluation/ragas_runner.py`：UUID 型指標 + Gemini Flash judge → Recall@3 0.744 / Precision@3 0.613 / Hit@1 0.643 / MRR 0.762
  - Phase B `evaluation/{run_judge_votes,compute_kappa,compute_faithfulness,layer2_report}.py`：votes 持久化 + Fleiss' Kappa + Faithfulness + Layer 2 報告彙整
  - Phase C.1 `evaluation/c1_generate_answers.py`：Flash-Lite 生成 expected_answer + 驗收（28/31 完成 + 4 flags 手審 manual-by-shiba）
  - Phase C.2/C.3 `evaluation/c2_e2e_evaluation.py`：Qwen 5.23 + Claude 5.48 baseline；bge-m3 swap 後 5.39（+0.16）
  - Phase C.4 `evaluation/c4_weekly_ci.py` + `com.shiba.ragas-c4.plist`：週度 CI launchd（週日 22:00 台灣時間）
- **`clients/` 共用 AI 呼叫包（PR-A `07447c0` + PR-E `c58bfb3` + PR-H `543d102`）**：
  - `clients/base.py`：`AIErrorCategory`（PERMANENT / TRANSIENT / QUOTA）+ `AIClientError` + 統一 `TRANSIENT_RETRY_BACKOFF_SECONDS`
  - `clients/{gemini,anthropic,openai_compat,ollama}/client.py`：vendor 分包，每次呼叫寫 `ai_api_call_logs`（source_type='remote'|'local' 區隔）
  - `teacher_service` 改為 thin wrapper（`_call_anthropic` / `_call_openai_compat` / `_call_ollama`），`_vendor_of` helper
- **Teacher 配額治理 PR-A/B/C/D（commits `77ef915` ~ `9c6a302`）**：
  - PR-A schema：`teachers` 表 +4 欄（rpm_limit / rpm_window_start / rpm_count_in_window / transient_backoff_until）+ token 配額 +8 欄
  - PR-B `f06f0c1`：RPM slot 原子消耗 + 429 分流（`PerMinute` 短暫 backoff / `PerDay` 每日重置）
  - PR-C `5da1f50`：scheduler 改 PT 午夜 UTC 08:05 重置（Gemini RPD 在 PT midnight 重置）
  - PR-D `543d102`：D.1 AnthropicClient + D.2 Claude `daily_limit=999999` placeholder + D.4 OpenAICompatClient（D.3 token-based TPM 預設上限 → won't-do）
- **Gemini Paid Tier 升級（PR-B `9c6a302`）**：Flash 500 RPM / 5000 RPD，Flash-Lite 2000 RPM / 999999 RPD（取 Paid 上限 50% buffer）；每次呼叫仍 `sleep(4)`
- **`clients/gemini/`：google-genai SDK 路徑 + REST 路徑雙軌**（PR-A）：REST 走 `_call_gemini_rest` 給 evaluation 腳本；SDK 路徑供 teacher_service 使用
- **Phase C.1 expected_answer pipeline（PR-C `d1e401e`）**：Flash-Lite 生成 + 驗收，4 flags 手審機制（`manual-by-shiba` notes）
- **bge-m3 swap（PR-J `42f1556`）**：`EMBED_MODEL` nomic-embed-text → bge-m3，`EMBED_DIM` 768 → 1024；`evaluation/backfill_bge_m3.py` 一次性 backfill 2263 exchange embeddings；A.3 結果 Hit@1/MRR/Precision 均上升，Recall@3 −0.036 在雜訊範圍

### Changed

- **PR-G `0953f59` thinking-mode 全面關閉**：Gemini Flash `ThinkingConfig(thinking_budget=0)` + Ollama `num_predict=2048`（thinking tokens 計入 num_predict 配額，須保留正文空間）；解決 score 解析失敗（max_tokens=100 預算被 thinking 吃光）
- **PR-I.3 `202f70d` retry-backoff 共用**：`TRANSIENT_RETRY_BACKOFF_SECONDS` 提到 `clients/base.py`，4 vendor client 統一從固定 10s × 1 次 → exponential `[2,5,10]` × 3 次
- **PR-K.1 `6eb58ee` aggressive backoff**：`TRANSIENT_RETRY_BACKOFF_SECONDS` 從 `[2,5,10]` → **`[5,15,30,60]`**（最壞 110s），提升分鐘級 Gemini spike 容忍度
- **PR-K.2 `6571915` C.2 韌性**：c2_e2e_evaluation judge 從 flash-lite → flash + `disable_thinking=True`（flash 配額池與 flash-lite 獨立，503 分布不同）；Ollama 永久錯誤改 skip 單筆而非整批熔斷
- **PR-D refactor `0155a0f`**：`golden_set_builder` Anthropic 改用 teacher_service 基礎設施；ragas_runner Flash 速率保護（sleep 4s）

### Fixed

- **PR-I.1 `1faaaad` schema-drift**：`schema_layer2.sql` 對齊 PR-D quota migration（teachers +8 token 欄 + teacher_usage_logs +2 欄），修 `tests/layer2/test_teacher_service.py` 6 個 `OperationalError`
- **PR-I.2 `3b6dd0b` tz-bug**：`get_today_usage` 改用 UTC `datetime.now(timezone.utc).date()` 對齊 SQLite `datetime('now')`，修 CST 跨日後 0-8 小時 `is_quota_available` 永遠回 True 的 production bug
- **PR-A hotfix `8a4c2d3`**：Anthropic backfill 改用 `model_id` + 修正 xai 註解誤導

### Operations

- **C.2/C.3 bge-m3 baseline 雙模型驗證**（28/28 × 2 零熔斷）：

  | 模型 | embed | judge | mean_score | run_id |
  |------|-------|-------|-----------|--------|
  | Qwen3:30b-a3b | nomic | flash-lite | 5.23 | e2e-ollama-20260520T040819 |
  | Qwen3:30b-a3b | **bge-m3** | **flash** | **5.39** | e2e-ollama-20260520T164503 |
  | Claude Sonnet 4.6 | nomic | flash-lite | 5.48 | e2e-claude-20260520T044310 |
  | Claude Sonnet 4.6 | **bge-m3** | **flash** | **5.14** | e2e-claude-20260520T220442 |

  Qwen +0.16 / Claude −0.34 兩者皆在雜訊範圍（embed 與 judge 兩變數同時改，非 apples-to-apples）；bge-m3 對中文召回提升 < 預期；Qwen bge-m3 (5.39) 反超 Claude bge-m3 (5.14)，再次印證 **RAG 召回為主瓶頸**，生成模型差異 < 召回變化的不確定性；PR-K aggressive backoff `[5,15,30,60]` × flash judge 完全吸收 503 spike
- **`evaluation/setup_c4_launchd.sh`**：C.4 launchd 安裝腳本，週日 22:00 台灣時間隨機抽 10 筆 ragas 評估，anchor=5.23 drop>0.5 觸發 alert
- **Backup**：`data/2026-05-20_shiba-brain.db.bak`（bge-m3 swap 前快照）+ `data/2026-05-20_shiba-brain.db.bge-m3-backfill.bak`（backfill 後快照），本地保留

## [1.5.0] - 2026-05-20

模型 yaml 化重構 Step 3-7 全部完成（Layer 0 三顆推論模型 + Layer 3 訓練 base 完全解硬寫，前端 PhaseRouter dropdown 即時切換 + online/offline kill switch）；SQLite hardening PR1+PR2 全部落地（PRAGMA 統一 + APScheduler cron 錯開 + WAL→DELETE journal + stop_hook 4 段切分 + multi_judge 三欄共一事務），DB corruption 事件根因排除，24h 觀察期已通過。

### Added

- **Step 3.1-3.3（commit `2cd6b21`）**：`layer_0_router/_config.py` 含 `load_active_snapshot` / `is_local_enabled` / `split_inference` / 50ms in-process cache；三檔（`classifier.py` / `compressor.py` / `router.py`）改讀 `router_config` + `model_registry.snapshot` JSON，徹底解硬寫；offline kill switch 由 `router_config.ollama_status` 即時生效。
- **Step 3 範圍外順手修**（同 commit `2cd6b21`）：`layer_2_chamber/backend/api/routes_router.py:163-176`（/router/status）與 `layer_3_pipeline/gatekeeper.py:151`（_get_current_model fallback）原 import `CLASSIFIER_MODEL/LOCAL_MODEL` 已移除，改呼 `load_active_snapshot`，避免 backend 啟動失敗。
- **Step 3.4 整合測試（commit `bc07f98`）**：real Ollama happy path（classify → compress → respond 全程）+ `router_decisions` 寫入驗證 + offline kill switch 實測；24/24 unit test 全綠。
- **Step 4 Backend API（commit `60aaac6`）**：`routes_router.py` 新增 4 端點：`GET /router/models/installed`（yaml vs Ollama 三分類）、`GET /router/models/by-role`（dropdown 清單）、`PUT /router/config`（model 切換 + snapshot atomic 寫入）、`POST /router/config/reload`（yaml 修改後刷 snapshot）；改 `GET /router/status` 加 yaml_modified 偵測。
- **Step 5 前端 UI（commit `bccbded`）**：新增 `Select.vue` / `api/router.ts` / `stores/router.ts`；`PhaseRouter.vue` 系統狀態列改造：3 個 role dropdown + ToggleSwitch（ollama_status kill switch）+ ⚠️ yaml 已修改徽章 + Reload 按鈕 + 切換 toast 提示。
- **Step 6 Layer 3 yaml 化**：`_config.py::get_training_base_hf_repo(block)` 取代 `mlx_trainer.py` / `gguf_converter.py` 中的 `BASE_MODELS` hardcode dict；訓練 base 切換走 `PUT /router/config`，無需改 code。
- **Step 7 文件**（本 commit）：新增 `config/models/README.md`（yaml schema + 新增 model 三步驟）；`CLAUDE.md` 技術選型表加 yaml 路徑欄；`CHANGELOG.md` v1.5.0 entry。

### Fixed

- **Ollama `think` flag 位置 bug（commit `bc07f98`）**：`split_inference` 原將 `think` 留在 options dict，但 Ollama 0.9+ 規格 `think` 是 body 頂層欄位，放錯位置 Ollama 直接忽略，導致 thinking-only 模型（Qwen3-30B）整段進 thinking 軌跡、`message.content` 全空。修法：`split_inference` 改三元組 `(options, keep_alive, think)`，三檔呼叫端把 `think` 提到 body 頂層；修復後 `tokens_response=719`（自然結束）/ `out_len=500`。
- **README 過時模型字串**：`classifier` 描述 `gemma3:2b` → `gemma3:4b`。

### Incident

- **2026-05-09 11:14 shiba-brain.db corruption**：`sqlite3.OperationalError: disk I/O error`，DB 末段 100+ pages 損壞。根因：host stop_hook + container backend uvicorn + APScheduler 6 jobs 跨進程並發 + PRAGMA 三層不一致（Layer 0 完全無設、Layer 1 busy=5s、Layer 2 busy=30s，三層皆缺 `synchronous` / `mmap_size` / `wal_autocheckpoint`）。已用 `.recover` SOP 修復（21,559 exchanges + 440 decisions 全救回，integrity_check=ok）。根因排除列入 SQLite hardening PR1 計畫（計畫檔：`docs/archive/plans/2026-05-09-sqlite-race-hardening.md`）。

### SQLite Hardening PR1+PR2 - Completed

PR1（PRAGMA 統一 + 排程錯開）：
- 建 root 層 `shiba_db.py`（全專案統一連線 helper，PRAGMA: WAL / synchronous=NORMAL / busy_timeout=30s / wal_autocheckpoint=1000 / mmap_size=256MB）
- Layer 0/1/2/3 全部 `sqlite3.connect` 替換，清除三層 PRAGMA 不一致
- APScheduler `interval` → `cron` 錯開 minute（避免多 job 同 minute=0 觸發）
- WAL checkpoint cron job（daily 03:30 TRUNCATE）
- WAL→DELETE journal mode（commit `f73e489`，根治 Docker bind mount SHM 鎖定不一致）

PR2（事務原子化，commit `e36aceb`）：
- **Step 5（stop_hook 4 段切分）**：`layer_1_memory/hooks/stop_hook.py` 將原本「一個 `with conn:` 包 4 個寫入區塊」改為 A=session / B=messages / C=branches / D=fts 四段獨立 try/except，任一段失敗 → re-raise → `get_connection` 統一 rollback（讀法 B：保 FK 完整性），同時 logger 標出具體失敗段別。
- **Step 6（multi_judge 三欄共一事務）**：`layer_2_chamber/backend/services/multi_judge.py` 將 `_update_sample_score`（寫 status/score）與 weight UPDATE 包進同一 `with conn:`；`teacher_service.py::_update_sample_score` 移除內層 `conn.commit()`，事務邊界交給 caller。徹底消除「score 寫了 weight 漏」部分狀態。quota 計數仍獨立 commit（精確化版本）。
- **驗證（三層）**：unit test 全綠 + dry run（檢視 transaction 邊界）+ smoke + E2E（`scripts/e2e_pr2_smoke.py` 兩案：multi_judge 三欄原子寫入、stop_hook C 段 raise 整體 rollback，docker 容器內驗證通過）。

### Tests

- `tests/layer0/`：24/24 全綠；`TestSplitInference` 三 case 驗三元組（options 7 keys / keep_alive / think）。

## [1.4.0] - 2026-05-07

模型 yaml 化重構 Step 1+2 完成：DB 雙表機制（`model_registry` 版本歷史 + `router_config` 選擇器）+ 師父 CRUD + 共用 UI 元件。下載新模型 → 寫 yaml → DB 切換的閉環打通至前端唯讀展示為止；前端可切 dropdown 與 Layer 0 解硬寫排在 v1.5.0（Step 3-7）。

### Added

- **Step 1 — model yaml schema + loader（commit `7a4a2ec`）**：5 份 yaml（`config/models/{classifier,compressor,responder,training_base}*.yaml`）+ 專案根 `models_loader.py`（frozen dataclass module-level singleton，與 `shiba_config.CONFIG` 並列），`from models_loader import MODELS` 即可拿到所有 yaml 解析結果與 `stems_by_role(role)` 查詢 helper。實作中追加第 5 份 `responder-qwen36-35b-a3b-nvfp4.yaml`（既有機台 nvfp4 模型 smoke test 通過）。
- **Step 2 — DB 雙表機制（commit `b706e78`）**：
  - `model_registry`（schema in `config/db/schema_model_registry.sql`）：版本歷史 + 完整 yaml snapshot JSON，含 `is_current=1` partial unique index、`change_kind` enum（`created`/`modified`/`restored`/`removed`）、`UNIQUE(model_name, content_hash)` 防止 restore 時 hash 重複；`models_db.py::sync_model_registry` 啟動時 idempotent 同步 yaml ↔ DB，覆蓋 6 種變動情境（created/modified/restored/removed/hash-switch/unchanged）。
  - `router_config`（migration in `core/config.py::_run_router_config_migration`）：純選擇器表 `key/value/updated_at`，seed 時依 `MODELS.stems_by_role(role)` 字典序取第一個 stem 當預設；含 `ollama_status='online'` 維護 flag。
  - `main.py` lifespan：`init_model_registry → sync_model_registry`，失敗只 log 不擋 API 啟動（degrade-friendly）。
  - 新 endpoints：`routes_models`（list/by-role）、`routes_router_config`（GET/PUT 選擇）。
  - 前端 `PhaseModels.vue` 4 列 grid 唯讀頁（`align-items:start` 頂部對齊、`min-width:0` 防內容溢出 grid item、STANDBY 卡 normal flow 排在 ACTIVE 卡下方），Sidebar 加「模型設置」入口。
- **師父 CRUD + 共用 UI 元件（commit `2bd6c28`）**：
  - `routes_teachers.py` 補 8 endpoints（list/get/create/update/delete/test/enable/disable）+ connectivity smoke test endpoint。
  - `PhaseTeachers.vue`：卡片可點開詳情面板、停用反灰、CRUD 表單。
  - 4 個 `frontend-vue/src/components/shared/` 共用元件：`Modal`（dialog 容器）、`ConfirmDialog`（破壞性操作確認）、`FormField`（label + input + error）、`Toast`（全域訊息匯流）。
  - `stores/toast.ts`：Toast 訊息佇列 pinia store，`App.vue` 統一 mount 一次。
- **plan 檔歸檔**：`docs/archive/plans/2026-05-07-yaml-schema-1-yaml-2-4-glimmering-candy.md` 含完整 7-step 計畫 + 執行偏離記錄（snapshot 改放 model_registry、`local_enabled`→`ollama_status`、`_config.py` 移到 Step 3）。

### Changed

- **`routes_finetune.ollama_status`（commit `ceb9ed0`）**：從 `subprocess.run(["ollama", "ps"/"list"])` 改為 `httpx` 打 `/api/ps`、`/api/tags`，container 內無 ollama CLI 也能回狀態，符合 docker-compose 部署語境。
- **前端 polish（commit `ceb9ed0`）**：`DateFilterBar` 加捷徑按鈕 + 自訂文字輸入 + 換行容錯；`Pagination`/`DataTable`/`Btn` 樣式統一與小幅修補；`PhaseRouter`/`PhaseMemory` 日期與顯示細節調整；`api/dateFilter.ts` 工具強化。

### Fixed

- **Hook 繁中過濾硬化（commit `ceb9ed0`）**：`stop_hook.py` 與 `services/paraphrase_service.py` 強化簡中變體偵測，避免 RAG 資料被簡體中文污染（延續 v1.3.x 的 exchange_embeddings 清理脈絡）。

### Tests

本版未新增測試（v1.4.0 範圍以架構與 UI 為主）；Step 3 將強制走 `superpowers:test-driven-development` 補齊 Layer 0 三檔解硬寫測試。

## [1.3.1] - 2026-05-06

文件目錄一次性整理 + 對外 agent 規範書（`AGENTS.md`）對齊最新事實。純文件變更，不動執行碼。

### Added

- **`AGENTS.md`**：對外 AI agent / coding 工具的規範入口（`CLAUDE.md` 為個人補充、不入版控；外部讀本走 `AGENTS.md`）。內容對齊 v1.3.0 事實：DB 路徑 `./data/shiba-brain.db`、Layer 0 分類器 `gemma3:4b`、`multi_judge` 三方投票完整邏輯、Layer 1→2 橋接條件 `has_final_text=1 AND has_error=0`、文件導覽指向 `docs/{design,references,archive}/`。
- **`docs/design/`**：Layer 0/1/2/3 實裝規格 5 份從 `docs/superpowers/plans/` 攤平搬入並改為日期前綴命名。
- **`docs/archive/plans/`**：歷史 plan 4 份（含從 `~/.claude/plans/` 歸檔的 3 份）統一日期前綴。
- **`docs/archive/2026-04-25-codex-review.md`**：原 `2026-04-25_codex_suggestion.md` 一次性外部審視報告歸檔。

### Changed

- **`docs/references/`**：扁平化原 `references-{paper,blog,git}/` → `references/{papers,blogs,git}/`，移除工具導向的命名前綴。
- **`.gitignore`**：移除已不存在的 `docs/superpowers/`；新增 `docs/references/git/*/` 整個第三方 repo 不入版控（內含獨立 `.git/` 會被 Git 視為 gitlink，整包排除最乾淨；副本仍留在 disk 供離線閱讀）。

### Removed

- 空殼資料夾 `docs/superpowers/`、`docs/references-{paper,blog,git}/`。
- 各層遺留 `.DS_Store`。

## [1.3.0] - 2026-05-04

Grok 外部審視回應：CADB 四項架構升級完成（A 廠牌多樣性、C retention 防遺忘、D 首次把關、B 告警儀表板）。

### Added

- **C Retention/Golden Set（`gatekeeper.py` + `schema_layer2.sql` + `config.py` + `scripts/freeze_golden_set.py`）**：新建 `golden_samples` 表凍結歷史高分樣本（score≥9 的 approved），shadow A/B gate 時以此集合驗證新模型是否在舊知識上維持水準（≥85% 不退化才放行），防止災難性遺忘；`_run_golden_samples_migration` idempotent 初始化；`freeze_golden_set.py` 一次性手動凍結腳本。
- **A Judge 廠牌多樣性（`multi_judge.py` + `schema_layer2.sql` + `config.py`）**：`teachers` 新增 `vendor` TEXT 欄（google/xai/openai/mistral/local），`_vendor_of` helper 安全讀取；`_collect_votes` C1 早停加廠牌異質條件（兩票一致 + 來自不同 vendor 才早停），避免 Gemini Flash + Flash-Lite 同源決策風險；不同 vendor 強制至少三票以保證異質性門檻，全同 vendor 時仍允許三票（防外部 API 全當機無法評分）。
- **D 首次訓練人工把關（`trigger_policy.py` + `runner.py` + `routes_finetune.py` + `schema.sql` + `layer_3_pipeline/server.py` + `config.py`）**：`finetune_runs` 新增 `requires_manual_approval` / `approved_by_human` / `approved_at` 三欄；status CHECK 擴充至包含 `pending_manual` / `gate_eval` / `gate_rejected`（修正既有 gate_eval/gate_rejected 未納入 CHECK 的 bug）；`trigger_policy.TriggerDecision.requires_manual` 標記首次訓練（無既有 done run），`runner` 建立 `pending_manual` run 不啟動實際訓練；`routes_finetune` 新增 `GET /pending_manual` 列出待審核、`POST /{run_id}/approve` 人工核准後降為 `pending` 讓 runner 撿起。
- **B Drift 告警 + 儀表板（`shiba_alert.py` + `trigger_policy.py` + `routes_router.py` + `background.py`）**：新建 `shiba_alert.py` 公用模組統一告警出口（背景層與 trigger 層共用），alert 同時輸出 CRITICAL log + 可選 webhook；`trigger_policy._signal_distribution_drift` 觸發時呼 `send_alert(distribution_drift)`；`routes_router` 新增 `GET /stats/drift` endpoint 對各 block 實時計算 cosine_dist、threshold、是否通過判定，供儀表板監控分布漂移趨勢。
- **D4 首次訓練 tests**：`tests/layer3/test_trigger_policy_manual.py` 2 tests（首次 requires_manual=True、後續 requires_manual=False）。
- **A3/C3/B3 新測試**：`test_multi_judge_vendor.py` 3 tests（同源無早停、異質早停、全同源允許三票）、`test_gatekeeper_retention.py` 3 tests（退化阻止、保留通過、樣本不足略過）、`test_drift_alert.py` 2 tests（超閾值告警、正常不告警）。

### Changed

- **background.py**：`_send_alert` 移到 `shiba_alert.py` 公用模組，改 import 保持相容；W4/W5 告警同走新通道。
- **config.py**：新增 `_run_teachers_vendor_migration`（backfill 廠牌）、`_run_golden_samples_migration`（建表）、`_run_finetune_manual_migration`（status CHECK 擴充 + 三欄 ADD）。
- **trigger_policy.py**：`_last_finetune_datetime` 修正 naive datetime bug（SQLite `datetime('now')` 無 tz offset，假設為 UTC）；`_signal_distribution_drift` 超閾值時呼 alert；`should_trigger` 加首次偵測邏輯回傳 `requires_manual`。
- **server.py**：inline `finetune_runs` DDL 同步 status CHECK（加 pending_manual/gate_eval/gate_rejected）。
- **freeze_golden_set.py**：新建。支援 `--dry-run` 預演、各 event_type 均勻配額（各 ~7 筆）、上限 50 筆防止 shadow eval 過慢、無重複寫入。

### Tests

新增 10 tests，全 113 tests 通過（7 個 pre-existing 失敗同 v1.2.0 註記）。

## [1.2.0] - 2026-05-01

A/B/C 三級架構檢視一輪完成（A3-A5 對齊、B1-B7 靜默失效修補、C1-C6 效能與正確性強化）。

### Changed

- **C3 exchange-level dedup（`pipeline.py` + `core/config.py` + `schema_layer2.sql`）**：`training_samples` 新增 `source_exchange_ids` 欄位（JSON list of `exchanges.id`），`_PATH_A_V2_SQL` 改用 `json_each` 排除已被任一 v2 樣本涵蓋的 exchange.id，取代原本「session.uuid 整段排除」邏輯；同 session 加入新乾淨 exchange 後仍能再產出新樣本（保 SEAL「跳過失敗重試、保留成功 exchange」哲學）。`_run_exchange_ids_migration` backfill 既有 v2 樣本。
- **C4 多維採納啟發式（`layer_0_router/telemetry.py`）**：`infer_acceptance_from_text` 從「無否定即推定採納」二值化升級為 `AcceptanceSignal(accepted, rewrote, matched_keyword)` 三維結構；新增 `_REWRITE_KEYWORDS`（軟拒絕＋修正訊號）與 `_CONFIRM_KEYWORDS`（明確採納），未命中任何關鍵字回傳 `accepted=None` 保留 NULL，避免拉高 acceptance_rate false positive。`update_pending_decisions` 同步寫入 `user_rewrote`。
- **C5 排程併發保護（`core/background.py` + `core/config.py`）**：`setup_scheduler` 七個 job 統一加上 `max_instances=1` / `coalesce=True` / `misfire_grace_time=300`，避免 refiner 跨 tick 重疊或 backlog 雪崩；`init_layer2_db` 的 `sqlite3.connect()` 顯式 `timeout=30.0`，緩解 Layer 1 hook + Layer 2 排程同時寫入時的 SQLite lock contention。
- **C1 multi_judge early exit（`services/multi_judge.py`）**：`_collect_votes` 取得前兩票若一致（同為 approved 或 rejected），第三票必不影響結果，提前中止節省 1 次 Teacher API call（最多省 33% 配額）。
- **A3/A4/A5 spec ↔ code 對齊**：`CLAUDE.md` 多 Judge 流程與 Layer 1→2 橋接條件依 v2 實作改寫；`pipeline.py` 移除 `_extract_path_a` v1 死碼；`multi_judge.py` 刪除無人呼叫的 `score_sample` / `_pick_available_teacher` / 三個 score 常數，避免文件與行為長期分歧。

### Fixed

- **B1 `runner.py finished_at`**：寫入時用 `datetime.now(timezone.utc).isoformat()`，加 ISO 格式驗證測試（型別 + T 分隔符），確保 `fromisoformat` 後續解析不會靜默失敗。
- **B2 `dataset_formatter.py`**：`samples=[]` 改為 `raise ValueError`，避免空 file 被當成有效訓練集合送入 Layer 3；移除 `_calc_stable_target` 死碼。
- **B3 移除 `threshold` 參數（`runner.py` + `server.py` + `tests/layer3/test_runner.py`）**：`run_finetune_if_ready` 拿掉外部 `threshold=30` 注入，門檻完全由 `trigger_policy.should_trigger` 決定，避免 server 與 trigger 雙頭設定不一致。
- **B4 收緊 `try-except`（`pipeline.py` / `refiner_service.py` / `teacher_service.py`）**：原本的 `except Exception` 改為精確 exception type（`json.JSONDecodeError`、`urllib.error.URLError` 等），避免 KeyboardInterrupt / SystemExit 被默默吞掉。
- **B5 `compress_cold_data` 條件（`core/background.py`）**：以「session 無 30 天內 pending/raw 樣本」NOT EXISTS 取代原本的 approved-IN list，超過 30 天的卡死樣本視為永久失敗允許壓縮，避免 decay 永遠卡住。
- **B6 `lib/exchanges.py` SAVEPOINT**：批次 INSERT 用 SAVEPOINT 包覆，session 級寫入失敗時整段回滾，避免「半邊資料」污染 exchanges 語意層。
- **B7 集中式 alert（`core/background.py`）**：新增 `_send_alert(alert_type, message, context)` 統一出口，CRITICAL log 必出 + `SHIBA_ALERT_WEBHOOK` env 可選 POST；W4/W5 改走此通道。
- **C2 Ebbinghaus cadence 驗證（`tests/layer3/test_trigger_policy.py`）**：補測試確認 6 小時排程節奏覆蓋 `{1,2,4,7,15,30}` 日視窗 ±0.5 day 不漏不重。
- **C6 `teachers.keychain_ref` nullable（`schema_layer2.sql` + `core/config.py`）**：移除 NOT NULL 約束讓本地 Ollama teacher 不必偽造 keychain ref；`_run_keychain_nullable_migration` 用 table-rebuild dance 升級舊 DB。

### Tests

新增 11 tests：5 × 採納啟發式（C4）、3 × multi_judge early exit（C1）、3 × compress_cold_data B5 條件、1 × pipeline_v2 exchange-level dedup（C3）、1 × scheduler 併發保護（C5）、2 × Ebbinghaus 視窗（C2）、1 × runner finished_at ISO 格式（B1）。全 105 tests 通過（7 個 pre-existing 失敗為 teachers schema 遺漏 `daily_request_limit` × 6 + router mock unpack × 1，與本輪改動無關）。

## [1.1.2] - 2026-04-30

### Fixed

- **A2 `trigger_policy.py`**：signal C 分布偏移檢測的 `to_matrix` 函式改用 `json.loads` 讀取 embedding，對齊 `db.py upsert_exchange_embedding` 的 JSON text 寫入格式；原 `np.frombuffer(blob, float32)` 把 JSON bytes 當作 raw float32 解讀，輸出為亂數，signal C 永遠失效
- **A1 `schema.sql`**：`router_decisions` + `finetune_runs` 兩張跨層共享表的 DDL 集中至 `layer_1_memory/db/schema.sql`，確保全新部署時 `init_db()` 一次建齊，不再依賴 Layer 3 server 啟動或外部手動 migration
  - `router_decisions` 新增 3 個查詢索引（session_id / classification+user_accepted / created_at）
  - `finetune_runs` 補上 `status CHECK('pending','running','done','failed')` 契約約束
- **A1 `db.py init_db()`**：移除重複的 `router_decisions` inline migration（已由 schema.sql 統一管理）

## [1.1.1] - 2026-04-29

### Fixed

- **C1 `config.py` migration**：`_run_refiner_migration` 重建的 `training_samples_new` 補入 `layer1_bridge_v2` 與 `weight` 欄位，避免 migration 重跑時蓋掉正確 CHECK 導致 v2 樣本永遠無法入庫
- **W1 `runner.py`**：`finished_at="datetime('now')"` 字串字面量改為 Python 端 `datetime.now(timezone.utc).isoformat()`，修正 Ebbinghaus 間隔訓練因 `fromisoformat` 解析失敗而靜默失效
- **W2 `pipeline.py _has_error_tool`**：改傳 `conn + msg_id`，查 `tool_executions` 精確比對 `tool_use_id`，避免 session 有任何工具錯誤就污染全部 exchange
- **W3 `init_db()` + `server.py`**：`init_db()` 補建 `router_decisions` 表；Layer 3 server startup 補建 `finetune_runs` 表，確保新環境初始化不因表不存在崩潰
- **W4 `background.py`**：extraction job 結束後查逾 24h raw 樣本，非零時 `logger.warning`，方便及早發現 refiner/Ollama 離線造成的鏈路斷裂
- **W5 `background.py`**：extraction 完成後對新 raw 樣本補一次 `sync_sample_weights`，修正 stop_hook 執行時樣本尚未存在導致採納 weight 回饋白白浪費

## [1.1.0] - 2026-04-29

### Added

- **Layer 1 — exchanges 語意層（commit 7091d4e）**
  - 新增 `exchanges` + `exchange_messages` 兩張語意表，記錄每個四步循環（user → tool → tool_result → final_assistant）的完整邊界與預計算欄位（`has_error` / `has_final_text` / `status`）
  - `lib/exchanges.py`：`ExchangeBuilder` state machine，`backfill_exchanges()` 批次補填
  - `hooks/stop_hook.py` 整合：每次 session 結束自動寫入 exchanges
  - backfill 驗證：17,790 筆 exchange，`status='completed'` 率 > 95%

- **Layer 2 — Path A v2（exchanges 語意層，commit ba0ec43）**
  - `extraction/pipeline.py`：新增 `run_extraction_v2` / `_extract_path_a_v2` / `_materialize_exchange_v2` / `_resolve_user_text`（raw_content zlib fallback）
  - 直接讀 `exchanges` 表取代舊版 state machine，解決三個結構性問題：邊界判定脆弱、錯誤標記過粗、語意層重複實作
  - `background.py` + `routes_dataset.py`：caller 切換至 `run_extraction_v2`（source=`layer1_bridge_v2`）
  - `schema_layer2.sql`：`training_samples.source` CHECK 加入 `layer1_bridge_v2`
  - `tools/compare_extraction.py`：A/B 對比腳本（純讀）
  - `tests/layer2/test_pipeline_v2.py`：9 tests（block1/2、has_error、decay_score、去重、resolve_user_text）
  - 舊版 `run_extraction` / `_extract_path_a` 保留不動，Path B 不受影響

## [1.0.0] - 2026-04-25

### Added

- **Phase 3 — Vue 3 + Vite 前端 bootstrap**
  - `frontend-vue/`：Vue 3 + TypeScript + Vite 8 + vue-router 4 + Pinia
  - `tailwind.config.js`：全部 CSS 設計 token 轉換（colors / fontFamily / fontSize / borderRadius / boxShadow）
  - `src/style.css`：Google Fonts（Noto Sans TC / IBM Plex Mono / Space Grotesk）+ Tailwind base

- **Phase 4 — 元件搬遷（React CDN → Vue 3 SFC）**
  - 10 shared 元件：Badge、StatusDot、QuotaBar、DataTable、DetailPanel、SectionHeader、StatCard、Btn、Pagination、DateFilterBar
  - 2 圖表元件：MemoryBarChart（Chart.js stacked bar）、RouterDonut（doughnut）
  - Sidebar（vue-router-link + backend 狀態探測）
  - 4 Phase views：PhaseRouter（決策紀錄 + donut + 對話脈絡）、PhaseMemory（sessions + 趨勢圖）、PhaseTeachers（師父配額 + 投票）、PhasePipeline（flow 動畫 + Ollama 資源）
  - `src/api/client.ts`（native fetch wrapper，base `/api/v1`）、`src/api/dateFilter.ts`（共用日期 QS 建構器）

- **Phase 5 — docker-compose 整合**
  - `frontend-vue/Dockerfile`：multi-stage（node:20-alpine build → nginx:alpine serve）
  - `frontend-vue/nginx.conf`：SPA fallback + `/api/` proxy → backend:8000
  - `docker-compose.yml`：frontend:9590 + backend:8000（internal） + `./data` / `./backups` volume

- **Phase 6 — Layer 3 獨立服務**
  - `layer_3_pipeline/server.py`：FastAPI :8001，`/health` / `/trigger/{block}` / `/runs`
  - `com.shiba.layer3.plist` + `setup_layer3_launchd.sh`：launchd 常駐安裝腳本
  - Layer 2 `routes_finetune.py` + `background.py`：direct import → HTTP POST（`httpx`）至 Layer 3；Layer 3 掛掉時 log warning 不拋異常
  - `requirements.txt` 補 `httpx==0.28.1`

- **Phase 7 — 收尾**
  - `scripts/db_backup.sh`：SQLite `.backup` 確保 WAL 一致性，路徑從 `config/shiba.yaml` 讀取
  - `frontend/_legacy_react_cdn/`：舊 React CDN 原始碼重命名保留

## [0.9.0] - 2026-04-24

### Added

- **Phase 1 — 設定集中化（Vue 3 + docker-compose 重構前置作業）**
  - `config/shiba.yaml`：全專案唯一 source of truth（paths / services / runtime）
  - `shiba_config.py`（專案根）：frozen dataclass singleton，依 `SHIBA_RUNTIME` env 自動擇一 host/docker URL
  - `data/`、`backups/` 骨架（`.gitkeep` 占位，DB/log/queue 依 `.gitignore` 排除）
  - Layer 1 hooks 檔頭 SHIBA_PROJECT_ROOT env pattern：同時支援專案原位與 `~/.claude/plugins/local-brain/` plugin 同步兩種部署

- **Phase 0 — 路由層儀表板後端（前端支援端點）**
  - `routes_router.py`：`/api/v1/router/decisions`（日期篩選 + 分頁）、`/status`（Ollama 連線探測）、`/decisions/{id}/adopt`（採納更新）
  - `routes_memory.py`：`/api/v1/memory/sessions`（日期篩選 + 分頁）、`/sessions/{id}/messages`、`/stats`
  - `routes_finetune.py` 擴充：`/trigger-status`（各 block 距觸發條件距離）、`/ollama-status`
  - `main.py` 啟用 CORS middleware + 註冊新 router

### Changed

- **Phase 1 呼叫點改寫（15+ 處硬寫路徑 → `CONFIG`）**
  - Layer 0：`router/classifier/compressor/telemetry.py` 的 `OLLAMA_BASE`、`DB_PATH` 讀 `CONFIG`
  - Layer 1：`lib/db.py`、`lib/embedder.py` 改讀 `CONFIG`；`config.yaml` 瘦身只留邏輯調參（rag / decay / event_importance / logging.level）
  - Layer 2：`core/config.py`、`extraction/dataset_formatter.py`、`scripts/brain_status.py`、`scripts/setup_teachers.py` 全部改讀 `CONFIG`
  - Layer 3：`db.py`、`gatekeeper.py` 改讀 `CONFIG`；`runner.py` 的 `_DEFAULT_WORK_DIR` 刻意保留硬寫並加註解（MLX 訓練工作區為 Layer 3 私有實作細節，不跨 layer）

- **資料遷移**：`~/.local-brain/shiba-brain.db{,-wal,-shm}` + `logs/` + `queue/` → 專案 `./data/`（36 sessions 保留、integrity ok）

### Fixed

- 清除搬檔後一個 1.5 個月前遺留的 ghost uvicorn process（讀舊 config.py 把 `~/.local-brain/shiba-brain.db` 重建為 4096 byte 空殼）

## [0.8.0] - 2026-04-21

### Added

- **Phase A — 管線穩定性**
  - `layer_2_chamber/scripts/run_scorer.py`：獨立 Scorer CLI，直接呼叫 `score_pending_samples`，不依賴 FastAPI / APScheduler，支援批次輪詢直到配額耗盡
  - `layer_2_chamber/scripts/setup_launchd.sh`：產生並載入 `com.shiba.layer2` LaunchAgent（KeepAlive + RunAtLoad，log → `~/.local-brain/layer2.log`）

- **Phase B — DB Schema 擴充**
  - `teachers` 表新增 8 欄位：`daily_request_limit`、`daily_token_limit`、`quota_reset_period`（`daily`/`monthly`/`none`）、`requests_today`、`input_tokens_today`、`output_tokens_today`、`quota_exhausted_at`、`quota_exhausted_type`
  - `teacher_usage_logs` 表新增 `input_tokens`、`output_tokens` 分拆欄位（`tokens_used` 保留為合計）
  - `config.py` 新增 `_run_token_quota_migration`（幂等，lifespan 自動執行）

- **Phase C — Teacher Service 升級**
  - C1 雙維度配額：`_pick_available_teacher` 新增 `requests_today >= daily_request_limit` 與 `token 總量 >= daily_token_limit` 兩層排除
  - C2 Input/Output 分拆：`_call_gemini_rest` 改用 `promptTokenCount` / `candidatesTokenCount`；`_call_openai_compat` 改用 `prompt_tokens` / `completion_tokens`；簽名改為回傳 `(text, input_t, output_t, status)`
  - C2 `_log_usage` 統一至 `_call_teacher` 內部處理，新增 `_record_teacher_usage`（更新 `requests_today` / `input_tokens_today` / `output_tokens_today`）
  - C3 `keychain_ref = NULL` 支援：本地 Qwen 跳過 Keychain，傳入 dummy `"none"` key
  - 新增 `_mark_quota_exhausted`（記錄耗盡時間與類型）、`call_teacher_for_test`（測試用，不計入 usage log）
  - `multi_judge.py` 移除重複的 `_log_usage` 呼叫（已由 `_call_teacher` 內部統一處理）

- **Phase D — 新 Teacher 預填**
  - `setup_teachers.py` 擴充 4 個新 Teacher：Grok 3 Mini（priority=2）、GitHub GPT-4o-mini（priority=3）、Mistral 7B（priority=4）、Local Qwen 7B（priority=5，keychain_ref=NULL）
  - 現有 Gemini Flash / Flash-Lite 更新 `daily_request_limit` 欄位
  - 新增 `--dry-run` 參數（只印出將插入的資料，不寫入 DB）

- **Phase E — Teacher 前端測試頁**
  - `POST /api/v1/teachers/{id}/test`：發送任意 prompt，回傳 response + input/output tokens + latency_ms
  - `GET /teacher-test`：返回 `static/teacher_test.html`（Tailwind CSS CDN + Test All 並行測試）

- **Phase F — 冷啟動品質改善**
  - F1 Few-shot 校準：`_SCORE_PROMPT` 嵌入 YAML 校準範例（3 個 9-10 分 + 3 個 2-4 分，針對 code/debugging/git_ops）
  - F2 動態 LoRA rank：`mlx_trainer.py` 依 `approved_count` 動態設定 rank（<50 → rank=8 防過擬合；≥50 → rank=16）；`runner.py` 傳入 `approved_count`
  - F3 外部資料集：`dataset_formatter.py` 新增 `_load_external_dataset`，從 `~/.local-brain/external_dataset/*.jsonl` 讀取 Alpaca JSONL，注入 10% 槽位；目錄不存在靜默跳過

- **Phase G — 診斷 CLI**
  - `layer_2_chamber/scripts/brain_status.py`：一鍵顯示 Pipeline（pending/approved/block 進度）、Teacher 配額狀態（含 token 用量）、外部資料集配置狀況

### Changed

- `background.py` `_reset_daily_limits`：每日重置擴充至清除 `requests_today`、`input_tokens_today`、`output_tokens_today`、`quota_exhausted_at`、`quota_exhausted_type`
- `routes_teachers.py` `_LIST_SQL`：改用 `requests_today` 欄位計算配額剩餘，支援新的 `daily_request_limit` / `daily_token_limit` 欄位

---

## [0.7.0] - 2026-04-21

### Added

- **Teacher API 配額監控與管理**
  - `teachers` 表新增 `is_daily_limit_reached` 欄位（標記當日額度耗盡）
  - `teacher_usage_logs` 表新增 `response_status` 欄位（`success` / `quota_exceeded` / `error`）
  - `config.py` 加幂等 migration（`_run_quota_migration`），lifespan 啟動時自動補欄位
  - `_call_gemini_rest` / `_call_openai_compat` 改回傳 `(text, tokens, status)` tuple，捕捉 HTTP 429 / RateLimitError
  - `_call_teacher` 接收 `conn` + `sample_id`，quota_exceeded / error 皆內部寫 log，成功回傳 `tokens_used`
  - `_mark_daily_limit_reached`：helper，標記 teacher 並 WARNING log
  - `is_quota_available` 計數達限時自動呼叫 `_mark_daily_limit_reached`
  - `_pick_available_teacher` 硬性排除 `is_daily_limit_reached=1` 的 teacher
  - `_log_usage` 新增 `tokens_used` / `response_status` optional 參數
  - `background.py` 新增 UTC 00:05 每日重置排程（`_reset_daily_limits`）
  - `routes_teachers.py`：`GET /api/v1/teachers`（LEFT JOIN 當日用量）/ `PATCH /api/v1/teachers/{id}`（修改 daily_limit / is_active）

## [0.6.0] - 2026-04-20

### Added

- **P0-1 Router Telemetry**（採納率追蹤）
  - `layer_0_router/telemetry.py`：`record_decision` / `update_acceptance` / `infer_acceptance_from_text` / `sync_sample_weights`
  - `router_decisions` 表（schema_layer3.sql migration）
  - `router.py` 加 telemetry 寫入與計時，`session_start_hook` 傳入 `session_id`
  - `stop_hook` 新增 `_infer_router_acceptance()`：對話結束後自動語意比對採納狀態

- **P0-2 Shadow Gate**（A/B 上線守門員）
  - `layer_3_pipeline/gatekeeper.py`：本地 Qwen 自評零成本，bootstrap 95% CI + latency ratio 三條件
  - `runner.py` 在 `push_to_ollama` 前插入 gate，未通過回傳 `gate_rejected`

- **P1-1 動態訓練觸發**（取代固定 approved≥30）
  - `layer_3_pipeline/trigger_policy.py`：Ebbinghaus 壁鐘間隔 / 採納退化 / embedding 分布偏移 三信號
  - `runner.py` 改用 `should_trigger()` 決定是否訓練

- **P1-2 多 Judge 投票**（SEAL ReSTEM^EM 精神）
  - `layer_2_chamber/backend/services/multi_judge.py`：三方投票，3票=1.0 / 2票=soft 0.5 / ≤1票=rejected / Shiba採納覆蓋
  - `background.py` 評分排程改用 `multi_judge_score`

- **P1-3 隱性標籤 weight**
  - `training_samples.weight` 欄位（migration, DEFAULT 1.0）
  - `sync_sample_weights`：stop_hook 採納後自動同步 weight（1.0/1.5/2.0）
  - `dataset_formatter.py`：Ebbinghaus 分桶 replay + weight 展開（soft 0.5/正常/×2/×3）

## [0.5.0] - 2026-04-19

### Added

- **Layer 0 路由層**
  - `layer_0_router/classifier.py`：Gemma E2B（gemma3:2b）分類任務 local/claude，ROUTER_TIMEOUT=30s（含 model swap）
  - `layer_0_router/compressor.py`：Gemma E4B（gemma3:4b）壓縮長 RAG context
  - `layer_0_router/router.py`：主協調器，local → compress → Qwen → 注入 🤖 建議；任何失敗靜默 fallback
  - `session_start_hook.py` 整合：router 結果 + RAG context 合併注入
  - 9 個單元測試，全數通過

## [0.4.0] - 2026-04-19

### Added

- **Layer 3 Fine-tuning Pipeline** 全自動化
  - `layer_3_pipeline/db.py`：`finetune_runs` 表 CRUD
  - `layer_3_pipeline/mlx_trainer.py`：呼叫 `mlx_lm.lora` 執行 LoRA 訓練
  - `layer_3_pipeline/gguf_converter.py`：`mlx_lm.fuse` + `convert_hf_to_gguf.py` 轉換 GGUF
  - `layer_3_pipeline/ollama_updater.py`：`ollama create` 更新本地模型
  - `layer_3_pipeline/runner.py`：主協調器，approved≥30 自動觸發完整 pipeline
  - `layer_2_chamber/backend/api/routes_finetune.py`：手動觸發 API（POST /trigger/{block}、GET /runs）
  - `background.py` 新增 `finetune_check` 排程（每 6 小時）
  - `~/.local-brain/schema_layer3.sql`：`finetune_runs` 表定義
  - 11 個單元測試，全數通過

### Fixed

- `stop_hook.py`：新增 session 層級 embedding 補捕，預期 capture 率大幅提升（原 4/15 sessions）
- `rag.py`：cosine similarity 門檻 0.5 → 0.35，提高 RAG 召回率
- `teacher_service.py`：Gemini REST 加 `responseMimeType: application/json`，修復評分 JSON 解析錯誤

## [0.1.0] - 2026-04-17

### Added

- **Layer 1 記憶層**核心實作
  - `layer_1_memory/lib/parser.py`：解析 Claude Code JSONL session 檔案（branch 追蹤、tool_use 偵測）
  - `layer_1_memory/lib/classifier.py`：規則型事件分類器（7 種 event_type）
  - `layer_1_memory/lib/db.py`：SQLite 連線管理、schema 初始化、migration 機制
  - `layer_1_memory/lib/rag.py`：FTS5 記憶查詢與 RAG context 格式化
  - `layer_1_memory/hooks/stop_hook.py`：Claude Code Stop Hook，背景 spawn 同步
  - `layer_1_memory/hooks/sync_session.py`：背景同步主邏輯（parse → classify → upsert DB）
  - `layer_1_memory/hooks/session_start_hook.py`：SessionStart Hook，RAG 注入歷史 context
  - `layer_1_memory/db/schema.sql`：四層 schema（projects / sessions / branches / messages + FTS5）
  - `layer_1_memory/config.yaml`：路徑、閾值設定
  - `layer_1_memory/setup.sh`：一鍵部署腳本（venv、DB 初始化、settings.json hooks 寫入）
- **單元測試** `tests/memory/`：db / parser / classifier / rag 共 18 個測試案例，全數通過

### Changed

- **Layer 1 記憶記錄完整性與成本追蹤補強**
  - 修復 `tool_result` 遭到 `parser.py` 拋棄的問題。
  - `layer_1_memory/db/schema.sql`：在 `messages` 表新增了 8 個欄位。包含 `raw_content` TEXT 欄位，用以保存未經過濾的最原始 JSON 結構；以及 7 個量測數值的欄位：`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `char_count`, `byte_count`, `encoding`，全面涵蓋成本與流量追蹤。
  - `layer_1_memory/lib/parser.py`：`_parse_entry` 現在會攔截 `message["content"]` 以及 `message["usage"]` 將其拆解、並且透過 python 計算物理位元組字元數。
  - `layer_1_memory/lib/db.py`：在 `init_db()` 加入 7 項新欄位新增的 Migration 控制；並擴充 `insert_message`。
  - `layer_1_memory/hooks/stop_hook.py`：串接流量追蹤參數至資料庫 `insert_message` 儲存階段。
  - `tests/memory/test_parser.py`：新增驗證單元測試，確保字元數、Token 消耗能被準確萃取與計算。
  - `tests/memory/test_classifier.py`：補上改版遺失的占位符。

- **Layer 1 生命週期與效能優化 (延遲壓縮與工具正規化)**
  - **時間戳與模型紀錄**：於 `messages` 分別新增 `message_time`, `model_name`，讓儀表板可精算真實時間與費率。
  - **工具紀錄正規化 (`tool_executions` 表)**：成功從 `raw_content` 獨立拆分，並使用 `(tool_name, is_error)` 建立索引，方便未來 Layer 2 背景程式毫秒級掃描出問題的 `Bash` 指令。
  - **Application-Level 即時壓縮機制**：引入 Python `zlib`。在寫入 DB 前，如果分析到 `output_log` 或 `raw_content` 的位元組超過 `1024 Bytes`，會直接啟動 `.compress()` 包裝成 `BLOB` 寫入。完全不拖慢背景掛勾且解決硬碟未來爆滿問題，並設有 `is_compressed=1` 的彈性旗標。
