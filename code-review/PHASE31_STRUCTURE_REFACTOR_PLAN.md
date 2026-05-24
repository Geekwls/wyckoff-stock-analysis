# Phase 31 Structure Refactor Plan

## 背景

本阶段目标是精细化重构 Wyckoff 核心事件检测和风控链路，重点覆盖：

- Spring 5 重过滤
- AR 4 层反弹
- LPS ATR 动态容差
- 交易区间失效风控
- 双计算轨算法 100% 对齐

核心原则是先统一事件口径，再重构检测算法，最后用黄金样本和一致性测试锁死主计算轨、报告轨、评分轨、交易计划轨的输出。

## 总目标

1. Spring 不再由单一跌破/收回条件触发，而是经过位置、跌破深度、成交量、收回质量、后续确认 5 层过滤。
2. AR 不再只看低点后的普通反弹，而是通过幅度、速度、量价质量、结构意义 4 层判断是否足以锚定交易区间。
3. LPS 不再使用固定百分比容差，而是基于 ATR 动态适配不同波动率股票。
4. 交易区间失效后，目标位、评分、交易计划和多头信号置信度必须同步调整。
5. 所有下游输出只读统一事件事实源，避免主轨和报告/评分/批量轨重复计算导致分歧。
6. 旧 TR 已失效但新 TR 尚未形成时，进入 `transition_period` 过渡状态，暂停所有依赖旧 TR 的事件判定和目标测算。

## 核心改造文件

- `src/wyckoff/core/pattern_detector.py`
- `src/wyckoff/core/detectors/reversal_detector.py`
- `src/wyckoff/core/detectors/strength_weakness_detector.py`
- `src/wyckoff/core/detectors/trading_range_detector.py`
- `src/wyckoff/core/event_arbitrator.py`
- `src/wyckoff/core/signal_extractor.py`
- `src/wyckoff/core/trading_plan_generator.py`
- `src/wyckoff/core/thresholds.py`
- `src/wyckoff/schemas.py`

## 阶段 1：基准冻结与黄金样本

### 任务

1. 新增一组离线黄金样本，覆盖：
   - 真 Spring
   - 假 Spring
   - Spring 跌破后未收回
   - SC 后有效 AR
   - SC 后弱反弹，不应判定为 AR
   - JOC 后有效 LPS
   - 高 ATR 股票 LPS
   - 低 ATR 股票 LPS
   - TR 向下失效
   - TR 向上突破后旧区间失效

2. 新增或扩展测试文件：
   - `tests/iterations/test_phase31_structure_refactor.py`
   - `tests/iterations/test_phase12_golden.py`
   - `tests/core/test_lps_lpsy.py`
   - `tests/core/test_pattern_detector.py`

3. 先记录当前输出行为，不立即修改算法。

### 验收标准

- 黄金样本能稳定构造 OHLCV、ATR、Volume_MA20 等必要字段。
- 每个样本都有明确预期：应检测、应降级、应失效或应拒绝。
- 当前行为快照可用于后续回归比较。

## 阶段 2：统一事件模型

### 任务

在 `src/wyckoff/schemas.py` 中扩展事件模型，保持向后兼容。

### SpringSignalModel 新增字段

- `filter_scores`
- `filter_passed`
- `classification`: `confirmed/candidate/failed/rejected`
- `failure_reason`
- `penetration_pct`
- `recovery_quality`

### LpsSignalModel 新增字段

- `atr`
- `atr_pct`
- `tolerance_pct`
- `matched_anchor`
- `distance_to_anchor_pct`
- `qualification`

### TradingRangeModel 新增字段

- `invalidation_level`
- `invalidation_reason`
- `invalidation_severity`: `none/warning/invalidated/distribution_risk/markup_breakout`
- `invalidated_at`
- `transition_period`: 旧 TR 已失效但新 TR 尚未形成
- `transition_reason`

### 兼容要求

- 保留现有字段，例如 `invalidated_tr`、`is_broken`、`latest_spring`。
- 新字段只增强事件表达，不破坏现有调用。
- `SignalExtractor.get_event_dict()` 能稳定透出新字段。
- `classification` 记录检测时的判定结果，`lifecycle_status` 跟踪检测后的生命周期变化，两者不得混用。

### 验收标准

- Pydantic 模型验证通过。
- 旧测试不因字段变化失败。
- 下游报告、评分、交易计划可以读取新字段。

## 阶段 3：Spring 5 重过滤

### 落点

优先改造：

- `src/wyckoff/core/detectors/reversal_detector.py`

保持委托入口：

- `src/wyckoff/core/pattern_detector.py`

### 过滤链

1. 位置过滤
   - 必须发生在 TR 下沿附近，或短暂跌破 TR 下沿。
   - 无 TR 时只允许候选 Spring，不直接确认。

2. 跌破深度过滤
   - 使用 ATR 与百分比阈值共同约束。
   - 跌破过深时不判 Spring，而应进入 TR 失效风险判断。

3. 成交量过滤
   - 支持缩量假破，表示供应枯竭。
   - 支持放量下探后快速收回，表示恐慌释放。
   - A 股涨跌停场景沿用市场特例，不把涨停缩量误判为需求弱。

4. 收回质量过滤
   - N 日内收回支撑位。
   - N 使用 `spring_max_recovery_days(atr_pct)`。
   - 收盘位置、实体质量、下影线质量纳入评分。

5. 后续确认过滤
   - ST、JOC、LPS 出现后升级为 `confirmed`。
   - 未确认时保持 `candidate`。

### 输出分类

- `confirmed_spring`
- `candidate_spring`
- `failed_spring`
- `rejected_spring`

### 验收标准

- 真 Spring 样本能够检测。
- 假破但未收回样本不应确认为 Spring。
- 跌破过深样本触发 TR 风控，而不是 Spring。
- Spring without JOC/LPS 不直接给积极交易计划。

## 阶段 4：AR 4 层反弹

### 落点

- `src/wyckoff/core/detectors/reversal_detector.py`
- `src/wyckoff/core/pattern_detector.py`

### 4 层判断

1. 幅度
   - 从 SC 或有效局部低点反弹至少达到 `max(1.5 * ATR, min_rebound_pct)`。

2. 速度
   - 反弹必须发生在合理窗口内。
   - 太慢的修复只算普通反弹，不作为 AR。

3. 量价质量
   - 反弹日需求改善，或下跌供应明显减弱。

4. 结构意义
   - AR 高点应能作为 TR 上沿候选。
   - 无结构锚定意义时，降级为 weak rebound。

### 输出字段

- `rebound_pct`
- `rebound_atr_multiple`
- `reaction_days`
- `volume_quality`
- `structural_role`
- `quality_score`

### 验收标准

- 有效 SC 后 AR 能锁定 TR high。
- 小反弹不再被当成 AR。
- AR 质量低时 Phase A 不应被过度确认。

## 阶段 5：LPS ATR 动态容差

### 落点

- `src/wyckoff/core/detectors/strength_weakness_detector.py`
- `src/wyckoff/core/thresholds.py`

### 阈值单一事实源

在 `thresholds.py` 中新增：

```python
def lps_atr_tolerance_pct(atr_pct: float) -> float:
    return min(8.0, max(2.0, atr_pct * 1.5))
```

### LPS 锚点优先级

1. JOC creek/test level
2. SOS breakout level
3. Spring support level
4. TR low / range midpoint
5. MA20 仅作为降级观察，不作为正式 LPS

### 正式 LPS 条件

- 已有 JOC/SOS/Spring 上下文。
- 回踩落在 ATR 动态容差内。
- 成交量低于合理阈值。
- 未有效跌破 Spring/TR 关键位。
- 后续出现向上响应时提高质量等级。

### 验收标准

- 高 ATR 样本不会因固定 3% 容差误杀。
- 低 ATR 样本不会因过宽容差误判。
- 无 JOC/SOS/Spring 前置时，只能是 observation/pullback，不能 formal LPS。

## 阶段 6：交易区间失效风控

### 落点

- `src/wyckoff/core/detectors/trading_range_detector.py`
- `src/wyckoff/core/orchestrator.py`
- `src/wyckoff/core/trading_plan_generator.py`
- `src/wyckoff/core/signal_extractor.py`

### 风控分级

- `none`: 区间有效。
- `warning`: 轻微跌破/突破，但未确认。
- `invalidated`: 有效破位且未快速收回。
- `distribution_risk`: 向下破位 + 放量 + 弱反抽/SOW。
- `markup_breakout`: 向上有效突破，旧 TR 切换到突破后逻辑。
- `transition_period`: 旧 TR 已失效，新 TR 尚未形成，进入过渡观察期。

### 过渡期处理

当 `transition_period=True` 时，系统必须暂停所有依赖旧 TR 的逻辑：

- Spring 位置过滤不得使用旧 TR low 作为有效支撑。
- AR 不得使用旧 TR high 作为结构锚点。
- LPS 不得使用旧 TR low / midpoint 作为正式锚点。
- P&F 因果目标测算暂停。
- 基于旧 TR 的 JOC/FTI 置信度需要降级或拒绝。

过渡期内允许保留的检测：

- VSA 检测。
- 趋势判断。
- 成交量背景分析。
- 新 TR 形成条件监控。

### 级联规则

- TR invalidated 后，旧 P&F 因果目标暂停。
- 多头 Spring/JOC/LPS 置信度折减或屏蔽。
- 交易计划改为“结构失效，等待新区间”。
- `risk_specific_advice` 必须显示失效原因和动作建议。
- 处于 `transition_period` 时，交易计划统一降级为“过渡期观察，等待新区间确认”。

### 验收标准

- `invalidated_tr` 时 `_calculate_targets()` 继续暂停旧目标。
- 信号质量评分被压低。
- 交易计划不再给积极入场区。
- 报告和 JSON 中能看到失效级别与原因。

## 阶段 7：双计算轨 100% 对齐

### 原则

`phase_coordinator.collect_all_events()` 是事件事实源。报告、评分、交易计划、批量扫描只读 `events_detected`。

下游禁止重复调用独立检测路径生成第二套结果，例如：

- `detect_spring()`
- `detect_lps()`
- `detect_sos()`
- `detect_trading_range()`

允许的例外：当 `events_detected` 缺失时可 fallback，但必须记录 fallback 原因。

双计算轨对齐不是最后阶段才执行的收尾任务，而是贯穿阶段 1 到阶段 6 的持续约束。每完成一个核心检测模块重构，都必须同步补充一致性断言，确保主轨、报告轨、评分轨、交易计划轨没有重新分叉。

### 一致性测试

新增测试覆盖：

1. 同一份 DataFrame。
2. 跑 `identify_phase()`。
3. 跑 `SignalExtractor.build_scoring_payload()`。
4. 跑 `TradingPlanGenerator`。
5. 对比 Spring/LPS/TR/phase/score/entry/stop 关键字段。

### 对齐字段

- `detected`
- `classification`
- `latest.date`
- `price/support/resistance`
- `confidence`
- `lifecycle_status`
- `invalidated_tr`
- `invalidation_severity`
- `direction`
- `entry_zone`
- `stop_loss`

### 验收标准

- 黄金样本中，主轨和评分/报告轨关键 JSON 完全一致。
- 浮点字段只允许极小误差。
- 不再出现“报告有 Spring，评分轨无 Spring”或相反情况。
- 每个阶段性提交都包含对应的双轨一致性测试或明确说明该阶段不影响输出轨。

## 建议提交拆分

1. `phase31-models-golden`
   - 模型字段扩展
   - 黄金样本
   - 当前行为快照

2. `phase31-spring-filters`
   - Spring 5 重过滤
   - Spring 分类输出
   - Spring 回归测试

3. `phase31-ar-quality`
   - AR 4 层反弹
   - TR high 锚定规则
   - Phase A 相关回归测试

4. `phase31-lps-atr-tolerance`
   - LPS ATR 动态容差
   - 锚点优先级
   - 高/低波动样本测试

5. `phase31-range-risk-dual-track`
   - TR 失效风控
   - transition_period 过渡期处理
   - 交易计划级联
   - 双轨一致性测试

## 推荐验收命令

```powershell
pytest tests/core/test_pattern_detector.py tests/core/test_lps_lpsy.py tests/core/test_scoring.py tests/iterations/test_phase12_golden.py
pytest tests/iterations/test_phase31_structure_refactor.py
pytest
```

## 完成定义

本阶段完成时应满足：

1. Spring、AR、LPS、TR 失效都有明确分类、证据字段和测试样本。
2. 所有旧接口保持兼容。
3. 黄金样本稳定通过。
4. 报告、评分、交易计划、批量扫描读取同一事件事实源。
5. 双计算轨关键输出 100% 对齐。
