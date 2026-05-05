# 2026-04-25 Codex 系統分析與改善建議

## 分析目的

本文件整理對 `shiba-fine-tuning-project` 的靜態系統分析結果，重點放在：

- 四層資料流是否符合 `AGENTS.md` 的設計
- 目前閉環是否已真正封口
- 哪些地方已具備可行性
- 哪些地方存在高風險斷點，適合後續交由 Claude 再審視是否需要調整

本次分析不涉及任何程式碼邏輯修改，只根據目前 repo 內容做架構與資料流檢查。

---

## 一、總結判斷

整體判斷可歸納為一句話：

> 架構方向正確，主流程已大致成形，但資料層與閉環契約尚未完全封口。

也就是說：

- Layer 0 → Layer 1 → Layer 2 → Layer 3 的主資料流概念是成立的
- 多數模組之間已能看出清楚的責任分工
- 但若以「是否嚴格符合設計規範」來看，仍有幾個關鍵落差
- 這些落差主要集中在 schema 契約、橋接條件、評分流程一致性、以及 Layer 3 訓練記錄可信度

如果目標是 demo 級閉環，現狀是可行的。  
如果目標是長期可維護、可持續自我進化的正式系統，則目前仍需要補強資料契約與流程一致性。

---

## 二、符合設計的部分

### 1. 全專案設定集中化方向正確

`config/shiba.yaml` 與 `shiba_config.py` 已經形成明確的 source of truth，這一點對多 layer 共用 DB/URL/path 很重要。

目前優點：

- DB 路徑、logs、queue、external dataset 已集中
- host / docker runtime URL 切換邏輯清楚
- 呼叫端可統一透過 `CONFIG` 取得設定

這部分是目前專案中最穩定、最像正式系統底座的設計之一。

### 2. Layer 1 記憶層資料流完整度高

Layer 1 的資料流大致如下：

1. `session_start_hook.py`
   - 啟動時做 RAG 記憶召回
   - 可整合 Layer 0 router 建議
2. `stop_hook.py`
   - session 結束後解析 transcript
   - 寫入 session / branch / messages / tool_executions / sessions_fts
   - 補寫 exchange embeddings
   - 推定 router acceptance
3. `rag.py`
   - 支援 vector search + FTS fallback

這條線已經具備「可持續累積經驗」的基本骨架。

### 3. Layer 2 與 Layer 3 主鏈已存在

目前可以看出一條明確的後段閉環：

1. Layer 2 extraction 抽樣
2. refiner 做 PII scrub / instruction 自包含化
3. judge 評分
4. dataset export
5. Layer 3 trigger
6. MLX LoRA 訓練
7. GGUF 轉換
8. Shadow gate
9. Ollama 更新

也就是說，閉環在程式結構上不是缺席，而是「部分段落仍有契約不一致」。

---

## 三、資料流不完全符合設計的關鍵點

以下是本次分析中最值得注意的資料流斷點。

### 1. `router_decisions` 與 `finetune_runs` 缺少明確正式 schema 來源

README 把這兩張表列為核心主表：

- `router_decisions`
- `finetune_runs`

但在目前 repo 內能直接看到的 schema 中：

- Layer 1 schema 沒有這兩張表
- Layer 2 的 init/migration 也沒有把它們列入正式初始化清單
- Layer 3 程式卻直接依賴 `finetune_runs`
- Layer 0 telemetry 與 Layer 2/3 API 也直接依賴 `router_decisions`

這代表：

- 設計上這兩張表非常重要
- 但 repo 內資料庫初始化契約沒有完整體現
- 若在全新環境部署，閉環很可能依賴外部歷史 DB 狀態才能成立

這是目前最優先的系統性風險之一。

### 2. Layer 1 → Layer 2 自動橋接條件與設計文件不一致

你在 `AGENTS.md` 定義的自動橋接條件是：

- `event_type ∈ {git_ops, terminal_ops, code_gen}`
- `has_tool_use = true`
- `exchange_count ≥ 2`

但目前 `pipeline.py` 的實作是：

- `_BRIDGE_EVENT_TYPES` 包含 block1 與 block2 全部事件
- session-level 並沒有嚴格檢查 `has_tool_use=true`
- 因此 `debugging` / `architecture` / `knowledge_qa` / `fine_tuning_ops` 也可能直接走 bridge

這表示：

- 程式正在實作一個比設計更寬鬆的橋接策略
- 若這是刻意演進，則文件應同步更新
- 若不是刻意演進，則資料集來源會偏離原始訓練哲學

### 3. Judge 流程存在雙軌，正式主流程不夠單一

設計規格寫的是：

- Gemini 2.5 Flash 初裁
- 8 分以上 approved
- 6-7 分送第二裁判
- 小於 6 rejected

但實際程式中同時存在兩條 judge 路徑：

1. `teacher_service.py`
   - 初裁 + 第二裁判
2. `multi_judge.py`
   - 最多三方投票
   - 還會把 router acceptance 當高價值訊號覆蓋 judge 結果

而排程實際使用的是 `multi_judge.py`。

這代表：

- 文件描述的是單一路徑
- 實作卻是另一套更複雜的路徑
- 若沒有正式定義哪一條才是 production truth，未來很容易出現「文件與資料分佈不一致」

### 4. `teachers.keychain_ref` 與本地 Teacher 備援設計不自洽

設計上你希望有：

- 免費 teacher pool
- 最後備援可用本地模型

但 schema 目前定義：

- `teachers.keychain_ref TEXT NOT NULL`

而程式邏輯卻允許：

- `keychain_ref is None` 代表本地 teacher，不需 key

這種情況下，如果真的要以 DB 正規方式建立本地 teacher：

- schema 與 service 行為會衝突

這雖不是最致命問題，但屬於典型的資料契約不一致。

### 5. 分布偏移信號（signal C）極可能失真或失效

`exchange_embeddings` 寫入時，embedding 是以 `json.dumps(list[float])` 存入。

但 `trigger_policy.py` 在 drift 檢測時，卻以：

- `np.frombuffer(blob, dtype=np.float32)`

去解析該欄位。

這兩邊的格式契約明顯不一致：

- 一邊像 JSON text
- 一邊像 raw float32 bytes

結果會是：

- drift 信號 C 無法正確反映真實向量分布
- 觸發策略可能因此失準

### 6. Layer 3 訓練 run 的記錄可信度不足

目前 Layer 3 有幾個值得注意的問題：

#### (a) `threshold` 參數名存實亡

`server.py` 呼叫：

- `run_finetune_if_ready(..., threshold=0)`

但 `runner.py` 實際只看 `should_trigger()`，沒有使用這個 `threshold` 參數。

這代表 API 語意與實際執行並不一致。

#### (b) `finished_at="datetime('now')"` 會被當字串存入

`update_run()` 是參數化 UPDATE，不會把這段字串當 SQL function 執行。

因此最終資料可能不是實際 timestamp，而是 literal string。

這會影響：

- trigger status 顯示
- Ebbinghaus interval 計算
- 任何依賴 run 完成時間的後續分析

#### (c) `get_last_run_id()` 並未真正表示「上次訓練用到哪裡」

它目前只是：

- 取同 block 所有 `done run` 關聯條件下的 `MAX(training_samples.id)`

但 `finetune_runs` 本身沒有明確記錄：

- 本次訓練實際涵蓋哪些 sample
- dataset snapshot 邊界是什麼

因此 incremental dataset export 的基準其實是不穩的。

### 7. extraction 的錯誤過濾太保守，可能污染樣本品質

`_has_error_tool()` 的現況是：

- 只要 session 內有任何 error tool id
- 後續任何帶 tool_use 的 assistant message 幾乎都可能被視為有錯

這會導致：

- path A 合格樣本被過度排除
- session 內部分成功 exchange 也被一併汙染
- block1 訓練資料的抽取準確率下降

### 8. Router 採納推定邏輯過於粗糙

目前 acceptance inference 大意是：

- 有否定關鍵字 → rejected
- 否則保守直接當 accepted

這對 demo 足夠，但對後續 `weight` 與 fine-tuning 信號品質來說過於粗糙，可能造成：

- 被改寫很多但沒明講否定的結果，也被算成 accepted
- 實際應學習的失敗樣本被弱化

---

## 四、資料流層面的整體判讀

如果用一句比較精確的話來描述目前狀態：

> 邏輯上的閉環大多已接上，但資料契約的閉環還沒完全接上。

這種系統在早期很常見，特徵是：

- 每一層看起來都「有東西在做事」
- 單點模組也都有其合理性
- 但跨 layer 的共同真相還不夠強

以目前專案來看，共同真相最需要補強的是：

1. DB schema 是不是完整反映所有核心表
2. 哪一條 judge 流程才是 production truth
3. 自動橋接條件是不是與 spec 完全一致
4. Layer 3 run metadata 能不能支撐增量訓練與 trigger 計算

---

## 五、優先改善建議

以下建議按優先度排序，偏向「最值得先讓 Claude 再審視」的方向。

### Priority A：先補齊資料契約

最建議 Claude 優先檢查與處理：

1. `router_decisions` 正式 schema / migration 是否存在且可在全新 DB 建立
2. `finetune_runs` 正式 schema / migration 是否存在且可在全新 DB 建立
3. Layer 2 / Layer 3 啟動時是否能自動保證這兩張表存在

原因：

- 這是所有閉環資料能否可靠落地的前提
- 若缺這一層，其餘分析、trigger、dashboard 都會建立在脆弱基礎上

### Priority B：統一 Layer 1 → Layer 2 bridge 規則

需要先決定一件事：

- 到底要堅持 spec，只讓 block1 類事件自動橋接
- 還是接受目前實作，讓 block2 事件也能進 bridge

只要這件事沒有定版，training_samples 的來源分佈就不會穩定。

### Priority C：定義唯一 Judge 正式主流程

建議 Claude 明確判斷：

- `teacher_service.score_sample()` 是正式主流程
- 還是 `multi_judge_score()` 才是正式主流程

若三方投票才是正式策略，則應：

- 更新文件
- 確認 dashboard、manual scoring、排程、測試都以同一規則為準

### Priority D：修正 embedding 儲存格式契約

這部分建議 Claude 聚焦在：

- `exchange_embeddings.embedding` 的實際資料型別
- drift signal 的讀法是否正確
- 是否要統一成 JSON text 或 float32 BLOB

否則 signal C 幾乎不值得信任。

### Priority E：強化 Layer 3 run metadata

這部分若 Claude 要動，最值得審視的是：

- `finetune_runs` 是否需要記錄 sample id range / dataset snapshot hash
- `finished_at` 是否正確寫入真正時間
- `threshold` 參數是否仍有存在必要
- `get_last_run_id()` 是否應改成更可信的 dataset 邊界紀錄

這會直接影響：

- 增量訓練是否可信
- Ebbinghaus replay 是否可信
- trigger status 儀表板是否可信

### Priority F：改善 acceptance 與 sample weight 的品質

若後續要提升資料品質，Claude 可以再評估：

- acceptance inference 是否應改成更結構化的判定
- `user_rewrote` 是否該實際納入
- 是否區分「部分採納」與「完全採納」

這會讓 `weight` 從 demo heuristic 走向更可靠的學習信號。

---

## 六、目前可行性評語

### 若目標是短期驗證

目前架構已足以支撐：

- 對話記憶累積
- 訓練樣本抽取
- 基本 teacher 評分
- 觸發訓練與部署概念驗證

也就是說，系統作為原型或研究型實驗平台，是有可行性的。

### 若目標是長期穩定運轉

目前最需要補的是：

- schema 完整性
- 流程單一真相
- metadata 可追溯性

否則系統雖然表面上能跑，但數據是否可信、觸發是否合理、訓練是否真正對應既定樣本，會越來越難驗證。

---

## 七、給 Claude 的審視方向建議

如果後續要請 Claude 幫忙判斷是否要調整，我建議可以請它優先回答以下問題：

1. `router_decisions` 與 `finetune_runs` 在全新資料庫初始化時是否真的可被可靠建立？
2. Layer 1→2 自動橋接是否應嚴格維持 block1 only，還是應升級設計文件承認 block2 也可橋接？
3. Judge production path 應該保留雙軌，還是統一成單一路徑？
4. `exchange_embeddings.embedding` 的儲存格式是否足以支撐目前 drift 檢測？
5. `finetune_runs` 現行欄位是否足夠支撐增量 dataset export 與 trigger 計算？
6. acceptance / weight 機制是否需要從 keyword heuristic 升級？

---

## 八、最終結論

最終結論如下：

- 目前專案的系統架構方向是合理的
- 主資料流已具備閉環雛形
- 但若以「是否完全符合既定設計」來看，答案仍是否定的
- 真正的差距不在單一模組，而在跨 layer 的資料契約與流程真相尚未完全一致

因此，最適合的下一步不是立刻大改，而是先由 Claude 針對：

- schema 契約
- bridge 規則
- judge 主流程
- Layer 3 run metadata

做第二輪精查，再決定哪些地方值得正式調整。

---

## 補充說明

本次分析未修改任何既有程式碼邏輯。  
另外，原本嘗試補跑部分測試作為旁證，但目前環境缺少 `pytest`，因此本文件結論主要依據：

- repo 內靜態程式結構
- schema 與 migration 設計
- 背景排程與 API 串接邏輯
- 現有測試內容本身所反映的假設

---

## 九、從成長角度看，這個專案是否仍有很大改善空間？

答案是有，而且空間不小。

這個專案目前最值得肯定的地方，不是單一功能做得多完整，而是它已經具備一個相當完整的自我進化骨架：

- 有路由層
- 有記憶層
- 有樣本抽取與評分層
- 有 fine-tuning pipeline
- 有部署與 gate 機制

這代表它已經不是單點工具，而是一個正在形成中的「學習型系統」。

也因此，下一階段的成長重點不應只是單純加功能，而應該聚焦在三件事：

1. 讓資料更可信
2. 讓閉環更穩定
3. 讓系統更可觀測、更可演進

如果用比較直白的話說：

> 這個專案已經從 prototype 走到 system prototype，但還沒到 reliable learning system。

---

## 十、如果從我的角度來規劃，我會怎麼做

### 1. 先補強系統可靠性，而不是先追求更多功能

如果是我接手後續演進，我最先做的不會是新增更多 teacher 或更快訓練，而是先把跨 layer 的共同真相固定下來。

我會優先補強：

- 核心表 schema / migration 完整性
- bridge 規則與設計文件的一致性
- judge production path 單一化
- embedding 儲存格式與 trigger signal 一致性
- finetune run metadata 的可追溯性

原因很簡單：

- 如果資料來源本身不穩
- 如果 trigger 依據有部分失真
- 如果 run 記錄無法精準回溯

那麼後續所有模型升級、weight 調整、teacher 擴充，都可能建立在不夠可信的訊號上。

也就是說，這個階段最值得投資的不是「功能數量」，而是「學習品質的底座」。

### 2. 把 Layer 1 記憶層升級成真正可管理的記憶系統

目前 Layer 1 已經可以：

- 存記憶
- 搜記憶
- 注入記憶

但從我的角度看，它還比較像「記錄庫 + 檢索器」，還沒有完全長成「可治理的記憶系統」。

如果要往前推，我會希望 Layer 1 再增加這幾種能力：

- 記憶去重與聚類：避免同類經驗反覆累積卻沒有壓縮
- 記憶分級：短期操作記憶、長期技巧記憶、專案規則記憶分層管理
- 記憶可信度分數：根據採納率、重複成功次數、時間衰減形成信心分數
- 記憶摘要卡：把多次相似操作壓縮成可注入的「經驗卡」
- 記憶失效機制：被更好做法取代的記憶自動降權，而不是只靠時間衰減

這樣 Layer 1 就不只是「回想過去」，而是開始具備「整理經驗」的能力。

### 3. 把 Layer 2 從樣本工廠升級成資料品質中台

我認為這個專案未來最關鍵的價值之一，其實會落在 Layer 2。

因為真正決定 fine-tuning 品質的，往往不是 trainer 本身，而是：

- 樣本從哪來
- 為什麼被留下
- 哪些該進、哪些不該進
- 哪些是長期穩定技巧，哪些只是一次性的專案情境

如果由我規劃，我會讓 Layer 2 更像 dataset refinery，而不只是 extraction + scoring。

我會新增或強化：

- 樣本 lineage：每筆 sample 可反查 session / message / tool execution / judge 結果
- 樣本版本化：同一樣本被 refine、重判、人工覆核時保留版本脈絡
- failure taxonomy：對 rejected 樣本做原因分類，而不是只有低分
- hard-negative 池：保留高相似但錯誤的樣本，供未來偏好對比或拒答策略
- dataset health dashboard：追蹤來源分佈、block 分佈、judge disagreement、重複率、PII 風險
- 樣本標籤細化：區分「長期規則」「專案特例」「一次性操作」

如果這一層成熟，未來從 7B 升到 32B 時，系統會更容易維持資料品質。

### 4. 重新定義 Layer 0 Router，讓它成為策略層而不只是分流器

目前 Layer 0 的角色比較接近：

- local / Claude 二選一路由

這是好的起點，但我覺得它未來可以再升級成「策略層」。

也就是不只是問：

- 這題給誰答？

而是進一步問：

- 這題值不值得讓本地模型碰？
- 這題的風險高不高？
- 這題若讓本地模型先做，失敗成本是否可接受？

如果由我延伸，我會想加：

- 任務風險等級：low / medium / high
- 可逆性判斷：可回滾操作才優先 local 試做
- 路由置信度輸出：不只是 `local/claude`，還要有 confidence
- fallback 策略：local 失敗後如何最小成本轉交 Codex
- 採納之外的評估指標：是否增加來回輪數、是否提高修正成本

這會讓 Layer 0 從分類器升級成任務策略引擎。

### 5. Layer 3 不只是更會訓練，而是更會評估

如果問我最希望 Layer 3 補什麼，我的答案不是「更多訓練」，而是「更好的 evaluation」。

因為對這類系統來說，真正困難的不是跑出 adapter，而是回答：

- 這次訓練後到底有沒有更好？
- 是哪一類能力變好？
- 有沒有引入新的退化？

所以我會優先加強：

- 固定 benchmark set：從真實歷史任務抽出穩定評測集
- block1 / block2 分離評估報告
- regression 檢查：哪些能力變好，哪些能力退步
- training diff report：本次訓練實際學了哪些新類型樣本
- rollout 策略：新模型先小流量試用，不直接全量替換
- post-deploy observation window：上線後 24h / 72h 採納與失敗率觀測

若再往下一步，我會評估：

- 除 SFT 外，是否逐步引入 preference / DPO 類資料
- block1 是否需要 action correctness 評估
- block2 是否需要中文解釋品質與結構性評估

---

## 十一、我會優先新增哪些功能

如果從產品與系統演進的角度，列出我最想加的功能，會是以下幾項：

### 1. `memory_insights`

顯示近期：

- 最常被命中的高價值記憶
- 長期未命中的低價值記憶
- 高重複的記憶簇

用途是讓記憶層開始可觀測，而不是只在出問題時才檢查。

### 2. `sample_lineage`

能從一筆 `training_sample` 反查：

- 來源 session
- 對應 messages
- 對應 tool execution
- refine 結果
- judge votes
- 最終為何進資料集

這會大幅提升資料治理能力。

### 3. `judge_disagreement_center`

集中呈現：

- `needs_review`
- judge 分歧大的樣本
- router acceptance 與 judge 結果衝突的樣本

這一類樣本最值得人類介入，也是系統最能學到東西的地方。

### 4. `run_snapshot`

每次 fine-tune run 都附一份資料快照摘要，例如：

- 使用多少新樣本
- 使用多少 replay 樣本
- 使用哪些 event_type
- 來源 sessions 數量
- 平均 weight / score

這能讓訓練從黑盒變成可追溯流程。

### 5. `post_deploy_monitor`

新模型部署後自動追蹤：

- 採納率
- fallback 率
- 工具失敗率
- 需要重做的比例
- 與上一版比較的變化

如果沒有這層，部署與否很容易只看感覺。

### 6. `project_rule_extractor`

從長期對話中自動萃出：

- 專案固定規範
- 命名習慣
- 測試偏好
- 部署與安全習慣

這些內容可以成為：

- router 的長期規則記憶
- future fine-tuning 的高價值資料來源

---

## 十二、我會優先修改哪些功能

如果只能選幾個點優先修改，我會先動以下方向。

### 1. 修改 Layer 1 → Layer 2 bridge 規則

目的不是只是改程式，而是要讓：

- 設計規範
- 實際抽樣邏輯
- 訓練資料分佈

三者完全一致。

### 2. 修改 acceptance inference 與 weight 信號

這一塊目前是可用的 heuristic，但還不夠像可靠 supervision signal。

若日後要讓模型真的從實戰採納中成長，這裡很值得升級。

### 3. 修改 judge 主流程，收斂成 production truth

無論最後保留雙裁判或三裁判，我都會希望系統內只有一套正式定義，而不是文件一套、排程一套、手動流程另一套。

### 4. 修改 Layer 3 run metadata

若要做可持續 fine-tuning，這一塊的必要性很高。

至少應讓未來能清楚回答：

- 這次學了什麼
- 跟上次相比多了什麼
- 如果回退，回的是哪一版資料快照

### 5. 修改 trigger policy 的可驗證性

尤其是 signal C 這種依賴 embedding 格式一致性的部分，若基礎不穩，就不適合成為正式 trigger 依據。

---

## 十三、整體成長方向判讀

如果用一句話總結我對這個專案的成長看法：

> 這個專案不是缺功能，而是已經值得進入第二階段：從「做出閉環」走向「讓閉環可信且可演進」。

我會把它理解成兩個階段：

### 第一階段：把閉環做出來

你目前已經做到了相當多：

- 記憶
- 評分
- 訓練
- 部署
- 回饋

### 第二階段：把閉環變成可靠學習系統

下一步關鍵不是再堆更多功能，而是：

- 讓資料更乾淨
- 讓評分更一致
- 讓 run 更可追溯
- 讓上線效果更能被量化

從我的角度看，這正是這個專案現在最值得投資的方向。

---

## 十四、若後續請 Claude 審視，可額外補問的問題

除了前面系統分析章節中列出的問題，我也建議後續可以請 Claude 再幫忙思考這幾題：

1. Layer 1 應否引入更正式的記憶分層與去重機制？
2. Layer 2 是否需要把資料治理能力獨立出來，而不只是 extraction/scoring？
3. Router 是否應升級成帶風險與可逆性判斷的策略層？
4. Layer 3 是否需要固定 benchmark 與 deployment 後觀測視窗？
5. 哪些新增功能最適合先做，才能最大化未來 7B → 32B 的遷移價值？

---

## 十五、補充結論

從純系統分析角度來看，這個專案已經有明確方向，也有繼續成長的價值。  
從產品與研究演進角度來看，它還有非常大的提升空間，而且這些空間大多不是「亂加功能」，而是有明確優先序的。

如果要用一句最濃縮的總結：

> 這是一個已經值得投入第二階段治理與強化的專案，而不只是繼續堆疊 prototype 功能。
