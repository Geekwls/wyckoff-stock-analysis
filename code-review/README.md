# Code Review 文档

本目录存放新威科夫理论相关的代码审查与修复跟踪文档。

| 文件 | 说明 |
|---|---|
| [CODE_REVIEW_REPORT.md](./CODE_REVIEW_REPORT.md) | 原始详细审查报告（729 行） |
| [WYCKOFF_REVIEW_ISSUES.md](./WYCKOFF_REVIEW_ISSUES.md) | 问题清单、修复优先级与进度跟踪（Phase 1–8） |
| [DEEP_REVIEW_ISSUES.md](./DEEP_REVIEW_ISSUES.md) | 深度理论审查问题清单（Phase 9：B1–B15） |
| [PHASE10_ISSUES.md](./PHASE10_ISSUES.md) | Phase 10 架构收尾与 Phase 11 进度 |
| [REAL_STOCK_VALIDATION.md](./REAL_STOCK_VALIDATION.md) | 真实股票数据验证报告 |
| [PHASE13_FIXES.md](./PHASE13_FIXES.md) | Phase 13 审查问题修复清单 |
| [PHASE14–22_OPTIMIZATIONS.md](./PHASE14_OPTIMIZATIONS.md) | Phase 14–22 威科夫理论优化（见各 PHASE*.md） |
| [PHASE19_OPTIMIZATIONS.md](./PHASE19_OPTIMIZATIONS.md) | Phase 19 P0/P1：Phase C 准入 / FTI 门控 / LPSY |
| [PHASE20_OPTIMIZATIONS.md](./PHASE20_OPTIMIZATIONS.md) | Phase 20：LPS 仲裁 / 高优先级注册 / 死角 JOC |
| [PHASE21_OPTIMIZATIONS.md](./PHASE21_OPTIMIZATIONS.md) | Phase 21：CHoCH 统一 / effective_phase 权威 |
| [PHASE22_OPTIMIZATIONS.md](./PHASE22_OPTIMIZATIONS.md) | Phase 22：报告旁路统一 / CI phase 测试 |
| [PHASE23_OPTIMIZATIONS.md](./PHASE23_OPTIMIZATIONS.md) | Phase 23：中文 Phase A/B 拦截 / pytest CI / 审查结案 |

## 当前状态（Phase 23 后 — 审查结案）

- **144** 个 `test_phase*.py` 语义测试通过
- **单一事实源**：`identify_phase()` → `events_detected` → `build_scoring_payload()`
- **阶段权威**：`SignalExtractor.get_effective_phase()`
- **交易门控**：Spring/Upthrust 须 JOC/FTI；派发 Phase A/B 中英文格式拦截
- **CI**：`phase-theory-tests.yml`（unittest + pytest）
- **实盘**：A 股 2/2 验证通过 — 见 [REAL_STOCK_VALIDATION.md](./REAL_STOCK_VALIDATION.md)
- **总清单**：[WYCKOFF_REVIEW_ISSUES.md](./WYCKOFF_REVIEW_ISSUES.md) v2.0 结案
