# Phase 27 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 26

---

## Phase 27a — 阶段识别理论对齐

| ID | 问题 | 修复 |
|----|------|------|
| P7-1 | fallback 纯均线标 Phase E | → `UNKNOWN` + Trending Bullish/Bearish 待事件确认 |
| P7-2 | 方案 B 多头 BC 直标 Markup E | → `Distribution Phase A` BC 警示 |
| P7-3 | Phase A 直跳 Phase C（跳过 B） | `_transition_from_phase_a` 只进 Phase B |
| P7-4 | `calculate_sequence_score` 仅 5 项 | 扩展至 11 项（含 PS/PSY/JOC/FTI/正式 LPS/LPSY） |

## Phase 27b — Spring 生命周期同步

| ID | 问题 | 修复 |
|----|------|------|
| P7-5 | 1 号 Spring 协调器仍升 Phase C | `needs_secondary_test` → Phase B |
| P7-6 | `validate_phase_consistency` 一律升 C | 调用 `_phase_from_spring_signal` 映射 |

---

## 测试

```bash
PYTHONPATH=src python -m unittest tests.test_phase27_optimizations -q
PYTHONPATH=src python -m unittest discover -s tests -p 'test_phase*.py' -q
```
