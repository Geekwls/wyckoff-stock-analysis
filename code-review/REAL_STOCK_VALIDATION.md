# 真实股票验证报告 (Phase 27 后)

**日期:** 2026-05-23  
**脚本:** `scripts/validate_real_stocks.py`  
**结果:** `REAL_STOCK_VALIDATION.json`

## 本轮结果：2/2 A 股（`--ashare-only`）

| 代码 | 阶段 | 方向 | 评分 | RS | 关键信号 | 入场区摘要 |
|------|------|------|------|-----|----------|------------|
| sh.600519 | Distribution Phase C/D | 观望 | 49 | falling | JOC+SOW 冲突→SOW | SOW 待 FTI/Upthrust 确认 |
| sz.000001 | Accumulation Phase B (1号Spring待二次测试) | 观望 | 47 | falling | Spring=Y, 正式LPS=- | 等待 JOC/LPS 确认 |

## Phase 26–27 改进已验证

1. **600519** — 派发 suppression + SOW 仲裁；方向观望；评分 49（门控生效）
2. **600519** — `lps=-`（无正式 LPS）；JOC 不参与做多处方
3. **000001** — Phase 27：1 号 Spring → **Phase B 待二次测试**（不再误标 Phase C）
4. **000001** — Phase 26：`lps=-`（support_test 不再误标 detected）；`lps_obs` 可在 JSON 中观察
5. **000001** — Spring 无 JOC → 观望；评分 47（RS falling 上限生效）

## 仲裁摘要

| 代码 | 主导信号 | 理由 |
|------|----------|------|
| 600519 | sow | 派发语境 SOW 优先于 JOC |
| 000001 | spring | 1 号 Spring 待二次测试，暂标 Phase B |

## 数据层

- A 股：AkShare 代理失败 → BaoStock 回退正常
- RS 指数：AkShare 失败 → BaoStock 回退（399001 等）
- 美股/港股：Yahoo 429 限流 → `--cache-only`

## 复现

```bash
# 仅 A 股（推荐）
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only

# 186 个 phase 语义测试
PYTHONPATH=src python -m pytest tests/test_phase*.py -q

# 全量 pytest（342 passed）
PYTHONPATH=src python -m pytest tests/ -q -m "not integration"
```
