# Phase 21 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 20 已完成

---

## Phase 21a — CHoCH 单一事实源

| ID | 问题 | 修复 |
|----|------|------|
| P2-2 | 双 CHoCH 实现（简化 vs Weis Wave） | `utils.detect_choch_weis()` 为唯一实现 |
| — | Meng / SW / PatternDetector 各自检测 | 三者均委托 `detect_choch_weis` |
| — | direction 枚举不一致 | `normalize_choch_result()` 统一 bullish/bearish |

## Phase 21b — 阶段双权威

| ID | 问题 | 修复 |
|----|------|------|
| P2-7 | coordinator 无 revision 也覆盖 identifier | 仅 `[事件仲裁]` 等 marker 才 override |
| — | 消费方 phase/coordinator_phase 混读 | `SignalExtractor.get_effective_phase()` 单一权威 |
| — | orchestrator / scoring / suppression 不同源 | 全部改读 `effective_phase` |

---

## 测试

```bash
PYTHONPATH=src python -m pytest \
  tests/test_phase21_optimizations.py \
  tests/test_phase10_integration.py \
  tests/test_phase9_theory.py -q

PYTHONPATH=src python -m pytest tests/test_phase*.py -q
```

## 复现

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only
```
