# Phase 22 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 21 已完成

---

## Phase 22a — effective_phase 消费方统一

| 模块 | 修复 |
|------|------|
| `report_generator.py` | 报告/JSON/conflict 改读 `get_effective_phase()` |
| `header_section.py` / `conclusion_section.py` | 阶段展示统一 |
| `facade.py` / `trading_plan_generator.py` | 轻量 JSON / 交易计划 |
| `holding_diagnostic.py` | 持仓诊断 |
| `screener_service.py` | 批量筛选 5 处 |
| `supply_demand.py` / `effort_result.py` | 三大定律子模块 |
| `recommendation_engine.py` | 冲突/环境评分剩余直读 phase |
| `validate_real_stocks.py` | 输出 `effective_phase` 字段 |

## Phase 22b — CI

| 项 | 修复 |
|----|------|
| GitHub Actions | 新增 `.github/workflows/phase-theory-tests.yml` |
| 覆盖 | `test_phase*.py` 全量（186 tests） |

---

## 测试

```bash
PYTHONPATH=src python -m pytest \
  tests/test_phase22_optimizations.py \
  tests/test_phase21_optimizations.py -q

PYTHONPATH=src python -m pytest tests/test_phase*.py -q
```

## 复现

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only
```
