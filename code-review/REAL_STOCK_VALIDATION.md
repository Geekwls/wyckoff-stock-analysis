# 真实股票验证报告 (Phase 23 后)

**日期:** 2026-05-23  
**脚本:** `scripts/validate_real_stocks.py`  
**结果:** `REAL_STOCK_VALIDATION.json`

## 本轮结果：2/2 A 股（`--ashare-only`）

| 代码 | 状态 | effective_phase | identifier | 方向 | 仲裁 |
|------|------|-----------------|------------|------|------|
| sh.600519 | ✅ | Distribution Phase C/D | C+ 待 FTI | 观望 | SOW 优先于 JOC |
| sz.000001 | ✅ | Accumulation Phase C | C 积累期震仓 | 观望 | Spring 优于 LPS（无 JOC） |

## Phase 19–23 改进已验证

1. **600519** — 派发语境 SOW 优先于 JOC；`effective_phase` 与协调器/仲裁一致
2. **000001** — Spring 无 JOC → 观望；Spring/LPS triage：`无 JOC 确认，Spring 结构优于 LPS`
3. **Phase 22** — 验证脚本输出 `effective_phase`；报告/筛选/定律均读同一权威阶段
4. **Phase 23** — 派发 Phase A/B 中英文格式拦截；观望时仓位强制 0%

## 数据层

- A 股：AkShare 代理失败 → BaoStock 回退正常
- 美股/港股：Yahoo 429 限流 → 使用 `--cache-only` 读 `.cache/yfinance/` 过期缓存

## 复现

```bash
# 仅 A 股（推荐）
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only

# 144 个 phase 语义测试
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_phase*.py' -q

# 全量 pytest（288 passed）
pip install pytest && PYTHONPATH=src python -m pytest tests/ -q

# Yahoo 限流时用本地过期缓存
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --cache-only
```
