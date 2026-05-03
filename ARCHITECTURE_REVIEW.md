# 架构评审（Architectural Review）

> 评审日期：2026-05-03

## 总结

当前项目在「模块拆分」上已经明显优于早期单体实现（`pattern_detector` 已委派给多个 detector 子模块），并且测试覆盖基础行为较完整（`59 passed`）。但从架构演进角度，仍存在一些会在规模化后放大的问题：**边界不清、缓存与资源生命周期耦合、错误模型混合、扩展点约束不足**。

## 主要问题与优化建议

### 1) 应用层对象承担过多职责（Analyzer 仍偏 God Object）

`WyckoffAnalyzer` 同时负责：
- 生命周期（`__enter__/__exit__/close`）
- 数据装载（`fetch_data`）
- 策略编排（phase/resonance/RS）
- 缓存管理（`_analysis_cache` 与 `_index_analyzer_cache`）
- 部分交易建议映射逻辑

这会导致：
- 变更耦合：数据源、策略、报告任一变化都可能触发核心类修改。
- 单测粒度受限：需要构造完整 analyzer 才能验证细粒度规则。

建议：
- 引入 `AnalysisOrchestrator`（应用服务层）负责流程编排。
- `WyckoffAnalyzer` 退化为 facade，仅做参数校验 + 结果聚合。
- 交易建议映射下沉到 `RecommendationEngine`（策略可插拔）。

### 2) 数据访问层存在跨市场分支膨胀风险

`WyckoffDataFetcher` 通过 `_is_a_stock` + `_fetch_a_stock_data/_fetch_global_stock_data` 分支处理市场，当前尚可维护，但继续引入港股/加密/期货等源时会快速膨胀。

建议：
- 使用 Strategy + Factory：`DataSourceStrategy`（BaoStock/YFinance/...）
- 统一 contract：`fetch(symbol, period) -> OHLCVFrame`
- 将 symbol 解析规则独立为 `SymbolResolver`，避免 fetcher 同时负责 IO 和语义解析。

### 3) 缓存策略与对象生命周期耦合，缺少统一缓存域

当前存在：
- `WyckoffAnalyzer._analysis_cache`（内存 LRU）
- `_index_analyzer_cache`（对象级缓存）
- `stock_cache.json`（symbol 名称映射文件缓存）

问题：
- 缓存散落在不同层，失效策略不一致。
- `fetch_data()` 中直接 `invalidate()`，可能导致调用链二次计算放大。

建议：
- 建立 `CacheService` 统一入口，支持命名空间：`analysis:*`, `symbol:*`。
- 明确失效策略：按数据源更新时间 + symbol + period 版本键。
- 将文件缓存迁移为可注入仓储（便于测试与并发控制）。

### 4) 领域语义与输出语义混杂（中英文枚举并存）

代码中既有 `Accumulation/Markup` 等英文 phase 字符串，也有中文解释文本直接拼接在逻辑中。长期看会导致：
- i18n 与业务规则耦合。
- 上层 API/MCP 调用方难以稳定依赖文本。

建议：
- 领域层只返回稳定枚举（如 `Phase.ACCUMULATION`）。
- 展示层（report generator / mcp）做本地化映射。
- 所有外部接口返回 `code + message`，message 可本地化，code 保持稳定。

### 5) 异常模型分层尚不完整

虽然定义了 `WyckoffError` 体系，但在 MCP 层仍用 `except Exception` 兜底并返回 `UnknownError`，不利于可观测性与错误分流。

建议：
- 约定错误码分层：`DATA_*`, `PATTERN_*`, `SYSTEM_*`。
- MCP 输出增加 `error_code`, `retriable`, `trace_id` 字段。
- 仅在最外层捕获 `Exception`，并写结构化日志，避免吞掉上下文。

### 6) 形态检测扩展点尚未完成（LPS/LPSY TODO）

`pattern_detector` 已拆分，但 `detect_lps/detect_lpsy` 仍是占位实现，意味着 phase 识别链路在部分场景下降级。

建议：
- 先定义 `DetectorProtocol` 与统一返回 contract（`detected/confidence/evidence`）。
- 将 LPS/LPSY 下沉到 `detectors/strength_weakness_detector.py` 或新 detector。
- 增加回归测试覆盖“检测缺失时的 phase 判定偏差”。

### 7) 接口契约建议显式化（Pydantic/TypedDict）

目前大量 `Dict` 返回，键结构依靠约定，跨模块演进容易出现 silent break。

建议：
- 关键对象（pattern result、phase result、recommendation）使用 `TypedDict` 或 Pydantic model。
- MCP 层可直接复用 schema，减少序列化偏差。

## 优先级建议（可执行路线）

1. **P0（1-2 周）**：统一结果 schema + 错误码模型（低风险，高收益）
2. **P1（2-4 周）**：数据源 Strategy 化 + SymbolResolver 独立
3. **P1（并行）**：完成 LPS/LPSY 实现与回归测试
4. **P2（4-6 周）**：Analyzer 编排层重构，分离 RecommendationEngine
5. **P2**：统一缓存服务与缓存失效策略

## 预期收益

- 降低核心类修改频率，减小回归面。
- 增强多市场扩展能力。
- 改善 API 稳定性与可观测性。
- 为后续实盘/回测一体化留出清晰边界。
