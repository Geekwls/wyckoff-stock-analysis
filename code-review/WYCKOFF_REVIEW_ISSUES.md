# 新威科夫代码审查问题清单与修复计划

**文档版本：** v2.3（Phase 27 增量）  
**审查日期：** 2026-05-23  
**审查基准：** `references/meng-expert-system.md`、`references/wyckoff-theory-full.md`、`SKILL.md`  
**审查范围：** `src/wyckoff` 核心检测、阶段协调、三大定律、交易建议、报告、批量筛选

> 详细原始审查见 [CODE_REVIEW_REPORT.md](./CODE_REVIEW_REPORT.md)  
> Phase 15–23 增量见 [PHASE15_OPTIMIZATIONS.md](./PHASE15_OPTIMIZATIONS.md) … [PHASE23_OPTIMIZATIONS.md](./PHASE23_OPTIMIZATIONS.md)  
> Phase 24–27 见 [PHASE24_OPTIMIZATIONS.md](./PHASE24_OPTIMIZATIONS.md) … [PHASE27_OPTIMIZATIONS.md](./PHASE27_OPTIMIZATIONS.md)

---

## 一、总体结论（Phase 27 后）

| 维度 | 评价 |
|---|---|
| 检测器理论设计 | **良好**（PS/PSY 硬门槛、Spring/JOC、FTI/LPSY 对称、LPS 正式性） |
| 决策链一致性 | **优秀**（主链 + TPG + Risk Advice + 因果定律同源） |
| 阶段路径 | **良好**（A→B→C；1 号 Spring→Phase B；fallback 不标 E） |
| 实盘级可用性 | **达标**（A 股 2/2；派发 suppression + 第五步门控） |
| 测试保护 | **良好**（186 个 `test_phase*.py` + 342 pytest；CI workflow） |

**核心根因（已解决）：** 缺乏单一事实源 + 正式信号语义未贯通 → Phase 26–27 统一 `SignalExtractor.is_formal_lps()` 与阶段路径约束。

---

## 二、待修复问题 — 全部已关闭

### P0 / P1 / P2（Phase 1–18）

见下文历史表格，**均已 ✅**。

### Phase 19–25 摘要

见 [PHASE19_OPTIMIZATIONS.md](./PHASE19_OPTIMIZATIONS.md) … [PHASE25_OPTIMIZATIONS.md](./PHASE25_OPTIMIZATIONS.md)

### Phase 26–27 增量（2026-05-23）

| Phase | 核心修复 |
|-------|----------|
| 26 | LPS 正式性契约；Phase B 死代码；PS/PSY 硬门槛；TPG/RE/Risk 同步；EventsModel 120 日过滤 |
| 27 | fallback/方案B 禁无事件 Phase E；A 不直跳 C；序列评分 11 项；1 号 Spring→Phase B |

**实盘复验：** [REAL_STOCK_VALIDATION.md](./REAL_STOCK_VALIDATION.md) — A 股 2/2 ✅

### 可选后续（非阻断，保留观察）

| ID | 说明 | 状态 |
|---|---|---|
| O-1 | VSA / dead_corner 独立 detect | 设计如此，已 JOC 门控 |
| O-2 | CI 全量 pytest | ✅ Phase 23+ workflow |
| O-3 | P&F 合成数据方向断言 | ✅ `test_phase3_theory` 通过 |
| O-4 | 美股/港股实盘样本扩充 | 观察（Yahoo 429 → `--cache-only`） |
| O-5 | dead_corner FTI 对称门控 | 观察 |

---

## 三、修复进度（完整）

| Phase | 内容 | 状态 |
|---|---|---|
| Phase 1–8 | 单一事实源 / orchestrator 同源 | ✅ |
| Phase 9–12 | 深度审查 B1–B15 + 金样本 | ✅ |
| Phase 13–18 | 派发 suppression / 仲裁扩展 / 验证脚本 | ✅ |
| Phase 19–25 | P0/P1/P2 收尾 + effective_phase + 第五步门控 | ✅ |
| Phase 26–27 | LPS 正式性 + 双轨同步 + 阶段路径 + fallback | ✅ |

---

## 四、语义级测试（节选，全部通过）

- [x] Spring 无 JOC → 观望（Phase 15–16）
- [x] 孤立 SOS/SOW → 观望（Phase 9–10）
- [x] LPS 须 JOC / LPSY 须 FTI（Phase 15）
- [x] `support_test` 不计入正式 LPS（Phase 26）
- [x] SC+AR+ST → Phase B（Phase 26）
- [x] Phase A 不直跳 C（Phase 27）
- [x] 1 号 Spring → Phase B 待二次测试（Phase 27）
- [x] fallback 纯均线不标 Phase E（Phase 27）

**运行：** `PYTHONPATH=src python -m pytest tests/test_phase*.py -q` → 186 tests OK

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
