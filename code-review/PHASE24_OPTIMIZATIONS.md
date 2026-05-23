# Phase 24 威科夫审查优化清单

**日期：** 2026-05-23

---

## Phase 24a — 评分/计划/协调器同步

| ID | 问题 | 修复 |
|----|------|------|
| P4-1 | 死角突破无 JOC 仍 +25/托底 85 | `_dead_corner_actionable()` 与 coordinator JOC gate 同源 |
| P4-2 | LPS/LPSY 无 JOC/FTI 仍加分 | 评分 loop 门控 |
| P4-3 | JOC/FTI 入场描述缺 LPS/LPSY | `generate_trading_plan` 标准入场文案 |
| P4-4 | Spring 收回天数两套标准 | `spring_max_recovery_days()` 单一事实源 |
| P4-5 | 因果 fallback 用 60 日高低 | `_resolve_tr_bounds()` 优先 TR |
| P4-6 | 报告 VSA/死角 fallback detect | 完全依赖 `events_detected` |
| P4-7 | RS/MTF 未影响评分 | 评分上限 55/50 |

## Phase 24b — Phase A PS/PSY 硬门槛

| ID | 修复 |
|----|------|
| P4-8 | `PhaseAdapter.is_phase_a_structure_complete()` — PS→SC→AR→ST / PSY→BC→AR→ST |
| P4-9 | 再吸筹/再派发：AR+ST 无 climax 可豁免 |
| P4-10 | LPS 检测 / Spring→Phase C 同步硬门槛 |

---

## 测试

```bash
PYTHONPATH=src python -m pytest tests/test_phase24_optimizations.py -q
PYTHONPATH=src python -m pytest tests/test_phase*.py -q
```
