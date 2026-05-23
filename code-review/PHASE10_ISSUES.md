# Phase 10–11 修复清单

**日期：** 2026-05-23  
**前置：** Phase 9 (B1–B15) 已完成

---

## Phase 10 已修复

| ID | 问题 | 修复 |
|----|------|------|
| R-P0-3 | Meng `spring_type` int 1/2/3 与 preliminary 字符串不匹配 | `PhaseCoordinator._phase_from_spring_signal()` |
| R-P0-1 | 协调器 `final_phase` 未合并进用户可见阶段 | `pattern_detector._merge_coordinator_phase()` + `EventsModel.coordinator_final_phase` |
| R-P1-2 | LPS 无 JOC 可升 Phase D | `_check_logical_consistency` 改为 C+ 待 JOC |
| R-P1-3 | C→D 允许 LPS 单独触发 | `_transition_from_phase_c` 仅 JOC/FTI |
| R-P1-4 | 孤立 SOW 仍做空 | 对称 B14 → 观望 |
| R-P1-5 | Spring lifecycle 未下游消费 | `recommendation_engine` + `signal_extractor` 拦截 failed |
| R-P1-7 | SC-only 仍正式 Phase A | `SC待AR确认` / `BC待AR确认` + 无 PS/PSY 兜底 |

---

## Phase 11 已修复

| ID | 问题 | 修复 |
|----|------|------|
| R-P0-2 | 单次检测 + 初步阶段门控 | `_apply_strength_signal_gating` + `_recollect_strength_events` |
| R-P2-2 | Phase E 路径分裂 | `_maybe_upgrade_to_phase_e` + `continuous_price_confirmation` |
| R-P2-1 | VSA Phase B 分支死代码 | `EventsModel.vsa_signals` + `_normalize_vsa_signals` |
| — | E2E `identify_phase()` | `tests/test_phase11_integration.py` |
| — | `has_ps` KeyError | `_get_phase_a_structure_status` 字段名修正 |
| — | utils 导入路径 | `phase_coordinator` `from .utils import ...` |

---

## 仍待优化

| 项 | 说明 |
|----|------|
| ~~SpringModel normalize~~ | ✅ Phase 12：`_normalize_spring_signal` / `_normalize_upthrust_signal` |
| ~~金样本 OHLCV~~ | ✅ `tests/test_phase12_golden.py` SC→Spring→JOC 管道 |

---

## Phase 12 已修复

| 项 | 说明 |
|----|------|
| Spring Pydantic | Meng `vol_ratio` → `volume_ratio`，补全 `breakdown_date` 等必填项 |
| Upthrust Pydantic | `close_position` → `close_from_high` |
| 金样本 | `_build_golden_df()` + `collect_all_events` / `identify_phase` 无校验错误 |

---

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_phase9_theory \
  tests.test_phase9b_theory \
  tests.test_phase10_integration \
  tests.test_phase11_integration \
  tests.test_phase12_golden \
  tests.test_phase2_theory -v
```
