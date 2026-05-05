# Trivy 固定版本安裝修正

## Context
CVE-2026-33634：Trivy 供應鏈攻擊（2026-03-19~03-23）導致 v0.69.4~v0.69.6 受汙染。
目前 Dockerfile 使用 `apt install trivy`（無版本釘定），存在自動升版風險。
目標：改成與 gitleaks 相同的 pinned binary 模式，固定在安全版本 v0.69.3。

## 修改範圍

**唯一異動檔案：** `docker-compose/agent/Dockerfile`

## 變更內容

將 Trivy apt 安裝區塊（第 40–51 行）替換為：

```dockerfile
# -----------------------------------------------------------------------------
# Trivy v0.69.3（Container / Filesystem 漏洞掃描）
# 固定版本確保可重現性，防止供應鏈攻擊（CVE-2026-33634）
# linux/arm64 對應 M1 Mac Agent 執行環境
# 官方 Release：https://github.com/aquasecurity/trivy/releases
# -----------------------------------------------------------------------------
ARG TRIVY_VERSION=0.69.3
RUN curl -sSfL \
        "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-ARM64.tar.gz" \
        -o /tmp/trivy.tar.gz \
    && tar -xzf /tmp/trivy.tar.gz -C /usr/local/bin trivy \
    && rm /tmp/trivy.tar.gz \
    && chmod +x /usr/local/bin/trivy \
    && mkdir -p /usr/local/share/trivy/templates \
    && curl -sSfL \
        "https://raw.githubusercontent.com/aquasecurity/trivy/v${TRIVY_VERSION}/contrib/junit.tpl" \
        -o /usr/local/share/trivy/templates/junit.tpl \
    && trivy --version
```

## 副作用清單
- Trivy 版本固定為 v0.69.3，未來升版需手動更新 ARG
- 僅下載 junit.tpl（cd.sh 實際用到的），其餘 template 不保留（asff/gitlab/html 不影響 pipeline）
- 移除 apt Trivy repo 相關設定（keyrings、sources.list.d），無副作用

## 驗證步驟
1. `docker build -t shiba-docker-jenkins-agent-dev .`（在 docker-compose/agent/ 下執行）
2. `docker run --rm --entrypoint trivy shiba-docker-jenkins-agent-dev --version` → 應顯示 `Version: 0.69.3`
3. `docker run --rm --entrypoint ls shiba-docker-jenkins-agent-dev /usr/local/share/trivy/templates/` → 應顯示 `junit.tpl`
4. 跑一次 Jenkins Pipeline（claude-project develop）確認 Image Scan stage 正常
