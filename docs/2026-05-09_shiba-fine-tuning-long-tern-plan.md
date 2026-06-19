# Shiba Fine-Tuning 長期架構規劃

最後更新：2026-05-09

---

## 現行架構（單人本地）

```
Claude Code session
  → stop_hook（Layer 1）→ SQLite DB
  → Layer 0（Gemma 分類 / Qwen 回應）
  → Layer 2（評分、精煉）
  → Layer 3（MLX LoRA → GGUF → Ollama）
```

---

## 近期待辦（2026-05 觀察期）

- [ ] PR1 觀察期每日確認（→ 2026-05-16）
  - `PRAGMA integrity_check` ok
  - logs 無 disk I/O / malformed 錯誤
- [ ] 2026-05-16 後：清理 `data/broken-*` / `recovered*.sql`
- [ ] PR2：stop_hook SAVEPOINT 分段 + multi_judge 外層事務
- [ ] FTS5 trigram migration（可選，RAG 中文召回改善）

---

## 中期規劃：多人小圈子版本

### 架構目標

```
使用者本地：
  Claude Code → stop_hook（HTTP client）
  本地 Ollama 跑 Layer 0（分類/壓縮/回應）
  本地 Layer 1 寫個人 DB
  → POST 精煉樣本到中央 server

中央 server（你的機器）：
  /ingest → Redis Streams → worker
  → Layer 2 評分寫 DB
  → 每週/月 Layer 3 訓練
  → 產出 GGUF → 使用者 pull 更新
```

### 關鍵元件

| 元件 | 技術選型 | 說明 |
|------|---------|------|
| 資料入口 | FastAPI `/ingest` | token 驗證（API key） |
| Message Queue | Redis Streams | 防並行寫入，consumer group |
| DB 寫入 | 單一 worker | 保證單 writer |
| 模型分發 | HTTP 靜態檔 + 版本號 | 使用者定期 pull GGUF |
| 身份識別 | user_id + source_ip 標註 | 資料來源追蹤 |

### 模型訓練策略

- **冷啟動**：共用池合訓 base adapter（解決新用戶樣本不足）
- **個人化**：樣本累積後可 fine-tune on top（adapter on adapter）
- **分發週期**：週/月定期，使用者主動 pull，不主動推

---

## 長期規劃：架構演進方向

### Model Provider Abstraction
- Layer 0 不直接呼叫 Ollama，透過統一 `ModelClient` 介面
- 支援 Ollama / vLLM / 其他 inference engine 可插拔
- 時機：Layer 3 訓練完需熱抽換模型時引入

### DB 抽換
- 現行：SQLite + journal_mode=DELETE（單機穩定）
- 多人並行達瓶頸後考慮：PostgreSQL（寫多讀多）
- 待討論

### 微服務拆解
- 現行單體 FastAPI → 依流量拆解
- 候選：ingest service / scoring service / training trigger
- 待討論

### stop_hook → HTTP API
- 目前 stop_hook 直連 DB（多 writer 風險）
- 長期改為打 Layer 2 HTTP API（單 writer）
- 前置條件：PR2 完成後評估

---

## 決策記錄

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-05-09 | journal_mode=DELETE | macOS Virtualization.framework SHM 鎖定不一致 |
| 2026-05-09 | MQ 選 Redis Streams | 小圈子規模，輕量，Docker 友善 |
| 2026-05-09 | 推論在使用者本地 | server 不跑即時推論，成本分散 |
| 2026-05-09 | GGUF 定期 pull 不主動推 | 簡單可靠，使用者控制更新時機 |
| 2026-05-09 | 訓練在 server，GGUF 推回 | 使用者不一定有 MLX/GPU |
