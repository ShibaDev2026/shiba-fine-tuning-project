# CLAUDE.md — docs/references（研究情報摘要工作區）

> 本檔為**子目錄 CLAUDE.md**，疊加在 repo root `CLAUDE.md` 與 `~/.claude/CLAUDE.md` 之上（不取代、不隔離）。
> 僅規範 `docs/references/` 底下的「情報檢索 → 每週摘要報告」工作；不改動主任務 `layer_*/`。

## 這個目錄是什麼
研究/參考資料庫（純資料、無程式碼）：
- `papers/` — 論文；`papers/pending/` 為待整理
- `blogs/` `news/` — 技術 blog／tech news（**時效性內容**）
- `git/` — GitHub repo／release 參考素材
- `01_summary_report/` — **本工作流的產出區**（每週報告）

## 目錄慣例（存檔結構）
單位原則：**一個資料夾 = 一則，內含單一 markdown**（比照 papers）。

| 類型 | 路徑樣式 | 內含檔 | 範例 |
|------|---------|--------|------|
| Blog | `blogs/YYYY_<month>/NN_Title/` | `blog.md` | `blogs/2026_june/01_Mac_Mini_35B_Local/blog.md` |
| Tech news | `news/YYYY_<month>/NN_Title/` | `news.md` | `news/2026_june/01_Some_Release/news.md` |
| 論文（digest 收集）| `papers/YYYY_<month>/NN_Title/` | `paper.md` | `papers/2026_june/01_New_RAG_Paper/paper.md` |
| GitHub | `git/YYYY_<month>/NN_Title/` | `repo.md`（**只名稱＋連結＋分析，無程式碼**）| `git/2026_june/01_Some_Repo/repo.md` |

- **digest 收集的內容一律多一層 `YYYY_<month>`**：西元年 ＋ 底線 ＋ 英文小寫月份（`2026_june`、`2026_july`…）。
- `NN_` 為**該月份資料夾內**的序號（每月從 `01` 重起），`Title` 用底線連接、可讀。
- 內含 markdown 開頭附 metadata：來源 URL、發布日期、來源類型、relevance、與主專案關聯。

### 處理狀態（單一真相源＝資料夾名）
- `NN_Title/` ＝ 已蒐集**未讀**；`NN_Title_read/` ＝ **已讀且已進週報**。
- 流程：Phase A 蒐集放進目錄（未加後綴）→ Phase B 批量讀無 `_read` 者、整理進報告 → 處理完 `mv` 加 `_read`。
- **去重**：蒐集時讀 `processed_log.md`（已讀文章索引、單一檔），URL 已列即跳過（不重爬）；批量閱讀只讀無 `_read` 者（不重讀）。Phase B 標 `_read` 時同步追加 log。
- ⚠️ 既有 `papers/NN_Title/`（無月份層、無 `_read`）＝參考庫舊有，**不自動納入週報**；既有扁平檔（如 `blogs/leopardracer-*.md`）不回溯搬移，除非 Shiba 指示。

## 核心工作流：每週情報摘要（weekly digest）
目標：定期蒐集與 shiba-fine-tuning-project 議題相關的「對外發表內容」，產出新聞式週報。

### 來源範圍
- ✅ 只收**已發表內容**：
  - 技術 blog、tech news、學術論文（arXiv／官方部落格／release notes）
  - **GitHub（git）**：新 repo、release／tag、CHANGELOG、README／文件更新——即「對外發布物」
- ❌ 不收**討論／對話**：論壇回文、社群辯論、comment thread、X／Reddit／HN 留言串，**以及 GitHub issue／PR／commit 的討論留言**
- 逐則記錄**來源 URL ＋ 發布日期**；抓不到原文日期就標「日期未確認」，不杜撰

### 議題範圍（佇列驅動，隨情境演進）
**單一真相源＝`topics_queue.md`**（本目錄）。每次執行依其輪轉規則挑一個議題（pending 優先→最久沒跑），跑完標 `done`＋日期、下次換下一個，繞完回頭。議題隨專案情境演進——手動增刪，或用佇列檔「刷新」段從專案 memory 索引（`~/.claude/projects/<proj>/memory/MEMORY.md`）+ `docs/roadmap/*` 補新題（提議制、不自動覆寫）。
> 不在此寫死議題清單，避免與佇列檔重複漂移；當前題目以 `topics_queue.md` 為準。

### 檢索方式（harness engineering）
- 用 **sub-agent 並行分流**：一個議題一個 agent、無依賴時同一訊息 dispatch（省主 context）
- 工具：`WebSearch` 找文 → `WebFetch` 取原文摘錄；只摘**發文本身**，不摘其下討論
- GitHub：用 `gh` CLI（release／tag／repo 查詢）或 `WebFetch` 取 release notes／CHANGELOG；只取發布物、不取 issue／PR 討論
- 去重：同一則跨來源重覆只收一次，標主來源

### 產出規範
**兩段式**：① 每則收錄先**存檔**到對應結構（見上「目錄慣例」：blog→`blogs/YYYY_<month>/`、news→`news/YYYY_<month>/`、paper→`papers/`）；② 再產**週報**彙整並連結到各存檔。

週報：
- 路徑：`01_summary_report/`
- 檔名：`YYYY-MM-DD-weekly-digest.md`（週報產出日）
- 語言：**繁體中文**；專有名詞先縮寫再附英文全名（如「HyDE（Hypothetical Document Embeddings）」）
- 格式：**新聞式**——報告開頭 TL;DR ＋ 收錄則數；每則為
  - **標題**（一行、具資訊量）
  - **詳細內文**（數句段落，非單句 bullet）
  - 附註：來源類型（blog／news／paper）、原文 URL、發布日期、**與主專案的關聯**一句話

## 邊界護欄（在此目錄工作時）
- **不得**改動主專案 `layer_*/`、`config/`、`data/*.db`、訓練流程
- 產出只寫進 `docs/references/` 底下；不碰主 DB、不跑訓練
- 不 commit／輸出機敏資訊（Key、token、本地 IP、個人資訊）
- `WebFetch`／`WebSearch` 抓外部內容＝對外動作，照全域 CLAUDE.md 規範

## 自動化現況（CLAUDE.md 本身達不到「定期」）
本檔只記錄「怎麼做」，**不會自動每週執行**。要真自動化，二擇一（未建，待 Shiba 指示）：
- 手動觸發 → 做成 skill `/weekly-digest`（封裝上述流程，`$ARGUMENTS` 收週次）
- 排程自動 → scheduled cloud agent（用 `schedule` skill 設每週 cron）
