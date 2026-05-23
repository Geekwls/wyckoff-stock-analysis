# Code Review 文档

本目录存放新威科夫理论相关的代码审查与修复跟踪文档。

| 文件 | 说明 |
|---|---|
| [CODE_REVIEW_REPORT.md](./CODE_REVIEW_REPORT.md) | 原始详细审查报告（729 行） |
| [WYCKOFF_REVIEW_ISSUES.md](./WYCKOFF_REVIEW_ISSUES.md) | 问题清单、修复优先级与进度跟踪 |
| [DEEP_REVIEW_ISSUES.md](./DEEP_REVIEW_ISSUES.md) | 深度理论审查问题清单（Phase 9：B1–B15） |
| [REAL_STOCK_VALIDATION.md](./REAL_STOCK_VALIDATION.md) | 真实股票数据验证报告 |
| [PHASE19–23_OPTIMIZATIONS.md](./PHASE19_OPTIMIZATIONS.md) | Phase 19–23 优化（见各 PHASE*.md） |
| [PHASE24_OPTIMIZATIONS.md](./PHASE24_OPTIMIZATIONS.md) | 评分/计划同步、PS 硬门槛、TR 因果 |
| [PHASE25_OPTIMIZATIONS.md](./PHASE25_OPTIMIZATIONS.md) | 第五步入场、RS/MTF 方向硬门控 |

## 当前状态（Phase 25 后）

- **162** 个 `test_phase*.py` 语义测试通过
- **306** pytest 全量通过
- **单一事实源**：`identify_phase()` → `events_detected` → `build_scoring_payload()`
- **阶段权威**：`SignalExtractor.get_effective_phase()`
- **Phase A 硬门槛**：PS→SC→AR→ST / PSY→BC→AR→ST（`PhaseAdapter.is_phase_a_structure_complete`）
- **第五步入场**：JOC+LPS / FTI+LPSY 才给出方向；否则观望
- **和谐门控**：RS 走弱/MTF 冲突 → 交易计划硬拦截
- **CI**：`phase-theory-tests.yml`（Phase 24/25 regression + unittest + pytest）
- **实盘**：A 股 2/2 — 见 [REAL_STOCK_VALIDATION.md](./REAL_STOCK_VALIDATION.md)
