# 專案 Markdown 一次性整理 Plan

## Context

`shiba-fine-tuning-project` 經過 v0.9.0 → v1.3.0 多輪迭代，根目錄與 `docs/` 下散落多種來源/用途不同的 markdown：論文、設計規格、過時 plan、Codex review、外部 agent 規範、嵌入的 Claudest 參考 repo。

**問題：**
- 根層 untracked：`AGENTS.md`、`2026-04-25_codex_suggestion.md`、`docs/`（整目錄）— 從未 commit
- `AGENTS.md` 是 stale fork（DB 路徑、模型版本、Layer 1→2 橋接條件全是 v1.0.0 前舊版，且全文 `Claude` → `Codex` 替換）
- `.gitignore` 排除 `CLAUDE.md` → repo 對外規範必須由 AGENTS.md 承擔
- `~/.claude/plans/` 內 3 份本專案 plan（go-glistening / sparkling-willow / unified-kindling）跨專案目錄堆積、其中 1 份已合併過時
- `docs/superpowers/`、`docs/references-paper/-blog/-git/` 命名混雜（工具名 vs 語意分類）

**預期結果：**
一次完成 — `docs/` 重組為 `design/ references/{papers,blogs,git}/ archive/{,plans/}` 三類；AGENTS.md 改寫為 agent-agnostic 並對齊 CLAUDE.md 最新事實；過時 plan 全歸檔；`.gitignore` 同步修正。完工後 `git status` 乾淨、未來新 plan 直接放 `docs/design/`、過時時 `mv` 到 `docs/archive/plans/`。

## Decisions（已透過 AskUserQuestion 確認）

1. **AGENTS.md** — 保留入版控、改寫為 agent-agnostic、與 CLAUDE.md 同步事實內容；`CLAUDE.md` 維持在 `.gitignore`（作 Claude Code 個人補充）
2. **`~/.claude/plans/` 中 3 份本專案 plan** — 全部歸檔到 `docs/archive/plans/`，加日期前綴

## 目標目錄結構

```
shiba-fine-tuning-project/
├── README.md                          # 保留
├── CLAUDE.md                          # 保留（仍 .gitignore）
├── CHANGELOG.md                       # 保留
├── AGENTS.md                          # 改寫對齊 CLAUDE.md，入版控
└── docs/
    ├── design/                        # 本專案實裝規格
    │   ├── 2026-04-15-architecture-design.md
    │   ├── 2026-04-15-phase1-memory-layer.md
    │   ├── 2026-04-17-layer2-schema.md
    │   ├── 2026-04-19-layer0-router.md
    │   └── 2026-04-19-layer3-finetune-pipeline.md
    ├── references/                    # 第三方參考
    │   ├── papers/  (PAPERS_INDEX.md + 4 篇)
    │   ├── blogs/   (mac-mini-35b)
    │   └── git/     (Claudest 整個 repo, .git 由 .gitignore 排除)
    └── archive/                       # 一次性報告 + 過時 plan
        ├── 2026-04-25-codex-review.md
        └── plans/
            ├── 2026-04-15-unified-kindling-lynx.md
            ├── 2026-04-19-sparkling-dazzling-willow.md
            └── 2026-04-30-go-glistening-metcalfe.md
```

## 執行步驟（依序執行，rm 動作標 ⚠️ 需 Shiba 口頭確認）

### Step 1 — 建立目錄
```bash
mkdir -p docs/design docs/references/papers docs/references/blogs docs/references/git docs/archive/plans
```

### Step 2 — 移動 design plans（5 份，untracked 無 git 歷史）
```bash
mv docs/superpowers/plans/*.md docs/design/
```

### Step 3 — 攤平 references 三類
```bash
mv docs/references-paper/* docs/references/papers/
mv docs/references-blog/*  docs/references/blogs/
mv docs/references-git/*   docs/references/git/
```

### Step 4 — 根層 untracked 檔搬到 archive
```bash
mv 2026-04-25_codex_suggestion.md docs/archive/2026-04-25-codex-review.md
```

### Step 5 — 從 ~/.claude/plans/ 搬 3 份本專案 plan，加日期前綴
```bash
mv ~/.claude/plans/go-glistening-metcalfe.md     docs/archive/plans/2026-04-30-go-glistening-metcalfe.md
mv ~/.claude/plans/sparkling-dazzling-willow.md  docs/archive/plans/2026-04-19-sparkling-dazzling-willow.md
mv ~/.claude/plans/unified-kindling-lynx.md      docs/archive/plans/2026-04-15-unified-kindling-lynx.md
```
> 註：unified-kindling 是否真為本專案 CVE 修正記憶不確定 — 先歸檔保留歷史，閱檔後若確認無關再個別 rm。

### Step 6 — ⚠️ 清理空殼舊目錄與 .DS_Store（**rm，需確認**）
```bash
rm -rf docs/superpowers/ docs/references-paper/ docs/references-blog/ docs/references-git/
find docs -name '.DS_Store' -delete
```

### Step 7 — 改寫 AGENTS.md 對齊 CLAUDE.md（agent-agnostic）

完整覆寫 `AGENTS.md` 為以下內容（複製 CLAUDE.md 結構，把 `Claude` 改為 `AI 助手`、移除 Claude Code 專屬段落如 memory/skill；其餘事實內容與 CLAUDE.md 一致）：

關鍵修正點（相對現況 stale 版）：
- `~/.local-brain/shiba-brain.db` → `./data/shiba-brain.db`（v1.0.0 docker-compose 重構）
- `Gemma E2B` → `gemma3:4b`（Layer 0 classifier）
- Layer 1→2 橋接：`has_tool_use=true + exchange_count ≥ 2` → `has_final_text=1 AND has_error=0 + branches.is_active=1 AND decay_score ≥ 0.3 + 同 session 合格 exchanges ≥ 2`
- Layer 2 評分：兩裁判舊邏輯 → multi_judge 三方投票（3/3 weight=1.0、2/3 weight=0.5、router_decisions.user_accepted=1 強制 approved）
- 安全機制：「強制回 Codex 確認」→「強制回 AI 助手確認」
- 移除 Layer 1 Hooks 同步至 plugin 的描述（settings.json 直接指專案目錄，不需 plugin）

### Step 8 — 更新 `.gitignore`

```diff
- # Plan 檔與 CLAUDE.md 不進版控
- docs/superpowers/
- CLAUDE.md
+ # CLAUDE.md 為 Claude Code 個人補充規範，不入版控（外部 agent 讀 AGENTS.md）
+ CLAUDE.md
+
+ # 內嵌的 Claudest 參考 repo 巢狀 .git/ 不入版控
+ docs/references/git/*/.git/
```

### Step 9 — 驗證
```bash
git status                                    # 應只剩 docs/、AGENTS.md、.gitignore（+ 既有 staged: stop_hook.py / paraphrase_service.py / dateFilter.ts，屬另案不動）
ls docs/                                      # design/ references/ archive/
ls docs/archive/plans/                        # 3 份 plan 都在
test -e AGENTS.md && grep -c "data/shiba-brain.db" AGENTS.md   # 應 ≥1（確認改寫生效）
test ! -e docs/superpowers && echo "superpowers/ removed"
test ! -e docs/references-paper && echo "references-paper/ removed"
ls ~/.claude/plans/ | grep -E "go-glistening|sparkling-willow|unified-kindling"  # 應為空（已搬走）
git ls-files docs/ | head                     # commit 後應列出新結構檔案
```

### Step 10 — 建議 commit message（Shiba 自己決定何時執行）
```
chore(docs): 一次性整理 markdown 與 plan 擺放結構

- docs/superpowers/plans → docs/design/（5 份實裝規格）
- 攤平 references-{paper,blog,git} → references/{papers,blogs,git}/
- 一次性報告與過時 plan → docs/archive/{,plans/}（含從 ~/.claude/plans/ 歸檔的 3 份）
- AGENTS.md 改寫對齊 CLAUDE.md 最新事實（DB 路徑、gemma3:4b、multi_judge、橋接條件）
- .gitignore：移除已不存在的 docs/superpowers/，新增 docs/references/git/*/.git/
```

## Critical Files

- `/Users/surpend/Developer/01_project/shiba-fine-tuning-project/AGENTS.md`（改寫）
- `/Users/surpend/Developer/01_project/shiba-fine-tuning-project/.gitignore`（兩處更新）
- `/Users/surpend/Developer/01_project/shiba-fine-tuning-project/CLAUDE.md`（**不動** — 此次決議維持 ignore，作為事實對照源）
- `/Users/surpend/Developer/01_project/shiba-fine-tuning-project/docs/`（重組）
- `/Users/surpend/.claude/plans/{go-glistening-metcalfe,sparkling-dazzling-willow,unified-kindling-lynx}.md`（搬走）

## Risks & Rollback

| 風險 | 影響 | 對策 |
|------|------|------|
| README/CLAUDE/CHANGELOG 內含舊 `docs/` 路徑連結 | broken link | 已 grep 確認三檔皆無 `docs/` 引用，安全 |
| `docs/references/git/Claudest/` 巢狀 .git 被 git 警告 | warning，非 error | Step 8 .gitignore 規則已處理 |
| `unified-kindling-lynx.md` 真的不相關卻被歸檔 | 雜訊但無害 | 歸檔目錄本就允許含過時/不相關內容；未來閱檔時 rm 即可 |
| `mv` 過程斷電 | 部分檔案在新位置、部分在舊 | mv 是 atomic（同 filesystem），實務上不會半途；萬一發生 → `mv` 反向回去即可 |
| AGENTS.md 改寫漏抄某段 | 對外規範缺塊 | Step 9 grep 驗證 + 完成後肉眼掃過 diff |
| ⚠️ Step 6 rm 誤刪 | 非 untracked 檔被刪 | 所有 rm 對象都已 untracked；rm 前 ls 一次確認 |

**Rollback：**
- Step 1-5（mv）— `mv` 反向就還原
- Step 6（rm 空殼）— 空殼無內容，不需還原
- Step 7（改寫 AGENTS.md）— 整檔覆寫；Shiba 若不滿意可從 git 還原（但檔案 untracked，無 git history；可從 OS 備份/Time Machine 還原）→ **建議改寫前先 `cp AGENTS.md AGENTS.md.bak`，整理完成後再 `rm AGENTS.md.bak`**
- Step 8（.gitignore）— 只兩行，肉眼可改回

## 整理完成後此 plan 檔的處置

整理 + 驗證通過後，Shiba 自行決定：
- 留在 `~/.claude/plans/cuddly-greeting-charm.md`（plan mode 預設位置）
- 或 `mv` 到 `docs/archive/plans/2026-05-06-cuddly-greeting-charm.md`（與其他歸檔 plan 同處）

依專案 CLAUDE.md「完成驗證後立即刪除 plan 檔」精神，建議第二種或直接 rm。
