# Phase 19 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 18 已完成

---

## Phase 19a — P0 阻断修复

| ID | 问题 | 修复 |
|----|------|------|
| P0-1 | 孤立 Spring/Upthrust 可直接标 Phase C | 须 Phase A 完整（Climax+AR+ST）；Spring/Upthrust 判定优先于 Phase B |
| P0-2 | `TradingPlanGenerator` 派发路径无 FTI 门控 | 对齐 `RecommendationEngine`：FTI/Phase E/SOW+Phase D 才做空，否则观望 |
| P0-3 | LPSY `detected` 含 weak_reactions | 仅 `signal_type=='lpsy'` 置 `detected=True` |
| P0-3b | `resolve_primary_signal` LPSY 无 FTI 门控 | 对称 Upthrust，须 FTI 才返回 short |

## Phase 19b — P1 语义对齐

| ID | 问题 | 修复 |
|----|------|------|
| P1-1 | `_has_complete_phase_a` 用 OR | 改为 `has_climax and has_ar and has_st` |
| P1-3 | 孟氏 1 号 Spring 无 `needs_secondary_test` | `_build_spring_signal` type 1 设 `needs_secondary_test=True` |
| P1-5 | 供求定律 Spring+SOS → Phase D-E | 须 JOC/FTI 才标 D-E，否则 C+ 待确认 |
| P1-6 | Climax+ST 无 AR → Phase B | 须 AR+ST 齐备 |
| P1-4 | fallback 吸收直跳 Phase D | 无 JOC → C+ 待 JOC；`_fallback_logic` 统一 4-tuple |
| P1-7 | Phase D→E 仅 3 日确认 | 须 LPS（吸筹）/ LPSY（派发）才升级 Phase E |

---

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_phase19_optimizations \
  tests.test_phase2_theory \
  tests.test_phase11_integration -q

# 全量 phase 测试
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_phase*.py' -q
# 124 tests OK
```

## 复现

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only
```
