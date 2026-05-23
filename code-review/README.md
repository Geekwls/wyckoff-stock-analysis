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
| [PHASE26_OPTIMIZATIONS.md](./PHASE26_OPTIMIZATIONS.md) | LPS 正式性、双轨门控、EventsModel 过滤 |
| [PHASE27_OPTIMIZATIONS.md](./PHASE27_OPTIMIZATIONS.md) | fallback/方案B、A→B 路径、序列评分、Spring ST |

## 当前状态（Phase 27 后）

- **186** 个 `test_phase*.py` 语义测试通过
- **342** pytest 全量通过
- **单一事实源**：`identify_phase()` → `events_detected` → `build_scoring_payload()`
- **阶段权威**：`SignalExtractor.get_effective_phase()`
- **LPS 正式性**：`detected` 仅 `signal_type=='lps'`；`is_formal_lps()` 贯通 scoring/计划/升级
- **Phase A 硬门槛**：PS→SC→AR→ST / PSY→BC→AR→ST；缺 PS/PSY → UNKNOWN
- **Phase 路径**：A→B→C（A 不直跳 C）；1 号 Spring → Phase B 待二次测试
- **第五步入场**：JOC+LPS / FTI+LPSY 才给出方向；否则观望
- **fallback**：纯均线不再标 Phase E
- **CI**：`phase-theory-tests.yml`（单入口 pytest，`-m "not integration"`）
- **实盘**：A 股 2/2 — 见 [REAL_STOCK_VALIDATION.md](./REAL_STOCK_VALIDATION.md)

## 运行测试

```bash
# 全量（CI 同款，默认跳过 integration）
PYTHONPATH=src python -m pytest tests/ -q -m "not integration"

# Phase 语义回归
PYTHONPATH=src python -m pytest tests/test_phase*.py -q

# 单个 phase 文件
PYTHONPATH=src python -m pytest tests/test_phase27_optimizations.py -q
```
