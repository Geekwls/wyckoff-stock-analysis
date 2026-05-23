# Phase 17 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 16 已完成

---

## Phase 17a — EventArbitrator 配对规则

| ID | 问题 | 修复 |
|----|------|------|
| P1-1 | SOW+JOC 冲突仅时间优先（600519 误倾向 JOC） | 新增 `_arbitrate_joc_sow`：派发语境 SOW 优先 |
| P1-2 | JOC+FTI 无专用规则 | 新增 `_arbitrate_joc_fti`：按吸筹/派发语境裁决 |
| P1-3 | 仲裁器无阶段语境 | `arbitration_raw` 注入 `_phase_context` / `_climax_type` |

## Phase 17b — MTF Coordinator EVR

| ID | 问题 | 修复 |
|----|------|------|
| P1-4 | Coordinator 未接 EVR 跨周期共振 | `_build_evr_context` + `_detect_weekly_evr` |
| P1-5 | 强共振建议未门控 JOC/FTI | `_generate_resonance_recommendation` 对齐孟氏 checklist |
| P1-6 | EVR 共现未提升共振档位 | weekly EVR + Spring/UT → medium/strong 升档 |

---

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_phase17_optimizations \
  tests.test_phase16_optimizations \
  tests.test_phase15_optimizations -q
```
