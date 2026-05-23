# Phase 25 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 24

---

## Phase 25a — 威科夫第五步入场硬门控

| ID | 问题 | 修复 |
|----|------|------|
| P5-1 | JOC 单独即做多 | JOC 无 LPS → 观望；JOC+LPS → 做多 |
| P5-2 | FTI 单独即做空 | FTI 无 LPSY → 观望；FTI+LPSY → 做空 |
| P5-3 | `TradingPlanGenerator` 与引擎不一致 | 同步 JOC+LPS / FTI+LPSY 规则 |

## Phase 25b — 第二/三步方向硬门控

| ID | 问题 | 修复 |
|----|------|------|
| P5-4 | RS/MTF 仅评分上限 | `generate_trading_plan` 硬拦截做多/做空 |
| P5-5 | orchestrator 无 RS | `_enrich_patterns_with_rs()` |
| P5-6 | MTF 冲突详情未传递 | `mtf_conflict_details` → 计划文案 |

---

## 测试

```bash
PYTHONPATH=src python -m unittest tests.test_phase25_optimizations -q
PYTHONPATH=src python -m pytest tests/ -q
```
