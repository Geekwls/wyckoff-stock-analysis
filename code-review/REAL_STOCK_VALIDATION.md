# 真实股票验证报告 (Phase 14 后)

**日期:** 2026-05-23  
**脚本:** `scripts/validate_real_stocks.py`  
**结果:** `REAL_STOCK_VALIDATION.json`

## 本轮结果：2/6（Yahoo 限流）

| 代码 | 状态 | 最终 phase | identifier_phase | 方向 | 信号 |
|------|------|------------|------------------|------|------|
| AAPL/MSFT/NVDA/0700.HK | ❌ 429 | — | — | — | — |
| sh.600519 | ✅ | **Distribution Phase A** | C+ 待 FTI | **观望** | SOW+JOC |
| sz.000001 | ✅ | **Accumulation Phase C** | C+ 待 JOC | **观望** | Spring |

## Phase 14 改进已验证（A 股）

1. **600519 不再误判 Accumulation Phase D** — BC+SOW 语境下 JOC 不升吸筹 D，identifier 为 `C+ 待 FTI`
2. **000001 Spring 无 JOC → 观望** — 符合孟氏 checklist（Phase C 震仓观察，等 JOC/LPS）
3. **phase_description 与 coordinator 一致** — 600519 不再出现 Phase B 文案覆盖 Phase A 标签
4. **VSA/dead_corner 主链采集** — `vsa_menhongtao` 已写入 EventsModel

## 数据层

- A 股：AkShare 代理失败 → BaoStock 回退正常
- 美股/港股：Yahoo **429 限流**（建议间隔 15min+ 或使用 `.cache/yfinance/` 缓存）

## 复现

```bash
# 全量
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py

# 仅 A 股
PYTHONPATH=src .venv/bin/python -c "
from scripts.validate_real_stocks import analyze_one
for s,m in [('sh.600519','茅台'),('sz.000001','平安')]:
    r=analyze_one(s,m)
    print(s, r['phase'], r['identifier_phase'], r['direction'])
"
```

## 单元测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_phase14_optimizations -q
# 12 tests OK（含 Phase 14 全量回归 52 tests）
```
