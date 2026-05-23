# 深度审查问题清单（Phase 9）— 结案

**文档版本：** v2.0（结案）  
**审查日期：** 2026-05-23  
**关联：** [WYCKOFF_REVIEW_ISSUES.md](./WYCKOFF_REVIEW_ISSUES.md)、Phase 15–23 优化

---

## 一、背景

Phase 1–8 已解决「单一事实源 / EventsModel 契约 / 报告同源」。  
Phase 9–23 已关闭全部 B1–B15 及后续审查项。

| 维度 | 评分 | 说明 |
|------|------|------|
| 理论框架完整度 | 9/10 | 全事件链 + 门控 + 仲裁 |
| 决策链一致性 | 9/10 | `effective_phase` 单一权威 |
| 吸筹路径 | 9/10 | JOC/LPS/Creek + Phase A 门槛 |
| 派发路径 | 9/10 | FTI/LPSY/Ice + 中文 Phase A/B 拦截 |
| 实盘可用性 | 8.5/10 | A 股验证通过；Yahoo 限流需 cache |

---

## 二、问题清单 — 全部已修复

| ID | 问题 | 修复 Phase | 状态 |
|----|------|------------|------|
| B1 | Phase B 优先于 JOC | 9a | ✅ |
| B2 | CHoCH 方向枚举不一致 | 9a / 21 | ✅ |
| B3 | 派发 Phase D 无 FTI 硬约束 | 9a | ✅ |
| B4 | Spring 支撑非 TR/SC 低点 | 9b / 20 | ✅ |
| B5 | Spring 量比阈值不一致 | 9a | ✅ |
| B6 | 仲裁器未纳入 UT/JOC/FTI | 9c / 17–18 | ✅ |
| B7 | LPSY 锚 MA20 非 Ice | 9b / 19 | ✅ |
| B8 | Phase A 仅 PS 即可标正式 A | 9b / 16 | ✅ |
| B9 | 长周期启发式跳 Phase C/D | 9d | ✅ |
| B10 | Phase D→E 仅 3 日 K 线 | 9d / 19 | ✅ |
| B11 | LPS 要求 Close > MA20 | 9c | ✅ |
| B12 | JOC 要求 is_consolidation | 9d | ✅ |
| B13 | Spring 仲裁重复 | 9c | ✅ |
| B14 | 孤立 SOS 仍做多 | 9c / 10 | ✅ |
| B15 | Upthrust 无 lifecycle | 9b / 10 | ✅ |

---

## 三、因果链合规矩阵（Phase 23 快照）

### 吸筹

```
PS → SC → AR → ST → Phase B → Spring → SOS → JOC → LPS → Phase E
 ✅    ✅   ✅   ✅     ✅       ✅      ✅    ✅    ✅      ⚠️*
```
\* Phase E 须 LPS 推进确认（Phase 19）

### 派发

```
PSY → BC → AR → ST → Upthrust → SOW → FTI → LPSY → Phase E
 ✅    ✅   ✅   ✅      ✅       ✅    ✅    ✅      ⚠️*
```
\* 孤立 SOW 观望；LPSY 须 FTI；中文 Phase A/B 拦截（Phase 23）

---

## 四、验证

```bash
# 144 phase 语义测试
PYTHONPATH=src python -m unittest discover -s tests -p 'test_phase*.py' -q

# A 股实盘
PYTHONPATH=src python scripts/validate_real_stocks.py --ashare-only
```
