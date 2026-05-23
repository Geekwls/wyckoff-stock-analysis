# Phase 14 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 13 已完成

---

## Phase 14a — P0/P1（已完成）

| ID | 问题 | 修复 |
|----|------|------|
| P0-1 | 主链 JOC 走 classic 非孟氏 | `detect_joc()` 孟氏优先 + classic fallback |
| P0-2 | coordinator 覆盖后 phase_description 矛盾 | `_merge_coordinator_phase` 清除/替换描述 |
| P1-1 | 孤立 SOW 阶段标签偏低 | `_detect_phase_c_plus_signals` BC+SOW / 孤立 SOW |
| P1-2 | Spring 无 JOC 仍做多 | `RecommendationEngine` 默认观望 |
| P1-3 | CHoCH 单独升 Phase A | 仅 augment 已有 Phase A 结构 |

## Phase 14b — P2（已完成）

| ID | 问题 | 修复 |
|----|------|------|
| P2-1 | `MIN_PHASE_*` 未使用 | A/B/C/D 转换接入最短停留天数 |
| P2-2 | D→E 仅价格确认 | `continuous_price_confirmation(require_volume=True)` |
| P2-3 | VSA/dead_corner 报告二次 detect | 纳入 `EventsModel`，报告读主链 |
| P2-4 | SC+BC 近距仲裁 | `_arbitrate_climax` 前序趋势优先 |
| P2-5 | Phase B 仅 Climax+AR | 须 ST 或 ≥2 次区间测试 |
| P2-6 | 再吸筹过宽 | markup + PS 或 无 BC |
| P2-7 | Shakeout 用 classic Spring | `vsa_detector` 优先孟氏 Spring 结果 |

## Phase 14c — 实盘修复（已完成）

| ID | 问题 | 修复 |
|----|------|------|
| P2-8 | 派发股 JOC 误升 Accumulation Phase D | `_is_accumulation_joc_context` 门控 |

---

## 实盘验证（A 股，Phase 14c 后）

| 代码 | phase | identifier | 方向 | 说明 |
|------|-------|------------|------|------|
| sh.600519 | Distribution Phase A | C+ 待 FTI | 观望 | BC+SOW+JOC 冲突，不再误判吸筹 D |
| sz.000001 | Accumulation Phase C | C+ 待 JOC | 观望 | Spring 无 JOC，符合孟氏 checklist |

---

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_phase14_optimizations \
  tests.test_phase9_theory \
  tests.test_phase10_integration \
  tests.test_phase11_integration \
  tests.test_phase12_golden \
  tests.test_phase13_fixes \
  tests.test_phase2_theory -q
# 52 tests OK
```
