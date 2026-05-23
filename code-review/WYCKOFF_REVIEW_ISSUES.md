# 新威科夫代码审查问题清单与修复计划

**文档版本：** v1.1  
**审查日期：** 2026-05-23  
**审查基准：** `references/meng-expert-system.md`、`references/wyckoff-theory-full.md`、`SKILL.md`  
**审查范围：** `src/wyckoff` 核心检测、阶段协调、三大定律、交易建议、报告、批量筛选

> 详细原始审查见同目录 [CODE_REVIEW_REPORT.md](./CODE_REVIEW_REPORT.md)

---

## 一、总体结论

| 维度 | 评价 |
|---|---|
| 检测器理论设计 | 较好（孟氏 Spring/JOC、SOS/SOW 阶段屏蔽、LPS Creek 锚定） |
| 决策链一致性 | **较好**（报告 / orchestrator / 定律 / 轻量 JSON 已同源；VSA 等仍独立 detect） |
| 实盘级可用性 | **接近达标**（派发 suppression、MTF 无信号降级已对齐；需 CI 全量回归） |
| 测试保护 | **较好**（Phase 0–7 语义 + 契约测试；`test_phase4_theory` 已补全） |

**核心根因（已缓解）：** 缺乏单一事实源。主链 `PhaseCoordinator.collect_all_events()` → `identify_phase()['events_detected']` 已通过 `SignalExtractor.build_scoring_payload()` 贯通报告与 orchestrator。

---

## 二、已修复项（当前工作区）

| # | 问题 | 状态 |
|---|---|---|
| F1 | SOS/SOW 模型化后丢失 `signals/latest` | ✅ 已修 |
| F2 | Spring 置信度 `close_position` 量纲错误 | ✅ 已修 |
| F3 | JOC 模型化丢失 latest 字段 | ✅ 已修 |
| F4 | LPS 锚定 TR 下沿而非 Creek | ✅ 已修 |
| F5 | 报告/orchestrator 未传 SOS/JOC 给 LPS | ✅ 已修 |
| F6 | SOS/SOW 误用 `strong=2.5x` | ✅ 已修 |
| F7 | PhaseCoordinator 用 classic Spring | ✅ 已修 |
| F8 | 交易计划对 EventsModel 直接 `.get()` | ✅ 已修 |
| F9 | VSA 报告读顶层字段 | ✅ 已修 |
| F10 | SequenceValidator 价格 dict 比较 | ✅ 已修 |
| F11 | 数据源硬依赖 | ✅ 已修 |
| F12 | Orchestrator 与报告派发 suppression 不一致 | ✅ Phase 8 |
| F13 | `resolve_primary_signal` 无信号时假造 Spring/long | ✅ Phase 8 |
| F14 | Upthrust 误用 Spring normalize（`latest_upthrust` 丢失） | ✅ Phase 8 |
| F15 | Orchestrator MTF 缺周线 resample 回退 | ✅ Phase 8 |
| F16 | 供求定律 TR fallback 条件过宽 | ✅ Phase 8 |

---

## 三、待修复问题（按优先级）

### P0 — 阻断级（均已修复）

| ID | 问题 | 位置 | 状态 |
|---|---|---|---|
| P0-1 | 报告三重检测，展示/评分/仲裁不同源 | `report_generator.py` | ✅ Phase 1 |
| P0-2 | 轻量 JSON 用 classic Spring | `facade.py` | ✅ Phase 1 |
| P0-3 | 三大定律绕开主事件链 | `laws/*.py` | ✅ Phase 1 |
| P0-4 | JOC 回测确认过宽 | `meng_trend_detector.py` | ✅ Phase 2 |
| P0-5 | Breakout 不限定 TR 时间窗 | `breakout_analyzer.py` | ✅ Phase 2 |

### P1 — 高优先级

| ID | 问题 | 位置 | 状态 |
|---|---|---|---|
| P1-1 | Phase D 缺 JOC 硬约束 | `phase_identifier.py` | ✅ Phase 2 |
| P1-2 | Orchestrator 目标位偏离 P&F | `orchestrator.py` | ✅ Phase 3 |
| P1-3 | P&F 混入历史同价位列 | `point_and_figure.py` | ✅ Phase 3 |
| P1-4 | 持仓诊断用 classic Spring | `holding_diagnostic.py` | ✅ Phase 1 |
| P1-5 | 派发 suppression 与 breakout override | `signal_extractor.py` | ✅ Phase 4b + 8 |
| P1-6 | EVR 总体漏 AT_HIGH/AT_LOW | `effort_result.py` | ✅ Phase 1 |
| P1-7 | Meng VSA 历史均量 | `meng_vsa_detector.py` | ✅ Phase 3 |
| P1-8 | MTF 小时线非威科夫语义 | `multi_timeframe_coordinator.py` | ✅ Phase 4 |
| P1-9 | `BRK-B` 误判 crypto | `symbol_resolver.py` | ✅ Phase 3 |

### P2 — 中优先级

| ID | 问题 | 位置 | 状态 |
|---|---|---|---|
| P2-1 | Breakout 评分从 50 起步 | `breakout_analyzer.py` | ✅ Phase 2 |
| P2-2 | WIE 熵阈值硬编码 | `state_engine.py` | ✅ Phase 4 |
| P2-3 | RS MA50 数据不足 | `relative_strength_analyzer.py` | ✅ Phase 4 |
| P2-4 | 市场广度 SKIPPED 语义 | `market_context_analyzer.py` | ✅ Phase 4 |
| P2-5 | 测试偏结构断言 | `tests/` | ✅ Phase 7 |

### 可选后续（非阻断）

| ID | 问题 | 说明 |
|---|---|---|
| O-1 | VSA / dead_corner 不在 EventsModel | 报告仍各 detect 一次，设计如此 |
| O-2 | CI 全量 pytest | 本地需 venv；建议在 GitHub Actions 跑全量 |
| O-3 | `test_phase3_theory` P&F 方向断言 | 合成数据需与 P&F 列生成对齐 |

---

## 四、修复进度

| Phase | 内容 | 状态 |
|---|---|---|
| Phase 1 | P0-1 ~ P0-3, P1-4, P1-6 统一事实源 | ✅ 已完成 |
| Phase 2 | P0-4, P0-5, P1-1 JOC/Breakout/Phase D | ✅ 已完成 |
| Phase 3 | P1-2, P1-3, P1-7, P1-9 因果/MTF/工程 | ✅ 已完成 |
| Phase 4 | P1-8, P2-* 工程收尾 + 语义测试 | ✅ 已完成 |
| Phase 5 | MTF 统一 / phase 缓存 / Analyzer 同源 | ✅ 已完成 |
| Phase 6 | P0 契约：SOS/SOW/Spring/EventsModel | ✅ 已完成 |
| Phase 7 | 语义级测试：SOS 1.5x / LPS Creek / 报告&定律一致性 | ✅ 已完成 |
| Phase 8 | 审查 P0 收尾：orchestrator 同源 / none 信号 / upthrust normalize | ✅ 已完成 |
| Phase 9–12 | 深度审查 + 架构收尾 + 门控/Phase E/VSA + 金样本 | ✅ 已完成 |

---

## 五、语义级测试清单

- [x] Spring `close_position=0.85` 获得收盘位置满分档 (`tests/test_phase0_contracts.py`)
- [x] SOS 1.5x 放量应检测到 (`tests/test_phase7_semantic.py`)
- [x] LPS 在 SOS/JOC 后、锚定 Creek±ATR (`tests/test_phase7_semantic.py`)
- [x] Phase D 无 JOC 不应返回 Phase D (`tests/test_phase2_theory.py`)
- [x] Distribution 目标位向下 (`tests/test_phase3_theory.py`)
- [x] 报告 vs `events_detected` 字段一致 (`tests/test_phase7_semantic.py`)
- [x] `BRK-B` → US_STOCK (`tests/test_phase3_theory.py`)
- [x] 三大定律 Spring 与主链一致 (`tests/test_phase7_semantic.py`)
- [x] MTF 小时线 LPS 锚点入场 (`tests/test_phase4_theory.py`)
- [x] WIE 熵阈值读配置 (`tests/test_phase4_theory.py`)
- [x] RS 数据不足用 MA20 斜率 (`tests/test_phase4_theory.py`)
- [x] 市场广度 SKIPPED 不参与环境修正 (`tests/test_phase4_theory.py`)
- [x] SOS/SOW 进入 EventsModel 后 latest 字段不丢失 (`tests/test_phase0_contracts.py`)
- [x] 批量评分 EventsModel 信号计数 (`tests/test_phase0_contracts.py`)
- [x] Orchestrator 派发 suppression 与报告一致 (`tests/test_phase4_theory.py`)
- [x] 无信号时 `resolve_primary_signal` → none/neutral (`tests/test_phase4_theory.py`)
- [x] Upthrust `latest_upthrust` normalize (`tests/test_phase0_contracts.py`)
- [x] Phase 9：JOC 优先 / FTI Phase D / CHoCH 归一化 (`tests/test_phase9_theory.py`)
- [x] Phase 12：Spring normalize + 金样本 (`tests/test_phase12_golden.py`)

---

## 六、Phase 1 验收标准

1. `generate_report()` / `generate_json()` 仅调用一次 `identify_phase()` — ✅
2. 报告展示事件与 `events_detected` 字段级一致 — ✅
3. `generate_phase_json()` 与主链 Spring 结论一致 — ✅
4. `analyze_supply_demand_law()` 不再调用 `detect_spring()` — ✅
5. `holding_diagnostic` 只读 `events_detected` — ✅
6. `orchestrator.run_analysis()` 评分输入与报告同源（`build_scoring_payload`） — ✅ Phase 8

---

## 七、Phase 9 深度审查（见 [DEEP_REVIEW_ISSUES.md](./DEEP_REVIEW_ISSUES.md)）

### 9a — 已修复

| ID | 问题 | 位置 | 状态 |
|----|------|------|------|
| B1 | Phase B 优先于 JOC | `phase_identifier.py` | ✅ |
| B2 | CHoCH 方向枚举不一致 | `phase_coordinator.py`, `utils.py` | ✅ |
| B3 | 派发 Phase D 无 FTI 硬约束 | `phase_identifier.py` | ✅ |
| B5 | Spring 向量化/迭代量比不一致 | `meng_reversal_detector.py` | ✅ |

### 9b — 待修复

B4, B6–B8, B9–B15 — 详见 [DEEP_REVIEW_ISSUES.md](./DEEP_REVIEW_ISSUES.md)
