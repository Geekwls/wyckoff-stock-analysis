# Phase 16 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 15 已完成

---

## Phase 16a — Phase A 门槛

| ID | 问题 | 修复 |
|----|------|------|
| P1-1 | 正式 Phase A 仅须 Climax+AR | 须 **Climax+AR+ST** |
| P1-2 | SC+AR / BC+AR 标正式 Phase A | 改为 `SC+AR待ST确认` / `BC+AR待ST确认` |
| P1-3 | `phase_coordinator` 初步阶段同问题 | 与 identifier 对齐 |

## Phase 16b — MTF / 报告 / Upthrust 对称

| ID | 问题 | 修复 |
|----|------|------|
| P1-4 | MTF 仅多头共振 | 增加 Upthrust/SOW/FTI 派发侧共振 |
| P1-5 | MTF 强共振即「积极建仓」 | Spring 无 JOC → 等待；须 JOC 才建议 LPS 建仓 |
| P1-6 | 周线 EVR 未与 Spring/UT 共现绑定 | `_evr_events` 从主链注入 |
| P1-7 | `conclusion_section` 二次 `collect_all_events` | 改读 `phase_result.events_detected` |
| P1-8 | 孤立 Upthrust 仍做空 | failed / 无 SOW·FTI → 观望 |
| P1-9 | `resolve_primary_signal` Upthrust 无 FTI 仍 short | 跳过，对称 Spring 门控 |
| P1-10 | `report_generator` mock 路径二次 collect | 改 `identify_phase` + `build_scoring_payload` |

---

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_phase16_optimizations \
  tests.test_phase15_optimizations \
  tests.test_phase14_optimizations \
  tests.test_phase2_theory -q
# 29 tests OK（全量 phase 测试 103 OK）
```

---

## 实盘验证

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py
# 或仅 A 股：
PYTHONPATH=src .venv/bin/python -c "
from scripts.validate_real_stocks import analyze_one
for s,m in [('sh.600519','茅台'),('sz.000001','平安')]:
    r=analyze_one(s,m)
    print(s, r['phase'], r.get('identifier_phase'), r['direction'])
"
```

预期（Phase 14–16 逻辑）：
- 600519：派发语境，Spring/JOC 不升吸筹 D，方向观望
- 000001：Spring 无 JOC → 观望
