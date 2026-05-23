# 深度审查问题清单（Phase 9）

**文档版本：** v1.0  
**审查日期：** 2026-05-23  
**审查基准：** `references/meng-expert-system.md`、`SKILL.md`、深度代码 walkthrough  
**关联文档：** [WYCKOFF_REVIEW_ISSUES.md](./WYCKOFF_REVIEW_ISSUES.md)、[CODE_REVIEW_REPORT.md](./CODE_REVIEW_REPORT.md)

---

## 一、背景

Phase 1–8 已解决「单一事实源 / EventsModel 契约 / 报告同源」等工程问题。  
本清单聚焦 **新威科夫理论语义** 与 **阶段判定逻辑** 的剩余缺陷（深度审查结论）。

| 维度 | 评分 | 说明 |
|------|------|------|
| 理论框架完整度 | 8/10 | 全事件链有检测器 |
| 决策链一致性 | 8/10 | 双阶段判定已对齐；仲裁器覆盖 UT/JOC/FTI |
| 吸筹路径 | 8.5/10 | JOC/LPS/Spring 结构锚定 + Phase B 不覆盖 C+ |
| 派发路径 | 7.5/10 | FTI 驱动 Phase D；LPSY @ Ice |
| 实盘可用性 | 7.5/10 | SOS 孤立信号降级观望；Phase E 阶段感知 |

---

## 二、问题清单（按 ID）

### P0 — 阻断级

| ID | 问题 | 位置 | 理论依据 | 状态 |
|----|------|------|----------|------|
| B1 | Phase B 主动检测优先于 JOC，完整序列下 JOC 无法升 Phase D | `phase_identifier.py` `_determine_phase_from_events` | 孟氏：JOC = Phase D 吸筹突破 | ✅ 9a |
| B2 | CHoCH 方向枚举不一致（`bullish/bearish` vs `up/down`） | `phase_coordinator.py` 初步阶段识别 | CHoCH 升级逻辑失效 | ✅ 9a |
| B3 | 派发 Phase D 无 FTI 硬约束（吸筹有 JOC 对称） | `phase_identifier.py` | 孟氏 §2.2：FTI → LPSY | ✅ 9a |

### P1 — 高优先级

| ID | 问题 | 位置 | 理论依据 | 状态 |
|----|------|------|----------|------|
| B4 | Spring 支撑用 rolling 20d low，非 TR/SC 低点 | `meng_reversal_detector.py` | Spring 应测试积累区支撑 | ✅ 9b |
| B5 | Spring 向量化(1.2x) vs 迭代(1.0x) 量比阈值不一致 | `meng_reversal_detector.py` | 孟氏收回量 > 跌破量 | ✅ 9a |
| B6 | EventArbitrator 未纳入 Upthrust/JOC/FTI | `event_arbitrator.py` | Spring vs UT 常见冲突 | ✅ 9c |
| B7 | LPSY 锚 MA20 非 Ice，且无 FTI 前置 | `strength_weakness_detector.py` | 对称 LPS @ Creek | ✅ 9b |
| B8 | Phase A 仅 PS 即可标正式 Accumulation Phase A | `phase_coordinator.py` | PS→SC→AR→ST 链条 | ✅ 9b/10 |

### P2 — 中优先级

| ID | 问题 | 位置 | 状态 |
|----|------|------|------|
| B9 | 长周期启发式用 TR 位置跳 Phase C/D | `phase_coordinator.py` | ✅ 9d |
| B10 | Phase D→E 用 3 日 80% 同向 K 线 | `phase_coordinator.py` | ✅ 9d |
| B11 | LPS 要求 Close > MA20，漏检 Creek 浅回踩 | `strength_weakness_detector.py` | ✅ 9c |
| B12 | JOC 要求 `is_consolidation`，再吸筹可能漏检 | `meng_trend_detector.py` | ✅ 9d |
| B13 | Spring 在仲裁器中 signals + latest 重复 | `event_arbitrator.py` | ✅ 9c |
| B14 | SOS alone 仍给交易计划「做多」 | `recommendation_engine.py` | ✅ 9c/10 (SOW 对称) |
| B15 | Upthrust 无 lifecycle（Spring 有 failed/confirmed） | `meng_reversal_detector.py` | ✅ 9b/10 (下游拦截) |

---

## 三、Phase 9 修复计划

| 批次 | 内容 | 问题 ID | 状态 |
|------|------|---------|------|
| 9a | JOC/FTI 优先于 Phase B；派发 FTI 硬约束；CHoCH 枚举统一；Spring 量比 | B1, B2, B3, B5 | ✅ 已完成 |
| 9b | Spring 支撑/TR 锚点；LPSY @ Ice；Phase A 收紧；Upthrust lifecycle | B4, B7, B8, B15 | ✅ 已完成 |
| 9c | 仲裁器扩展；LPS MA20 放宽；SOS 观望；语义测试补全 | B6, B11, B13, B14 + 测试 | ✅ 已完成 |
| 9d | 长周期启发式降级；Phase E 规则；JOC consolidation | B9, B10, B12 | ✅ 已完成 |
| 10 | Spring 类型映射；阶段权威合并；LPS/JOC；SOW 对称；lifecycle | R-P0-1/3, R-P1-2~5, R-P1-7 | ✅ 已完成 |

---

## 四、语义测试清单（Phase 9 新增）

- [x] Climax+AR+2LPS+JOC → 必须 Phase D（B1）
- [x] Upthrust+SOW 无 FTI → 最高 Phase C+，非 Phase D（B3）
- [x] CHoCH `bullish`/`up` 别名归一化（B2）
- [x] FTI detected → Distribution Phase D（B3）
- [x] Spring 向量化/迭代量比阈值一致（B5）
- [x] PS-only → `PS待SC确认`，非正式 Phase A（B8）
- [x] Spring 结构支撑锚定 SC/TR（B4）
- [x] LPSY 锚 Ice + FTI 前置（B7）
- [x] 孤立 SOS → 交易计划「观望」（B14）
- [x] EventArbitrator 纳入 UT/JOC/FTI，Spring 去重（B6/B13）
- [x] Phase D→E 阶段感知确认（B10）

---

## 五、因果链合规矩阵（审查快照）

### 吸筹

```
PS → SC → AR → ST → Phase B → Spring → SOS → JOC → LPS → Phase E
 ✅    ✅   ✅   ⚠️     ⚠️       ✅      ✅    ✅    ✅      ⚠️
```

### 派发

```
PSY → BC → AR → ST → Upthrust → SOW → FTI → LPSY → Phase E
 ✅    ⚠️   ✅   ✅      ✅       ⚠️*   ✅    ✅       ⚠️
```
\* 孤立 SOW 已改观望（Phase 10）；FTI Phase D 已强制（B3）
