# Phase 15 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 14 已完成

---

## Phase 15a — P0 阻断修复

| ID | 问题 | 修复 |
|----|------|------|
| P0-1 | `breakout_analyzer` 回测/反弹对标量误用 `.any()/.all()` | 改为逐 bar 区间判断 |
| P0-2 | UTAD 无阶段上下文默认 `True` | 默认 `False`，须派发语境 |
| P0-3 | `_is_reaccumulation_context` 匹配 `Distribution Phase D` | 改用 `PhaseAdapter.is_distribution()` |
| P0-4 | TR 向上突破自动改「再积累」 | 维持原阶段，待 JOC 确认 |

## Phase 15b — P1 语义对齐

| ID | 问题 | 修复 |
|----|------|------|
| P1-1 | `sequence_validator` LPS 无 JOC 前置 | 正式 LPS 须 JOC；新增 LPSY↔FTI |
| P1-2 | `event_arbitrator` 时间差用全局 newest/oldest | Spring–LPSY/Upthrust 改成对时间差 |
| P1-3 | `supply_demand` Spring+SOS → Phase D–E | 须 JOC/FTI；否则 C+ 待确认 |
| P1-4 | `TradingPlanGenerator` 吸筹即做多 | Spring 无 JOC → 观望 |
| P1-5 | `facade` conflict/levels JSON 旁路 detect | 改读 `events_detected` |
| P1-6 | `screener_service` LPS/LPSY 独立 detect | 改读 `identify_phase()` |
| P1-7 | `holding_diagnostic` Phase C 即加仓 | 须 JOC；Spring 失效用 Spring 低点 |
| P1-8 | Spring 失败窗口 10 日 vs 孟氏 5 日 | 统一为 5 交易日 |
| P1-9 | `resolve_primary_signal` Spring 无 JOC 仍报 long | 跳过，返回 none/neutral |
| P1-10 | `cause_effect` 独立 `detect_joc_menhongtao` | 改读缓存 `events_detected` |
| P1-11 | Upthrust lifecycle 未下游消费 | `signal_extractor` + `effort_result` |
| P1-12 | `effort_result` legacy 缺 `import pandas` | 已补 |

---

## 测试

```bash
PYTHONPATH=src python -m pytest \
  tests/test_phase15_optimizations.py \
  tests/test_phase14_optimizations.py -q
# 子集回归（见全量 phase 命令）
```
