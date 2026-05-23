# 新威科夫代码审查问题清单与修复计划

**文档版本：** v2.0（结案）  
**审查日期：** 2026-05-23  
**审查基准：** `references/meng-expert-system.md`、`references/wyckoff-theory-full.md`、`SKILL.md`  
**审查范围：** `src/wyckoff` 核心检测、阶段协调、三大定律、交易建议、报告、批量筛选

> 详细原始审查见 [CODE_REVIEW_REPORT.md](./CODE_REVIEW_REPORT.md)  
> Phase 15–23 增量见 [PHASE15_OPTIMIZATIONS.md](./PHASE15_OPTIMIZATIONS.md) … [PHASE23_OPTIMIZATIONS.md](./PHASE23_OPTIMIZATIONS.md)

---

## 一、总体结论（Phase 23 后）

| 维度 | 评价 |
|---|---|
| 检测器理论设计 | **良好**（孟氏 Spring/JOC、FTI/LPSY 对称、Phase A 完整门槛） |
| 决策链一致性 | **良好**（`effective_phase` 单一权威；报告/筛选/定律/验证脚本同源） |
| 实盘级可用性 | **达标**（派发 suppression、JOC/FTI 门控、A 股验证 2/2） |
| 测试保护 | **良好**（144 个 `test_phase*.py` + pytest 全量；CI workflow） |

**核心根因（已解决）：** 缺乏单一事实源 → `PhaseCoordinator.collect_all_events()` → `identify_phase()` → `SignalExtractor.build_scoring_payload()` → `get_effective_phase()` 贯通全链。

---

## 二、待修复问题 — 全部已关闭

### P0 / P1 / P2（Phase 1–18）

见下文历史表格，**均已 ✅**。

### Phase 19–23 新增修复摘要

| Phase | 核心修复 |
|-------|----------|
| 19 | Phase C 须 Phase A 完整；FTI 门控；LPSY 语义；Phase D→E 须 LPS/LPSY |
| 20 | LPS 仲裁；JOC/FTI 高优先级注册；死角 JOC 门控；FTI 因果对称 |
| 21 | CHoCH Weis Wave 统一；`effective_phase` 权威；协调器 override 收紧 |
| 22 | 报告/筛选/定律/验证脚本 `effective_phase` 统一；CI phase 测试 |
| 23 | 派发 Phase A/B 中文格式拦截；pytest CI；审查结案 |

### 可选后续（非阻断，保留观察）

| ID | 说明 | 状态 |
|---|---|---|
| O-1 | VSA / dead_corner 独立 detect | 设计如此，已 JOC 门控 |
| O-2 | CI 全量 pytest | ✅ Phase 23 workflow |
| O-3 | P&F 合成数据方向断言 | ✅ `test_phase3_theory` 通过 |

---

## 三、修复进度（完整）

| Phase | 内容 | 状态 |
|---|---|---|
| Phase 1–8 | 单一事实源 / orchestrator 同源 | ✅ |
| Phase 9–12 | 深度审查 B1–B15 + 金样本 | ✅ |
| Phase 13–18 | 派发 suppression / 仲裁扩展 / 验证脚本 | ✅ |
| Phase 19–23 | P0/P1/P2 收尾 + effective_phase + CI | ✅ |

---

## 四、语义级测试（节选，全部通过）

- [x] Spring 无 JOC → 观望（Phase 15–16）
- [x] 孤立 SOS/SOW → 观望（Phase 9–10）
- [x] LPS 须 JOC / LPSY 须 FTI（Phase 15）
- [x] Spring/LPS triage：JOC 后 LPS 优先（Phase 20）
- [x] CHoCH Weis Wave 三路径一致（Phase 21）
- [x] `effective_phase` 报告/筛选同源（Phase 22）
- [x] `派发阶段A` 早期派发拦截（Phase 23）

**运行：** `PYTHONPATH=src python -m unittest discover -s tests -p 'test_phase*.py' -q` → 144 tests OK

---

## 五、历史已修复项（Phase 1–8 摘录）

| # | 问题 | 状态 |
|---|---|---|
| F1–F16 | SOS/SOW 模型、Spring 锚点、同源 suppression 等 | ✅ |
| P0-1~P0-5 | 报告三重检测、JOC 回测、Breakout 时间窗 | ✅ |
| P1-1~P1-9 | JOC Phase D、P&F、MTF、symbol_resolver | ✅ |
| P2-1~P2-5 | Breakout 评分、WIE 熵、RS、测试语义 | ✅ |

---

## 六、Phase 9 深度审查

见 [DEEP_REVIEW_ISSUES.md](./DEEP_REVIEW_ISSUES.md) — **B1–B15 全部 ✅**

---

## 七、实盘验证

见 [REAL_STOCK_VALIDATION.md](./REAL_STOCK_VALIDATION.md)

```bash
PYTHONPATH=src python scripts/validate_real_stocks.py --ashare-only
```
