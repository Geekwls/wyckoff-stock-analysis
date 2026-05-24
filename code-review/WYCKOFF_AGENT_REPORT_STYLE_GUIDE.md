# Wyckoff Agent Report Style Guide

## 目标

智能体输出的威科夫分析报告必须具备：

- 有背景：先说明行业、市场、标的近期环境。
- 有体系：按固定章节展开，不只给结论。
- 有证据：每个判断尽量对应系统 JSON 字段或数据来源。
- 有框架：给关键价位、触发条件、失效条件和操作建议。
- 有克制：低质量信号时必须明确等待，不制造买点。

报告风格参考：专业投研笔记 + 威科夫结构复盘 + 风控执行清单。

## 默认报告结构

### 一、分析背景：行情数据与宏观环境

说明：

- 分析日期。
- 当前价格。
- 市场环境。
- 行业或主题背景。
- 标的近期走势概况。
- 数据来源和分析周期。

字段来源：

```text
summary.current_price
summary.timestamp
market_environment.environment
market_environment.details
multi_timeframe.weekly_trend
multi_timeframe.monthly_trend
```

输出要求：

- 不直接进入买卖建议。
- 先让用户知道“这只票现在处在什么大环境里”。

### 二、日线级别量价解读：当前结构在哪里

说明：

- 当前威科夫阶段。
- TR 区间上下沿。
- 当前价格在 TR 中的位置。
- Spring / Upthrust / SOS / SOW / JOC / LPS 状态。
- VSA 量价信号。
- 是否处于 `transition_period`。

字段来源：

```text
summary.phase
trading_range.high
trading_range.low
trading_range.position
trading_range.transition_period
trading_range.invalidation_severity
patterns.spring
patterns.upthrust
patterns.sos
patterns.sow
patterns.joc
patterns.lps
advanced_signals.vsa
```

推荐写法：

```text
当前日线更像是“吸筹/再吸筹观察”，但还不是标准买点。
原因是：虽然出现了 Spring 或突破迹象，但 JOC/LPS 尚未确认。
```

如果处于过渡期：

```text
当前旧 TR 已失效，新 TR 尚未形成，因此所有基于旧 TR 的 P&F 目标和 LPS 判定都应暂停。
```

### 三、周线级别判断：结构是否有更大级别支撑

说明：

- 周线趋势。
- 月线趋势。
- 多周期是否共振。
- 日线信号是否被周线支持或压制。

字段来源：

```text
multi_timeframe.resonance_level
multi_timeframe.weekly_trend
multi_timeframe.monthly_trend
multi_timeframe.trading_implication
multi_timeframe.confidence_boost
```

输出要求：

- 如果周线偏空，要明确“日线信号需要打折”。
- 如果周线偏多，但日线无 LPS，也不能直接说买点成立。

### 四、估值与基本面背景：只做辅助，不替代结构

说明：

当前项目主要是威科夫量价系统，不直接内置完整估值模型。因此智能体可以输出“估值/基本面背景”章节，但必须区分：

- 系统已有数据。
- 用户提供的数据。
- 外部检索数据。
- 无数据时的缺口说明。

允许写法：

```text
当前系统未接入完整估值和财务因子，本节只作为背景观察，不参与威科夫信号确认。
```

如果后续接入财务数据，可补充：

- PE/PB 分位。
- 行业景气度。
- 盈利趋势。
- 机构持仓。
- 主题催化。

禁止：

- 在无数据时编造估值水平。
- 用估值结论替代交易结构确认。

### 五、关键证伪条件与观察框架

这是报告最重要的执行章节。

必须包含：

- 关键支撑。
- 关键压力。
- 转强条件。
- 失效条件。
- 观察动作。

字段来源：

```text
trading_range.low
trading_range.high
breakout_analysis.breakout_price
breakout_analysis.joc_test_status
trading_plan.entry_zone
trading_plan.stop_loss
cause_effect.targets
```

推荐结构：

```text
关键价位一：xx.xx
如果站稳：说明需求承接增强。
如果跌破：说明当前结构失效，需要重新评估。

关键价位二：xx.xx
如果放量突破：可能形成 JOC。
如果突破后缩量回踩不破：才具备 LPS 观察价值。
```

### 六、总结与操作建议

必须明确：

- 当前是否是买点。
- 是否适合追入。
- 是否需要等待确认。
- 不同风险偏好的动作。
- 仓位建议。

字段来源：

```text
signal_quality.score
signal_quality.confidence
trading_plan.direction
trading_plan.position_sizing
risk_advice
strategy_decision_audit
```

推荐结论模板：

```text
当前结论：观察，不追。

理由：
1. 当前处于 Phase B / transition_period / 无 LPS。
2. 虽有某些积极量价迹象，但确认链条不完整。
3. 需要等待 JOC + LPS 或重新形成有效 TR。
```

## 报告详细模板

```markdown
# {标的名称}（{symbol}）威科夫结构分析

数据截至：{date}
当前价格：{current_price}
核心结论：{direction} / {position_sizing}

## 一、分析背景：行情数据与宏观环境

{market_background}

## 二、日线级别量价解读：当前结构在哪里

当前系统识别阶段：{phase}

交易区间：
- 上沿：{tr_high}
- 下沿：{tr_low}
- 当前位置：{tr_position}
- 区间状态：{tr_status}

关键事件：
- Spring：{spring_status}
- JOC/SOS：{breakout_status}
- LPS：{lps_status}
- SOW/LPSY：{weakness_status}

量价特征：
{vsa_summary}

## 三、周线级别判断：结构是否有更大级别支撑

{multi_timeframe_summary}

## 四、估值与基本面背景：只做辅助，不替代结构

{fundamental_context}

## 五、关键证伪条件与观察框架

关键价位一：{support_level}
{support_plan}

关键价位二：{resistance_level}
{resistance_plan}

转强条件：
{bullish_conditions}

失效条件：
{invalid_conditions}

## 六、总结与操作建议

当前结论：{final_conclusion}

保守型：{conservative_action}
稳健型：{moderate_action}
激进型：{aggressive_action}

风险提示：以上分析仅供研究，不构成投资建议。
```

## 智能体输出规则

### 必须做到

1. 每篇报告至少包含六个章节。
2. 每个章节都要围绕“结构、证据、条件”展开。
3. 必须给出关键价位。
4. 必须说明“什么情况转强，什么情况失效”。
5. 低信号质量时必须把“等待条件”写清楚。
6. 如果系统字段冲突，要说明冲突，而不是强行给方向。

### 不允许

1. 只输出一句“观望”。
2. 只罗列 JSON 字段，不解释含义。
3. 无数据时写估值和基本面结论。
4. 无 JOC/LPS 时把 Spring 直接当买点。
5. `transition_period=true` 时输出积极买入建议。
6. 忽略多周期压制。

## 质量分层表达

### signal_quality.score < 40

表达：

```text
信号质量低，当前主要任务是观察，不是交易。
```

禁止：

```text
可以轻仓试错
```

除非交易计划明确允许。

### 40 <= score < 60

表达：

```text
结构有观察价值，但确认链条不足，需要等待触发条件。
```

### 60 <= score < 75

表达：

```text
结构开始具备交易观察价值，但仍需结合风险位。
```

### score >= 75

表达：

```text
信号质量较高，可以进入交易计划评估，但仍需仓位控制。
```

## 特殊场景写法

### transition_period

```text
当前处于旧 TR 失效、新 TR 尚未形成的过渡期。此时不应继续使用旧区间做 P&F 目标测算，也不应把旧 TR 下沿/上沿作为新的 LPS 锚点。操作上以等待新区间形成为主。
```

### 突破但无回测

```text
突破已经发生，但还没有 LPS 回测确认。威科夫上这属于“突破观察”，不是标准低风险买点。
```

### Spring 但无 JOC

```text
Spring 只能说明下方出现过震仓或供应测试，不能单独构成完整买点。后续需要 JOC 突破小溪和 LPS 缩量回测确认。
```

### 周线压制

```text
日线结构有改善，但周线仍偏弱，因此日线信号需要打折。除非后续出现放量突破和回踩确认，否则不宜提前重仓。
```

### ETF 分析

```text
ETF 没有个股基本面利润表逻辑，重点看指数环境、成分方向、量价结构和多周期共振。估值章节应改为“指数与主题背景”。
```

## Agent 集成建议

在 `WYCKOFF_AGENT_EXECUTION_PLAN.md` 的 `ResponseComposer` 阶段，必须按本文件实现：

- `compose_symbol_report(analysis: dict) -> str`
- `compose_position_diagnosis(diagnosis: dict) -> str`
- `compose_comparison_report(result: dict) -> str`
- `compose_signal_explanation(result: dict) -> str`

并新增测试：

```text
tests/agent/test_report_style.py
```

测试要求：

- 输出包含六个章节标题。
- `transition_period=true` 时包含“过渡期观察”。
- 无 LPS 时不得出现“标准买点成立”。
- ETF 报告使用“指数与主题背景”，不强行写个股估值。
- 输出包含“不构成投资建议”。
