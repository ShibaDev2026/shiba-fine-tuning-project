# shiba-fine-tuning-project — 標準工作流

> 對應規則來源：`~/.claude/CLAUDE.md`（通用）+ `./CLAUDE.md`（shiba 專屬）+ `.claude/skills/{resume,finish}`
> 適用情境：每次開 session 開始新工作。

---

## 1. Session Start（開機）

```
Shiba：Hi
```

Claude 動作：
1. 觸發 global「Session 觸發詞」+ project `/resume` skill。
2. 讀 `MEMORY.md` 前三段：**Active Plan / Recent Decisions / Open Questions**。
3. 讀 `docs/note/progress.md` 的 `## Active Task` — 若有未完成 / `[PAUSED]` step → 額外回報中斷點。
4. 回報「上次做到哪、下一步是什麼」。
5. **等 Shiba 確認方向才動作**。

---

## 2. 派工（一次一個任務，建議用前綴）

| 前綴 | 範例 | Claude 回應 |
|---|---|---|
| `[DO]` | `[DO] 把 retriever 換成 reranker` | 直接執行，不問澄清 |
| `[PLAN]` | `[PLAN] 評估加入 HyDE 的影響` | 只給計畫，不動檔 |
| `[DECIDE]` | `[DECIDE] reranker 用 bge-reranker-v2-m3 還是 cohere？` | 答這題，不擴張 |
| 無前綴 | `加 reranker` | 範圍模糊 → 問一題；否則直接做 |

---

## 3. Branch / Commit 慣例

- Branch 命名：**`yyyymmdd-pr-xxx`**（例：`20260522-pr-p-1`、`20260601-pr-q`）
- 切 branch 前 **必先 `git stash`** 未提交修改；回來後 `git stash pop`
- Commit message：**`<type>(<scope>): <中文主旨>`**
  - 例：`fix(pr-p-1): retriever 換成 bge-reranker`
- 大專案分 PR，scope 用 `pr-a / pr-b / pr-c ...` 字母遞增
- 推送 main 受拒 → `git pull --rebase` 後再 push（不 force push）

---

## 4. 執行中（Claude 自動遵守）

- **多檔重構** → 跑 `./CLAUDE.md` Verification 指令清單對應層的 pytest
- **危險操作**（`rm / git reset --hard / docker rm / volume rm / 覆蓋非暫存檔`）→ 強制回 Shiba 確認，**不自行執行**
- **動到秘密**（API Key / token）→ 走 Keychain + DB `keychain_ref`，**不打 log / 不寫 commit**
- **完成 evidence 形式**：`tests passed (N)` + `commit hash` + 必要時 `baseline 對比`

---

## 5. Verification 指令速查

```bash
# 全量
pytest tests/ -q

# 分層（範圍小時優先用）
pytest tests/layer0/ -q
pytest tests/layer2/ -q
pytest tests/layer3/ -q
pytest tests/memory/ -q
pytest tests/test_pr_o_*.py -q

# 改 docker / compose 後
docker compose config -q

# 改 stop_hook
SHIBA_PROJECT_ROOT=$(pwd) python layer_1_memory/stop_hook.py
```

**Baseline**：145+ tests（PR-O 後基準），回歸時須 ≥ 此數。

---

## 6. Session End（關機）

```
Shiba：/finish
```

Claude 動作：
1. 跑相關 pytest，回報 `tests passed (N)`。
2. Draft conventional commit message → **等 Shiba 確認才 commit**。
3. 更新 `MEMORY.md`：
   - **覆寫** `## Last Session (YYYY-MM-DD)`（3 bullets：what changed / evidence / next step）。
   - 若有重大決策，**前插** `## Recent Decisions (last 5)`，擠掉最舊一筆（cap=5），格式：
     ```
     YYYY-MM-DD — 決策 — (evidence: tests=N, commit=xxxxxxx[, baseline=...])
     ```
4. 更新 `CHANGELOG.md`（若值得發版，SemVer）。
5. `git status` + `git log -3` 給 Shiba，**等明確指示才 push**。

---

## 7. 典型 Session 範例

```
Shiba：Hi
Claude：[讀 MEMORY 前三段]
        Active Plan = RAGAS reranker；上次完成 PR-O；
        Open Questions：bge-m3 召回實效未驗證。
        建議下一步：先補召回回歸測試。

Shiba：[DO] 建 20260522-pr-p-1 branch，加 bge-m3 召回 baseline 測試
Claude：[git stash → checkout -b 20260522-pr-p-1 → 編輯 → pytest tests/memory/ -q]
        145 passed; commit hash: xxxxxxx

Shiba：/finish
Claude：[全量 pytest → draft commit → Shiba 確認 → 寫 Last Session
         → Shiba 確認 → git status / log → 等 push 指示]
```

---

## 三件 Claude **不會自動做**的事

1. **不會**主動讀 memory（必須 Shiba 開 session 後說 Hi 才觸發）。
2. **不會**主動 push 到 main（永遠等明確指示）。
3. **不會**自動跑全量測試燒 token（按 Verification 清單挑相關層；除非 `/finish`）。
