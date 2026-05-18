# Layer 2 Judge 可靠性報告

生成時間：2026-05-18 07:54:30 UTC

## B.2 Fleiss' Kappa（Judge 一致性）

**尚無足夠資料**（需 ≥2 votes/sample）

目前 judge_agreement_logs：5 筆（每筆 <2 票，無法計算）

**下一步**：
1. 等待 Gemini 配額重置（UTC 00:00）
2. 重新評分現有樣本以累積多方投票
3. 重跑 `python -m evaluation.layer2_eval --action kappa`

## B.3 RAGAS Faithfulness（輸出忠實度）

**平均 Faithfulness = 0.5500**

評估樣本數：20

❌ 輸出忠實度需改進

## 決策與建議

| 檢查項 | 狀態 | 建議 |
|--------|------|------|
| Kappa ≥ 0.6 | ⚠️ 待補充 |  |
| Faithfulness ≥ 0.6 | ⚠️ Review | 指令追蹤精準度需提升 |

## 驗證指令

```bash
# 完整 100 筆樣本評估
python -m evaluation.layer2_eval --action kappa

# Kappa 分布
sqlite3 data/shiba-brain.db "SELECT ROUND(fleiss_kappa,1) k, COUNT(*) FROM judge_agreement_logs GROUP BY k ORDER BY k"

# Judge vs RAGAS 衝突樣本（高一致性但低忠實度）
sqlite3 data/shiba-brain.db "SELECT sample_id, fleiss_kappa, ragas_faithfulness FROM judge_agreement_logs WHERE ragas_faithfulness < 0.5 AND fleiss_kappa > 0.7 LIMIT 10"
```
