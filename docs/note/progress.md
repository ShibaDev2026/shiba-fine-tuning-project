# In-Progress Task Tracker

> **用途**：當 [DO] 任務超過 3 步驟、或預期會跨 context 窗口時，每個 step 完成就在這裡記一筆。Session 結束（/finish）由 Claude 清空或歸檔到 MEMORY.md。
>
> **不是**：每天日記、每個 commit log、長期決策記錄（那些在 MEMORY.md / CHANGELOG / git log）。
>
> **何時用 vs 不用**：
> - ≤ 3 step 的單純 [DO] → **不用**，避免噪音。
> - PR-X 多 step、或預期跨 session 的任務 → **必用**，保命用。
> - 中途 context 滿被截斷 → 下個 session /resume 必讀。

---

## Active Task

（沒有進行中任務時，此區為空。）

**Task**:
**Started**:
**Expected steps**: N
**Branch**:

### Steps

- [ ] Step 1 — 描述 / next action
- [ ] Step 2 — 描述
- [ ] Step 3 — 描述

### Evidence Log

> 每完成一個 step 在此追加一行：`YYYY-MM-DD HH:MM | Step N | tests=N passed | commit=xxxxxxx | note`

---

## Archive

> Session 結束（/finish）時，當前 Active Task 若已完成 → 整段移到下方並標記 `[DONE YYYY-MM-DD]`；若中斷 → 標記 `[PAUSED YYYY-MM-DD]` 保留供下次 /resume 重啟。保留 **最近 3 筆**，更舊的可刪。
