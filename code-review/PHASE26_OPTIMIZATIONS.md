# Phase 26 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 25

---

## Phase 26a — LPS 正式性契约贯通

| ID | 问题 | 修复 |
|----|------|------|
| P6-1 | `support_test` 误标 `lps.detected=True` | 出口仅 `signal_type=='lps'` 为真；保留 `observation_detected` |
| P6-2 | 下游消费层不读 `signal_type` | `SignalExtractor.is_formal_lps()` 统一 scoring/计划/阶段升级 |
| P6-3 | `phase_identifier` SC+AR+ST→Phase B 死代码 | 修复分支顺序 |
| P6-4 | PS/PSY 硬门槛在 identifier 仍为软门控 | 缺 PS/PSY → `UNKNOWN` 低置信 |
| P6-5 | PSY 未计入结构完整性 | `_calculate_structural_integrity` 按 climax 类型计 PS/PSY |

## Phase 26b — 双轨决策链同步

| ID | 问题 | 修复 |
|----|------|------|
| P6-6 | `TradingPlanGenerator` 与 RE 门控分裂 | Phase E / 再派发 / RS / MTF 同步 |
| P6-7 | Risk Advice MTF aggressive 仍鼓励试错 | 与计划层一致 → 观望 0% |
| P6-8 | EventsModel 不做 120 日过滤 | identify 路径转 dict 后 `filter_relevant_events` |
| P6-9 | 因果定律 phase 非 effective | `cause_effect.py` 用 `get_effective_phase()` |

---

## 测试

```bash
PYTHONPATH=src python -m unittest tests.test_phase26_optimizations -q
PYTHONPATH=src python -m pytest tests/ -q
```
