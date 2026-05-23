# Phase 13 审查问题修复

**日期：** 2026-05-23

## 已修复

| ID | 问题 | 修复 |
|----|------|------|
| P0-1 | Orchestrator `analysis_cache=None` 崩溃 | `WyckoffOrchestrator` 注入 LRU cache |
| P0-2 | Phase B 吸收得分文案覆盖 `phase` 标签 | `_detect_phase_b_active` 保留标签，文案进 `phase_description` |
| P1-1 | Coordinator 合并在无仲裁 marker 时不生效 | `_merge_coordinator_phase` 默认以 `coordinator_final_phase` 为准 |
| P1-2 | 派发 suppression 只认英文 `Distribution` | `PhaseAdapter.is_distribution` + `coordinator_phase` |
| P1-3 | Markdown/派发 + Spring 仍做多 | `generate_trading_plan` bearish 结构拦截 |
| P1-4 | Spring 在派发上下文无条件升 Accumulation | `_preliminary_phase_identification` 门控 |
| P1-5 | Orchestrator 市场环境恒为 UNKNOWN | `SymbolResolver.resolve_benchmark_index` + `MarketContextAnalyzer` |
| P1-6 | yfinance `1w` 无效 | `YFinanceStrategy.normalize_interval` → `1wk` |
| P1-7 | `hk.00700` 无法识别 | SymbolResolver `hk.` 前缀 → `0700.HK` |
| P1-8 | AkShare 小时线静默回退日线 | 不支持频率抛错触发 BaoStock 回退 |
| P1-9 | yfinance 无限流重试 | 指数退避 + `max_retries` |
| P1-10 | 报告 MTF 小时线 fetcher 路径错误 | `analyzer.orchestrator.data_fetcher` |
| P2-1 | 批量扫描 patience 状态串 symbol | `_reset_patience_for_symbol` |
| P2-2 | Facade 基准指数逻辑重复 | 委派 `SymbolResolver.resolve_benchmark_index` |
| P2-3 | yfinance 无限流本地缓存 | `.cache/yfinance/` 6h/7d TTL |
| P2-4 | Orchestrator 合成 E2E | `test_orchestrator_run_analysis_synthetic` |

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_phase13_fixes \
  tests.test_phase9_theory \
  tests.test_phase10_integration \
  tests.test_phase11_integration \
  tests.test_phase12_golden \
  tests.test_phase2_theory -q
# 38 tests OK
```
