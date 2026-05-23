# Phase 20 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 19 已完成

---

## Phase 20a — 仲裁 / 门控 / 因果对称

| ID | 问题 | 修复 |
|----|------|------|
| P2-4 | EventArbitrator 未纳入 LPS | 提取 LPS + `_triage_bullish_signals`：JOC 后 LPS 优于 Spring |
| P2-1 | `register_high_priority_signal` 死代码 | JOC/FTI 先于 SOS/SOW 检测并注册高优先级 |
| P2-5 | 死角突破 `STRONG_BUY` 无 JOC 门控 | `_apply_dead_corner_joc_gate` + `_generate_breakout_trading_advice` 降级 WATCH |
| P2-6 | 因果定律突破概率仅查 JOC | 派发侧对称读取 FTI Weis 质量 |
| P2-3 | Spring 支撑混用 rolling max | 有 SC/TR 结构时仅用结构价位，rolling 仅 fallback |

---

## 测试

```bash
PYTHONPATH=src python -m pytest \
  tests/test_phase20_optimizations.py \
  tests/test_phase19_optimizations.py -q

# 全量 phase 测试
PYTHONPATH=src python -m pytest tests/test_phase*.py -q
```

## 复现

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only
```
