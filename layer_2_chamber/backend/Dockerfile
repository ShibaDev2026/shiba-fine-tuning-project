# Layer 2 Backend Dockerfile
# 建構時以「專案根」為 build context：
#   docker build -f layer_2_chamber/backend/Dockerfile -t shiba-backend:latest .
# 如此 COPY 才能抓到 shiba_config.py、config/、layer_0/1/3/ 等跨 layer 依賴

FROM python:3.11-slim AS base

# 系統層：sqlite3 CLI（供除錯）、curl（供 healthcheck）
# --no-install-recommends 避免多餘 packages 進入 image
RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlite3 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements 先裝：build cache 優化，程式碼變動時不會重裝 deps
COPY layer_2_chamber/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 複製專案程式碼（.dockerignore 排除 data/backups/frontend/docs/等）
COPY . /app

# runtime 環境變數：
# - SHIBA_RUNTIME=docker → shiba_config 選 host.docker.internal 的 Ollama/Layer 3 URL
# - PYTHONPATH=/app → 讓 `from shiba_config import CONFIG` 與各 layer 匯入解析
ENV SHIBA_RUNTIME=docker \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "layer_2_chamber.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
