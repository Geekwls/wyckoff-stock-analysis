# 威科夫分析快速索引 (v2.6.0 专家版)

## 1. 核心相位识别 (Phase Identification)

### 吸筹相位 (Accumulation)
- **背景**: 长期下跌后的震荡区间。
- **关键序列**: PS (初步支撑) → SC (高潮) → AR (反弹) → ST (测试) → **Spring (震仓)** → JOC (突破) → LPS (回测)。
- **交易倾向**: 看多 (找入场点)。

### 派发相位 (Distribution)
- **背景**: 长期上涨后的震荡区间。
- **关键序列**: PSY (初步供应) → BC (高潮) → AR (回跌) → ST (测试) → **Upthrust (假突破)** → SOW (转弱) → LPSY (回抽)。
- **交易倾向**: 看空 (减仓或反手)。

---

## 2. v2.6.0 量化信号速查表 (Signal Dictionary)

| 缩写 | 全称 | 核心逻辑 | 信号分级 |
| :--- | :--- | :--- | :--- |
| **PS** | Preliminary Support | 主跌中首次放量止跌 | Phase A 证据 |
| **PSY** | Preliminary Supply | 主升中首次巨量滞涨 | Phase A 证据 |
| **SC/BC** | Climax | 趋势末端极度放量且 K 线变长 | Phase A 确认 |
| **Spring** | Spring (震仓) | 跌破支撑位后 3 日内收回 | Phase C 强力买入 |
| **UT** | Upthrust (上冲) | 突破压力位后 3 日内跌回 | Phase C 强力卖出 |
| **JOC** | Jump Across the Creek | 放量长阳突破区间上沿 | Phase D 趋势启动 |
| **FTI** | Fall Through the Ice | 放量长阴跌破区间下沿 | Phase D 趋势确认 |
| **SOT** | Stopping of Transient | 价格波动率在趋势末端收窄 | 预警信号 |

---

## 3. 专家级决策逻辑

### Spring 3 号模型 (生命周期)
1. **活跃 (Active)**: 刚刚收回，正在进行 LPS 测试。
2. **确认 (Confirmed)**: LPS 回测不破低点并再次放量上涨。
3. **失败 (Failed)**: 5 日内跌破 Spring 低点，判定为真跌破。

### 努力与结果 (EVR) 共振
- **日线/周线一致**: 权重评分 90+。
- **日线/周线背离**: 触发“逻辑证伪”，提示观望。

---

## 4. AI Agent 分析建议
- **优先调用**: `detect_wyckoff_phase` 以获取宏观位置。
- **深度挖掘**: 使用 `get_trading_levels` 确定精准的止损位。
- **矛盾处理**: 若出现 SOS 与 SOW 并存，调用 `analyze_signal_conflict`。

---

*“永远不要在没有证据的情况下交易，威科夫方法就是关于证据的收集。”*
