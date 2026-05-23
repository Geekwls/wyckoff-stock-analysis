# 真实股票验证报告 (Phase 13 后)

**日期:** 2026-05-23  
**脚本:** `scripts/validate_real_stocks.py`  
**结果:** `REAL_STOCK_VALIDATION.json`

## 本轮结果：2/6（Yahoo 限流）

| 代码 | 状态 | 最终 phase | phase_description | 方向 |
|------|------|------------|-------------------|------|
| AAPL/MSFT/NVDA | ❌ 429 | — | — | — |
| sh.600519 | ✅ | **Distribution Phase A** | 派发特征确认文案（独立字段） | **观望** |
| sz.000001 | ✅ | **Accumulation Phase C** | — | 做多 |
| 0700.HK | ❌ 429 | — | — | — |

## Phase 13 改进已验证（A 股）

1. **阶段标签规范化** — 600519 的 `phase` 为 `Distribution Phase A`，不再被 `[经典威科夫派发...]` 长文案覆盖  
2. **描述分离** — 吸收/派发得分 narrative 写入 `phase_description`  
3. **Coordinator 合并** — `phase_source=coordinator_reconcile`，identifier 仍为 Phase B 时用户可见阶段以 coordinator 为准  
4. **交易门控** — 600519 派发 A + SOW → 观望  

## 数据层

- A 股：AkShare 代理失败 → BaoStock 回退正常  
- 美股/港股：Yahoo **429 限流**（短期频繁请求导致）  
- 已加：**yfinance 本地缓存**（`.cache/yfinance/`，6h 新鲜 / 7d 过期兜底）+ 重试退避  

## 复现

```bash
# 全量（建议间隔 15min+ 若 Yahoo 仍 429）
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py

# 仅 A 股（不依赖 Yahoo）
PYTHONPATH=src .venv/bin/python -c "
from scripts.validate_real_stocks import analyze_one
for s,m in [('sh.600519','茅台'),('sz.000001','平安')]:
    r=analyze_one(s,m); print(s, r['phase'], r['direction'])
"
```

## 单元测试

38+ tests OK（含 `test_phase13_fixes` orchestrator 合成 E2E）
