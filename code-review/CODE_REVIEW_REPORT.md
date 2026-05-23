# src 代码逻辑审查报告 - 新威科夫操盘法口径

审查日期：2026-05-23  
审查范围：`src/wyckoff` 下核心检测、阶段协调、事件模型、交易建议、报告输出、数据入口与批量筛选链路。  
审查基准：项目内 `SKILL.md`、`README.md`、`references/meng-expert-system.md`、`references/optimized-strategy.md`、`references/wyckoff-theory-full.md` 中的新威科夫与孟洪涛规则。

## 总体结论

当前代码的问题不只是某个指标阈值偏差，而是“检测器原始 dict、Pydantic 模型、报告 dict、批量扫描 dict”多套事件契约并存。许多检测器能识别出信号，但进入 `EventsModel`、仲裁、评分、交易计划或报告渲染后，信号细节会丢失或被错误读取。

建议优先修复事件契约和数值归一化，再修具体交易规则：

1. 统一事件标准结构：所有核心事件输出 `detected/signals/latest` 或统一顶层字段，不再混用。
2. 建立公共读取工具：统一读取 dict、Pydantic 模型、`latest`、`signals[-1]`、`DerivedValueModel.value`。
3. 统一 Spring/JOC/SOS/SOW/LPS 的孟氏口径，避免主报告、轻量 JSON、三大定律、批量筛选各自调用不同检测路径。
4. 用针对性单元测试覆盖新威科夫关键序列：SC-AR-ST-Spring-SOS-LPS-JOC、BC-AR-ST-UTAD-SOW-LPSY-FTI。

## P0 - 阻断级问题

### 1. SOS/SOW 事件模型化后丢失细节，仲裁与评分基本失效

位置：

- `src/wyckoff/core/detectors/strength_weakness_detector.py:266`
- `src/wyckoff/core/detectors/strength_weakness_detector.py:476`
- `src/wyckoff/schemas.py:157`
- `src/wyckoff/schemas.py:176`
- `src/wyckoff/core/phase_coordinator.py:163`
- `src/wyckoff/core/event_arbitrator.py:189`

问题：

`detect_sos()` 和 `detect_sow()` 返回顶层 `date/price/volume_ratio/price_change` 等字段，但 `SosModel` 和 `SowModel` 只接收 `signals/latest`。`PhaseCoordinator._safe_model()` 会过滤掉模型不存在的字段，导致 `EventsModel.sos` 和 `EventsModel.sow` 只剩 `detected=True`，但没有日期、价格、量比、突破位。`EventArbitrator` 又只读取 `signals`，因此无法仲裁 SOS/SOW 冲突。

影响：

- SOS/SOW 已检测到，但仲裁器可能返回“无有效信号”。
- 量能确认无法参与评分。
- `sos_sow` 二选一模型无法保留关键证据。
- 批量筛选和报告结论会低估或错判强弱信号。

建议：

- 将 SOS/SOW 检测器输出改为 `signals=[SosSignal]`，`latest=...`。
- `EventArbitrator` 同时兼容 `signals` 和 `latest`。
- `SosModel/SowModel` 可保留 `signal_rank/signal_type/phase_context/tr_low` 等语义字段，避免二次丢失。

### 2. 孟氏 Spring 置信度收盘位置量纲错误

位置：

- `src/wyckoff/core/detectors/meng_reversal_detector.py:75`
- `src/wyckoff/core/detectors/meng_reversal_detector.py:164`
- `src/wyckoff/core/detectors/meng_reversal_detector.py:352`

问题：

Spring 收盘位置先按 `0~1` 计算并传入 `_calculate_spring_confidence()`，但评分函数按 `80/70/60` 比较。结果符合“收盘在日内高位 70%/80%”的 Spring 无法获得收盘位置分。

影响：

- Spring 5 重过滤可以通过，但置信度被系统性压低。
- Phase C、交易建议、仓位建议可能被错误降级。
- Type 3 高质量 Spring 可能被误判为中低质量。

建议：

- 将评分阈值统一为 `0.8/0.7/0.6`。
- 或在调用评分函数前统一转换成百分制，但不得在存储字段和评分字段之间重复转换。

### 3. 孟氏 JOC 模型化后丢失 `latest/signals` 细节

位置：

- `src/wyckoff/core/detectors/meng_trend_detector.py:211`
- `src/wyckoff/schemas.py:221`
- `src/wyckoff/core/phase_coordinator.py:203`

问题：

`detect_joc_menhongtao()` 返回 `signals/latest` 嵌套结构，但 `JocModel` 期待顶层 `date/creek_level/breakout_pct/test_detected/confidence`。进入 `_safe_model()` 后，JOC 会变成 `detected=True` 但 creek、回测质量、置信度大多为空或默认值。

影响：

- Phase D 识别只知道“有 JOC”，不知道 JOC 质量。
- 交易计划无法可靠锚定 Creek。
- 多周期共振和报告展示可能取不到小溪位。

建议：

- 将 `JocModel` 改为支持 `signals/latest`，或在 `_safe_model()` 前扁平化 `latest`。
- FTI、VSA、LPS 等事件也应同步检查是否存在同类契约错位。

## P1 - 高优先级逻辑问题

### 4. LPS 锚定 TR 下沿，违背“JOC 后缩量回测 Creek/突破位”的语义

位置：

- `src/wyckoff/core/detectors/strength_weakness_detector.py:616`
- `src/wyckoff/core/detectors/strength_weakness_detector.py:678`
- `src/wyckoff/core/detectors/strength_weakness_detector.py:731`

问题：

当前 LPS 以 `trading_range['low']` 为支撑锚点，要求低点贴近 TR 下沿。但新威科夫语义中，LPS 更常见于 SOS/JOC 后对 Creek、TR 上沿或突破位的缩量回测。

影响：

- 健康的高位回踩会被漏检。
- 深回撤到区间底部反而可能被标成 LPS。
- 入场区和止损锚点会偏离真实结构。

建议：

- `has_sos/is_after_sos` 成立时，将 LPS 支撑锚点切到 `JOC.creek_level`、`SOS.breakthrough_level` 或 TR high。
- 保留 “Spring 后 LPS 高于 Spring 低点” 作为补充约束，而不是唯一位置逻辑。

### 5. 报告和 orchestrator 调用 LPS 时未传入 SOS/JOC 上下文

位置：

- `src/wyckoff/core/pattern_detector.py:364`
- `src/wyckoff/core/report_generator.py:67`
- `src/wyckoff/core/orchestrator.py:225`

问题：

`detect_lps()` 支持 `sos_result` 和 `trading_range` 参数，但报告和 orchestrator 直接调用 `detect_lps()`，丢失 SOS/JOC 后回测的上下文。

影响：

- 报告层可能看不到正式 LPS，只看到普通支撑测试。
- `Phase C -> D` 的转换证据不完整。

建议：

- 所有入口统一调用 `detect_lps(sos_result=sos, spring_res=spring, trading_range=tr)`。
- 最好由 `PhaseCoordinator` 产出的 `EventsModel` 作为唯一事实来源，报告层不要重复独立检测。

### 6. SOS/SOW 量能阈值误用 `strong=2.5x`

位置：

- `src/wyckoff/config/settings.py:51`
- `src/wyckoff/config/settings.py:52`
- `src/wyckoff/core/detectors/strength_weakness_detector.py:183`
- `src/wyckoff/core/detectors/strength_weakness_detector.py:401`

问题：

配置注释明确 `moderate=1.5` 用于 SOS/SOW/LPS，但 SOS/SOW 实际使用 `strong=2.5`。同时 rolling 均量包含当前放量柱，会进一步提高触发门槛。

影响：

- 大量符合 “>1.5x 20 日均量” 的有效 SOS/SOW 被漏检。
- Phase D/FTI/JOC 推进延后或缺失。

建议：

- SOS/SOW 使用 `VOLUME_CONFIRMATION['moderate']` 或专门配置项。
- 量比基准使用前一日均量，如 `Volume_MA20.shift(1)`。

### 7. Spring、JOC、报告、阶段识别使用多套检测源

位置：

- `src/wyckoff/core/phase_coordinator.py:89`
- `src/wyckoff/core/report_generator.py:62`
- `src/wyckoff/core/orchestrator.py:221`
- `src/wyckoff/facade.py:391`

问题：

阶段协调器使用 classic `detect_spring()`，报告和 orchestrator 使用 `detect_spring_menhongtao()`，轻量 phase JSON 又直接调用 classic reversal detector。

影响：

- Phase、报告、交易建议可能对同一标的给出不同 Spring 结论。
- 孟氏 5 重过滤无法成为全局统一口径。

建议：

- 统一以孟氏 Spring 作为主检测源。
- classic Spring 只作为兼容字段或弱证据，不应驱动主阶段。

### 8. 交易计划对 `EventsModel` 的兼容声明与实现不一致

位置：

- `src/wyckoff/core/recommendation_engine.py:529`
- `src/wyckoff/core/recommendation_engine.py:587`
- `src/wyckoff/core/recommendation_engine.py:599`
- `src/wyckoff/core/recommendation_engine.py:611`

问题：

`generate_trading_plan()` 会从 dict 中提取 `events_detected`，该值可能是 `EventsModel`。后续却直接对 `joc/spring/sos` 等对象调用 `.get()`。

影响：

- 某些入口会直接抛异常。
- 即使未抛异常，也可能取不到信号细节，导致方向、止损、入场区错误。

建议：

- 全部改用 `_get_attr()`。
- 对事件对象统一调用 `normalize_event(event)`。

### 9. orchestrator 目标位计算绕开 P&F 因果测算，且只给上行目标

位置：

- `src/wyckoff/core/orchestrator.py:233`
- `src/wyckoff/core/orchestrator.py:243`
- `src/wyckoff/core/trading_plan_generator.py:247`

问题：

orchestrator 用 `duration * ATR * 0.25` 从 TR high 往上推目标，未考虑派发/做空方向，也没有复用已有 P&F 因果目标。

影响：

- Distribution/Markdown 场景下交易目标偏多头。
- 三大定律中的因果测算与交易计划目标不一致。

建议：

- orchestrator 目标位统一调用 `calculate_cause_effect_from_pnf()`。
- 根据 phase 或主导信号决定目标方向。

### 10. 批量筛选 `strength/signal_count/entry_count` 会失真

位置：

- `src/wyckoff/services/screener_service.py:161`
- `src/wyckoff/core/recommendation_engine.py:507`
- `src/wyckoff/services/screener_service.py:446`

问题：

`_scan_single()` 把 `phase_res` dict 传给 `calculate_signal_strength()`，但后者只按对象属性读取事件。dict 输入下事件计数多数为 0。

影响：

- `signal_count` 和 `entry_count` 偏低。
- top picks 排序更依赖错误或不完整的 `weighted_score`。

建议：

- `calculate_signal_strength()` 兼容 dict：优先读取 `events_detected`。
- 或批量筛选直接基于 `EventsModel` 计数。

### 11. 评分引擎对 dict 输入取不到 phase

位置：

- `src/wyckoff/core/recommendation_engine.py:249`
- `src/wyckoff/core/recommendation_engine.py:403`
- `src/wyckoff/core/recommendation_engine.py:424`

问题：

`calculate_weighted_score()` 支持 `pattern_results` 为 dict，但后续多处用 `getattr(pattern_results, 'phase')`，dict 输入会得到 `Unknown`。

影响：

- 派发阶段 bearish 信号可能不计数。
- 冲突扣分、市场顺逆势加减分、缺失核心信号提示都会偏差。

建议：

- 使用 `_get_attr(pattern_results, 'phase')`。
- `events` 与 `phase_str` 在函数开头一次性规范化。

### 12. 多周期共振没有校验日线信号方向

位置：

- `src/wyckoff/core/multi_timeframe_coordinator.py:138`
- `src/wyckoff/core/multi_timeframe_coordinator.py:169`
- `src/wyckoff/core/multi_timeframe_coordinator.py:316`

问题：

周线方向有 `long/short`，日线分析也知道传入方向，但 `_check_weekly_daily_alignment()` 只看日线是否有信号和质量是否 medium/strong，不校验日线信号方向。

影响：

周线多头 + 日线空头信号，也可能被判定为周日对齐。

建议：

- daily analysis 输出 `direction`。
- alignment 规则必须同时满足 weekly direction 与 daily signal direction 一致。

### 13. 突破分析取全历史首次突破，不限定当前 TR

位置：

- `src/wyckoff/core/breakout_analyzer.py:76`
- `src/wyckoff/core/breakout_analyzer.py:136`

问题：

向上突破取 `self.data[self.data['Close'] > tr_high]` 的第一个点，向下突破同理。若当前 TR 位于后半段，早期历史穿越同一价格会被误当成本次突破。

影响：

- JOC/FTI 质量分析错位。
- 回测和 Upthrust 判断使用错误时间段。

建议：

- `trading_range` 应携带起止日期或 bar 范围。
- BreakoutAnalyzer 只在当前 TR 形成之后搜索突破。

### 14. 孟氏 JOC 回测确认条件过宽

位置：

- `src/wyckoff/core/detectors/meng_trend_detector.py:191`
- `src/wyckoff/core/detectors/meng_trend_detector.py:326`
- `src/wyckoff/core/detectors/meng_trend_detector.py:350`

问题：

回测命中只要求 `Low < creek * 1.02` 且缩量，没有下界，也不要求收盘重新站上 Creek。质量评分会检查收盘，但置信度只要 `has_test=True` 就直接加 25 分。

影响：

深跌破位也可能被当成 Test of JOC，从而提高 JOC 置信度。

建议：

- 回测命中应有价格带上下界，如 `creek * (1 - band) <= Low <= creek * (1 + band)`。
- 要求收盘重新站上或接近 Creek。
- `test_score` 低于阈值时不得给完整 test 加分。

### 15. P&F 当前 TR 计数会纳入全历史同价位列

位置：

- `src/wyckoff/core/point_and_figure.py:233`
- `src/wyckoff/core/point_and_figure.py:286`

问题：

传入 `known_tr_high/low` 后，会筛选所有与该价格带重叠的 P&F 列，没有限制当前 TR 的时间范围。

影响：

早期同价位震荡会被计入当前因果，目标幅度虚高。

建议：

- `calculate_horizontal_count()` 支持 TR 起止索引。
- 当前 TR 的 P&F 计数只使用 TR 内 columns。

### 16. P&F 吸筹期可能生成下跌目标

位置：

- `src/wyckoff/core/point_and_figure.py:475`
- `src/wyckoff/core/point_and_figure.py:325`
- `src/wyckoff/core/point_and_figure.py:358`

问题：

说明写明吸筹期触发向上目标，但非派发时仍依赖最后一列 P&F 方向。若最后一列向下，吸筹期会输出下跌目标。

影响：

因果定律与 Phase 语义冲突。

建议：

- Accumulation 默认只输出上行候选目标。
- 下行目标可作为失效情境单独标记，而不是主目标。

### 17. 序列验证没有归一化结构化价格值

位置：

- `src/wyckoff/core/detectors/reversal_detector.py:607`
- `src/wyckoff/schemas.py:101`
- `src/wyckoff/core/sequence_validator.py:237`
- `src/wyckoff/core/sequence_validator.py:425`

问题：

classic Spring 的 `breakdown_price` 可以是 `{"value": ...}` dict，schema 又允许 `Any`，但 `SequenceValidator` 直接做数值比较。

影响：

- 可能 TypeError。
- 或者跳过关键 Spring/SOW 冲突判断。

建议：

- 增加 `extract_number(value)`，兼容 float、dict.value、DerivedValueModel.value。
- 所有价格比较前统一归一化。

### 18. VSA 历史扫描使用最新均量评估所有历史 K 线

位置：

- `src/wyckoff/core/detectors/meng_vsa_detector.py:32`
- `src/wyckoff/core/detectors/meng_vsa_detector.py:44`

问题：

循环外取最后一天 `Volume_MA20`，循环内每根 K 线都用它计算量比。

影响：

近期量能环境变化时，历史 No Supply、No Demand、Stopping Volume 会系统性误判。

建议：

循环内使用 `Volume_MA20.iloc[i]` 或滚动均量序列。

### 19. VSA 报告读取结构错误

位置：

- `src/wyckoff/core/detectors/meng_vsa_detector.py:154`
- `src/wyckoff/core/reports/section_builders/signal_section.py:117`

问题：

Meng VSA 返回 `no_supply: {detected, signals, latest}`，报告区块直接读取 `sig['date']` 和 `sig['vol_ratio']`。

影响：

VSA detected 时报告可能漏字段或崩溃。

建议：

- 报告读取 `sig.get('latest')`。
- VSA 信号也纳入统一事件读取工具。

### 20. 数据质量 warning 不触发清洗

位置：

- `src/wyckoff/core/data_validator.py:298`
- `src/wyckoff/core/data_validator.py:310`
- `src/wyckoff/core/data_fetcher.py:130`

问题：

极端涨跌幅、零成交量过高、缺失值过高等 warning 不会让 `report.ok` 变为 false，`fetch_data()` 因此不会清洗。

影响：

复权断点、停牌异常、数据源断裂会直接进入威科夫检测，污染 Spring、SOS/SOW、RS、VSA。

建议：

- 实现 `strict` 语义。
- 对单股深度分析，极端涨跌幅和缺失过高应阻断或要求复权数据。

### 21. 股票代码解析会误判带 `-` 或 `/` 的美股

位置：

- `src/wyckoff/core/symbol_resolver.py:113`

问题：

只要代码含 `-` 或 `/` 就走 crypto 分支。`BRK-B` 这类美股会被误判为加密货币。

影响：

市场类型、数据源语义、波动率阈值、交易建议可能偏离。

建议：

- 先识别常见美股 ticker 规则，再识别 crypto pair。
- crypto 识别应要求 quote currency，如 USD、USDT、USDC、BTC、ETH。

### 22. 可选数据源变成顶层硬依赖

位置：

- `src/wyckoff/__init__.py:10`
- `src/wyckoff/core/datasource_factory.py:3`
- `src/wyckoff/core/strategies/baostock_strategy.py:1`

问题：

导入 `src.wyckoff` 会触发 `baostock`、`akshare`、`yfinance` 策略导入。缺少任一可选数据源时，纯逻辑测试或报告区块导入也失败。

影响：

- 无法运行与数据源无关的单元测试。
- 工程模块耦合过重。

建议：

- `DataSourceFactory` 懒加载策略类。
- 数据源依赖按 extras 分组，如 `a-share`、`us`、`full`。

## P2 - 中优先级问题

### 23. 报告层将 `EventsModel` 当 dict，异常被吞掉

位置：

- `src/wyckoff/core/report_generator.py:143`
- `src/wyckoff/core/report_generator.py:249`

问题：

`phase_coordinator.collect_all_events()` 返回 `EventsModel`，报告层却使用 `events.get('arbitration_result')`。异常只写 debug。

影响：

报告可能缺少仲裁和突破质量信息，且用户无感知。

建议：

使用统一读取工具或 `model_dump()`。

### 24. 信号质量评分读取顶层 `volume_ratio`，但模型化后量比在子信号内

位置：

- `src/wyckoff/core/recommendation_engine.py:276`
- `src/wyckoff/schemas.py:148`

问题：

评分读取 `info.volume_ratio`，而 `SosModel/SowModel` 的量比在 `signals/latest` 内。

影响：

强 SOS/SOW 可能得不到量能加分。

建议：

评分前提取最新子信号，再读取量比。

### 25. BreakoutAnalyzer 评分从 50 起步且只加分，低质量分支基本不可达

位置：

- `src/wyckoff/core/breakout_analyzer.py:343`
- `src/wyckoff/core/breakout_analyzer.py:324`
- `src/wyckoff/core/breakout_analyzer.py:446`

问题：

向上和向下突破评分都从 50 起步且只加分，但 Upthrust 判断中 `low_quality = score < 40`。

影响：

`very_weak` 和低质量突破分支难以触发，假突破识别偏弱。

建议：

评分从 0 累加，或重设阈值。

### 26. WIE 状态机熵阈值配置未使用

位置：

- `src/wyckoff/config/settings.py:139`
- `src/wyckoff/core/state_engine.py:189`

问题：

配置中有 `STATE_ENTROPY_DEGRADED_THRESHOLD`，实现中硬编码 `1.55`。

影响：

不同市场类型和用户配置无法调整高熵模糊带。

建议：

将配置注入 `StateEngine`。

### 27. 相对强弱引擎对部分日期交集使用前后填充

位置：

- `src/wyckoff/core/relative_strength.py:49`
- `src/wyckoff/core/relative_strength.py:58`
- `src/wyckoff/core/relative_strength.py:63`

问题：

有共同日期时，只给共同日期赋基准字段，但未裁剪资产数据，随后 `ffill().bfill()` 填充缺口。

影响：

非交易日或缺口日可能使用邻近大盘值，甚至出现未来填充，RS 与 hidden strength/weakness 失真。

建议：

将资产和指数都裁剪到 `common_idx` 后再计算。

### 28. RS 趋势允许 20 条数据进入，却用 MA50 判定

位置：

- `src/wyckoff/core/relative_strength_analyzer.py:22`
- `src/wyckoff/core/relative_strength_analyzer.py:31`

问题：

只要求 20 个共同日期，但计算 `rs_ma50`。20-49 条数据时 MA50 为 NaN，趋势可能落为 `flat`。

影响：

相对强弱趋势可能假性走平。

建议：

少于 50 条时使用 MA20 斜率或返回 `insufficient_data_for_ma50`。

### 29. 努力与结果总体判断漏掉高位/低位专用解释

位置：

- `src/wyckoff/core/laws/effort_result.py:91`
- `src/wyckoff/core/laws/effort_result.py:140`

问题：

代码会生成 `EFFORT_WITHOUT_RESULT_AT_HIGH/AT_LOW`，但总体评估只检查精确的 `EFFORT_WITHOUT_RESULT`。

影响：

高位放量滞涨、低位停止行为这类关键威科夫信号可能不会进入 overall warning。

建议：

总体判断使用前缀匹配或枚举集合。

### 30. 供求定律层绕开主事件上下文

位置：

- `src/wyckoff/core/laws/supply_demand.py:30`
- `src/wyckoff/core/laws/supply_demand.py:33`
- `src/wyckoff/core/laws/supply_demand.py:287`

问题：

供求定律直接调用 classic Spring、无 TR 的 SOW，与 `PhaseCoordinator` 的上下文检测结果不一致。

影响：

三大定律报告可能与主 Phase/交易计划结论冲突。

建议：

三大定律统一消费 `EventsModel`，不要重复独立检测。

### 31. 市场广度默认跳过，但报告仍保留广度修正语义

位置：

- `src/wyckoff/core/market_context_analyzer.py:98`
- `src/wyckoff/core/market_context_analyzer.py:207`

问题：

单股分析中 `_get_market_breadth()` 永远返回 `SKIPPED`，后续 `_refine_environment()` 仍期待 `alignment`。

影响：

报告看起来有广度维度，实际没有参与判断。

建议：

报告明确标注“广度未启用”，或仅在批量扫描模式下展示广度修正。

### 32. 测试覆盖偏结构，不足以保护新威科夫语义

位置：

- `tests/test_lps_lpsy.py:39`
- `tests/test_data_contracts.py:124`
- `tests/test_wyckoff_theory_upgrades.py:928`

问题：

部分测试只断言返回结构，不断言 LPS 必须发生在 SOS/JOC 后，也没有覆盖 Creek 回测。SOS 合约测试要求顶层字段，而 schema 又要求嵌套信号，说明测试也固化了旧契约。

建议：

新增以下测试：

- Spring 5 重过滤置信度：`close_position=0.85` 应获得收盘位置分。
- SOS/SOW 原始输出进入 `EventsModel` 后字段不丢失。
- JOC latest 能映射到 `JocModel`。
- LPS 必须在 SOS/JOC 后，且可发生在 Creek/TR high 回测区。
- Distribution 下目标位必须向下。
- `BRK-B` 应识别为美股，不是 crypto。

## 验证记录

已执行：

- `python3 -m compileall -q src`：通过。
- 使用合成数据探针复现：
  - Spring close position 量纲错误。
  - LPS 高位 Creek 回测漏检。
  - SOS 1.5x 放量被 `2.5x` 阈值漏检。
  - SOS/SOW 进入 Pydantic 模型后字段丢失。

后续验证（测试风格已收敛）：

- CI 与本地默认：`PYTHONPATH=src python -m pytest tests/ -q -m "not integration"`（342 passed，1 skipped）。
- Phase 语义回归：`PYTHONPATH=src python -m pytest tests/test_phase*.py -q`（186 tests）。
- 历史审查时曾用 `unittest discover`；现已统一 pytest 单入口，测试导入统一为 `from wyckoff...`。

## 推荐修复顺序

1. 事件契约标准化：SOS/SOW/JOC/FTI/VSA/LPS 全部统一 `signals/latest` 或统一顶层字段。
2. 公共读取工具：`get_event_attr()`、`get_latest_signal()`、`extract_number()`。
3. 修 Spring 量纲、SOS/SOW 量能阈值、LPS Creek 锚点、JOC 回测确认。
4. 统一事实来源：报告、orchestrator、三大定律、批量筛选都消费 `PhaseCoordinator.collect_all_events()` 的规范化结果。
5. 重标定 P&F、BreakoutAnalyzer、多周期共振方向校验。
6. 懒加载数据源依赖，恢复纯逻辑测试可运行性。
7. 增加覆盖新威科夫关键事件序列的单元测试。
