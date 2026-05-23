# 真实股票验证报告 (Phase 15–18 后)

**日期:** 2026-05-23  
**脚本:** `scripts/validate_real_stocks.py`  
**结果:** `REAL_STOCK_VALIDATION.json`

## 本轮结果：2/2 A 股（`--ashare-only`）

| 代码 | 状态 | 最终 phase | identifier_phase | 方向 | 信号 | 仲裁 |
|------|------|------------|------------------|------|------|------|
| sh.600519 | ✅ | **Distribution Phase C/D** | C+ 待 FTI | **观望** | SOW+JOC | **SOW 优先** |
| sz.000001 | ✅ | **Accumulation Phase C** | C+ 待 JOC | **观望** | Spring | — |

## Phase 15–18 改进已验证（A 股）

1. **600519 派发语境 SOW 优先于 JOC** — 仲裁器理由：`派发语境：SOW 优先于 JOC`；阶段修订为 `Distribution Phase C/D`
2. **000001 Spring 无 JOC → 观望** — identifier `C+ 待 JOC`
3. **arbitration_result 写入 EventsModel** — 修复 Pydantic 对象未持久化导致验证脚本读不到仲裁结果

## 数据层

- A 股：AkShare 代理失败 → BaoStock 回退正常
- 美股/港股：Yahoo 429 限流 → 使用 `--cache-only` 读 `.cache/yfinance/` 过期缓存

## 复现

```bash
# 仅 A 股（推荐）
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only

# Yahoo 限流时用本地过期缓存
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --cache-only

# 指定标的
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --symbols sh.600519
```

## 单元测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_phase*.py' -q
# 113 tests OK
```
