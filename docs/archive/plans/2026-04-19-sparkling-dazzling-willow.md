# 新增 event_type：infra_ops + tech_eval

## Context

本次對話中，Shiba 討論了 MCP server 設計、Docker vs launchd、Python vs Java 技術選型等議題。這類對話目前會被分類為 `architecture` 或 `knowledge_qa`（過於泛化），導致：
1. **Fine-tuning 品質下降**：部署討論和技術比較會混入過於寬泛的 Block 2 訓練樣本中
2. **RAG 召回精準度差**：下次問「launchd 怎麼設定」找不到這段對話
3. **知識盲區不可見**：無法追蹤專案在基礎設施和技術選型兩個維度的對話分布

新增兩個 event_type 可精確分類此類對話，提升兩個主要目標（fine-tuning 與 RAG 召回）的效果。

---

## 實作步驟

### Step 1：`classifier.py` — 加入關鍵字規則與優先順序

檔案：`layer_1_memory/lib/classifier.py`

**加入關鍵字**（在 `_KEYWORD_RULES` dict 的 `knowledge_qa` 之前）：

```python
"infra_ops": [
    "docker-compose", "docker compose", "dockerfile",
    "launchd", "plist", "launchctl", "launchagents",
    "mcp server", "mcp_server",
    "nginx", "reverse proxy", "gunicorn", "uvicorn",
    "daemon", "systemd",
    "deploy", "deployment", "infra", "infrastructure",
    "部署", "服務管理", "守護程序", "基礎設施", "架設", "反向代理",
],
"tech_eval": [
    "vs", "versus", "compare", "comparison",
    "trade-off", "tradeoff", "pros and cons",
    "feasible", "feasibility", "viable",
    "side effect", "limitation", "drawback",
    "有辦法", "可行性", "能做到嗎", "辦得到嗎",
    "哪種比較好", "哪個更好", "怎麼選", "如何選擇",
    "優缺點", "優劣", "副作用", "有什麼缺點", "有什麼限制",
    "比較好", "建議用", "值不值得", "適合嗎",
],
```

**更新優先順序列表**（`classify_session` 中的 for 迴圈）：

```python
for event_type in [
    "fine_tuning_ops",
    "debugging",
    "git_ops",
    "terminal_ops",
    "infra_ops",    # 新增
    "architecture",
    "tech_eval",    # 新增
    "knowledge_qa",
]:
```

同步更新 `classify_text` 函式中相同的迴圈。

**注意**：`terminal_ops` 已有 `docker`、`service` 關鍵字，`infra_ops` 用更精確的 `docker-compose`、`launchd` 等子詞避免衝突。兩個 type 同時命中是可接受的行為（`terminal_ops` 因優先順序較高會是 primary type）。

---

### Step 2：`config.yaml` — 新增 event_importance 權重

檔案：`layer_1_memory/config.yaml`

```yaml
event_importance:
  architecture: 1.1
  fine_tuning_ops: 1.1
  infra_ops: 1.0        # 新增
  debugging: 1.0
  tech_eval: 1.0        # 新增
  code_gen: 1.0
  git_ops: 0.9
  terminal_ops: 0.9
  knowledge_qa: 0.9
```

權重設計邏輯：`infra_ops` 1.0（部署資訊有時效性，不及架構設計高）；`tech_eval` 1.0（技術比較論述在同一技術生命週期穩定有效）。

---

### Step 3：`pipeline.py` — 更新 Block 2 分類

檔案：`layer_2_chamber/backend/extraction/pipeline.py`

```python
_BLOCK2_EVENT_TYPES = {
    "debugging",
    "architecture",
    "knowledge_qa",
    "fine_tuning_ops",
    "infra_ops",    # 新增：部署討論 = 文字推理
    "tech_eval",    # 新增：技術評估 = 文字推理
}
```

`_BLOCK1_EVENT_TYPES` 和 `_BRIDGE_EVENT_TYPES` 不需修改（後者自動 union 繼承）。

---

### Step 4：`seed_questions.py` — 新增兩個題目集

檔案：`layer_2_chamber/scripts/seed_questions.py`

在 Block 2 區塊末尾加入：

**infra_ops 題目集**（8 題，難度 5-7）：
- launchd plist 開機自啟、docker volume 持久化 SQLite、Ollama 服務崩潰自動重啟、FastAPI worker 數量設定、nginx 反向代理 MCP server 等

**tech_eval 題目集**（8 題，難度 5-8）：
- SQLite WAL 多程序寫入可行性、Ollama vs API 副作用、FTS5 vs 向量搜尋語意匹配效果、LoRA rank 取捨、本地 fine-tuning 品質上限等

---

### Step 5：更新測試

**`tests/memory/test_classifier.py`** — 加 5 個案例：
```python
test_classify_infra_ops()              # docker-compose FastAPI → infra_ops
test_classify_infra_ops_launchd()      # launchd plist → infra_ops
test_classify_tech_eval()              # 優缺點副作用 → tech_eval
test_classify_tech_eval_feasibility()  # 有辦法做到嗎 → tech_eval
test_terminal_ops_docker_backward()    # docker 單詞仍觸發 terminal_ops（向後相容）
```

**`tests/layer2/test_pipeline.py`** — 加 1 個案例：
```python
test_new_block2_event_types()  # infra_ops/tech_eval → block 2
```

---

### Step 6：CLAUDE.md 同步

兩處更新：
1. Adapter 表格的 block2 欄位加入 `infra_ops + tech_eval`
2. 事件分類清單加入兩個新 type

---

## 自我監督優化

**不新增 `meta_ops`**（討論此專案架構的對話），理由：與 `architecture` 關鍵字高度重疊、訓練樣本泛化性差。替代方案：在 RAG 召回時用 `project_path` 過濾，讓同專案架構討論優先出現。

**分類分布追蹤 SQL**（可加入 `layer_2_chamber/scripts/` 作為診斷工具）：
```sql
SELECT value AS event_type,
       COUNT(*) AS session_count,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
FROM sessions, json_each(sessions.event_types)
WHERE started_at > datetime('now', '-30 days')
GROUP BY value ORDER BY session_count DESC;
```
若某 type 佔比 < 3%，標記為知識盲區，考慮補充 seed_questions 或調整關鍵字。

---

## 驗證指令

```bash
# 執行測試
python -m pytest tests/memory/test_classifier.py tests/layer2/test_pipeline.py -v

# 手動驗證分類
python -c "
from layer_1_memory.lib.classifier import classify_text
print(classify_text('docker-compose 有辦法讓 FastAPI 自動重啟嗎？'))
print(classify_text('Python vs asyncio 哪種比較好？有什麼副作用'))
print(classify_text('docker compose up 失敗了'))
"

# 確認 seed_questions 寫入
python layer_2_chamber/scripts/seed_questions.py --list
```

---

## 修改的關鍵檔案

| 檔案 | 改動 |
|------|------|
| `layer_1_memory/lib/classifier.py` | 加 2 組關鍵字 + 更新 2 個優先順序列表 |
| `layer_1_memory/config.yaml` | 加 2 條 event_importance |
| `layer_2_chamber/backend/extraction/pipeline.py` | `_BLOCK2_EVENT_TYPES` 加 2 個 |
| `layer_2_chamber/scripts/seed_questions.py` | 加 2 個題目集（16 題） |
| `tests/memory/test_classifier.py` | 加 5 個測試 |
| `tests/layer2/test_pipeline.py` | 加 1 個測試 |
| `CLAUDE.md` | 同步 Adapter 表格 + 事件分類清單 |
| `CHANGELOG.md` | 新增 v0.6.0 區塊 |
