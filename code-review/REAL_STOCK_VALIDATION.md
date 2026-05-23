# 真实股票验证报告 (Phase 25 后)

**日期:** 2026-05-23  
**脚本:** `scripts/validate_real_stocks.py`  
**结果:** `REAL_STOCK_VALIDATION.json`

## 本轮结果：2/2 A 股（`--ashare-only`）

| 代码 | 阶段 | 方向 | 评分 | RS | 关键信号 | 入场区摘要 |
|------|------|------|------|-----|----------|------------|
| sh.600519 | Distribution Phase C/D | 观望 | 49 | falling | JOC+SOW 冲突→SOW | SOW 待 FTI/Upthrust 确认 |
| sz.000001 | Accumulation Phase C | 观望 | 55 | falling | Spring+LPS 无 JOC | 等待 JOC 或 LPS 回测 |

## Phase 24–25 改进已验证

1. **600519** — 派发 suppression 后 JOC 不参与做多；SOW 无 FTI → 观望（Phase 25 第五步）
2. **600519** — RS falling + 派发语境；评分 49（上限/冲突惩罚生效）
3. **000001** — Spring 无 JOC → 观望；LPS 无 JOC 不计入有效入场（Phase 24 评分门控）
4. **000001** — RS falling；评分上限 55（Phase 24）
5. **000001** — PS 已检测；Phase A 硬门槛与 Spring→Phase C 路径一致

## 仲裁摘要

| 代码 | 主导信号 | 理由 |
|------|----------|------|
| 600519 | sow | 派发语境 SOW 优先于 JOC |
| 000001 | spring | 无 JOC 确认，Spring 结构优于 LPS |

## 数据层

- A 股：AkShare 代理失败 → BaoStock 回退正常
- RS 指数：AkShare 失败 → BaoStock 回退（399001 等）
- 美股/港股：Yahoo 429 限流 → `--cache-only`

## 复现

```bash
# 仅 A 股（推荐）
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only

# 162 个 phase 语义测试
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_phase*.py' -q

# 全量 pytest（306 passed）
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q
```
