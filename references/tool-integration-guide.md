# 威科夫理论与自动化工具集成指南
# Wyckoff Theory & Tool Integration Guide

本文档旨在指导用户如何利用本项目提供的 Python 工具库（v4.2.0+）来验证和辅助威科夫理论的实战分析。

---

## 1. 核心映射：理论 vs. 工具

| 威科夫理论概念 | 对应工具/方法 | 说明 |
| :--- | :--- | :--- |
| **阶段识别 (Phase)** | `WyckoffAnalyzer.identify_phase()` | 自动判断当前处于 Accumulation/Distribution 的哪个子阶段。 |
| **关键信号 (Spring/SOS)** | `PatternDetector.detect_all_patterns()` | 通过向量化算法检测 Spring, Upthrust, SOS, SOW 等事件。 |
| **努力 vs 结果 (Effort)** | `LawAnalyzer.analyze_effort_vs_result()` | 对比量价关系，判断当前上涨/下跌的有效性。 |
| **相对强度 (RS)** | `DataFetcher.get_relative_strength()` | 计算个股相对于基准指数（如 S&P 500 或 沪深300）的强度。 |
| **市场全景扫描** | `ScreenerService.quick_scan()` | 并行扫描大量股票，快速定位有信号的标的。 |

---

## 2. 实战场景示例

### 场景 A：我想寻找正在“洗盘”的股票 (Spring)
**理论依据**：在积累期末端，价格跌破支撑位后快速收回。
**工具操作**：
```python
from wyckoff import ScreenerService, STOCK_POOLS

# 使用深度筛选功能，过滤出处于积累期（Accumulation）且有信号的股票
screener = ScreenerService()
potential_springs = screener.deep_screen(STOCK_POOLS['tech_giants'], screen_type='accumulation')

# 检查结果中的信号
for stock in potential_springs:
    if stock['has_spring']:
        print(f"发现潜在 Spring: {stock['symbol']}")
```

### 场景 B：我想验证一个 SOS 信号的可靠性
**理论依据**：SOS 必须伴随成交量放大，且随后不应立即跌破突破位。
**工具操作**：
```python
with WyckoffAnalyzer("AAPL") as analyzer:
    report = analyzer.generate_json()
    # 查看 LawAnalyzer 的分析结论
    print(f"努力vs结果分析: {report['laws_analysis']['effort_vs_result']['conclusion']}")
    # 查看回测数据（如果支持）
    print(f"该信号历史胜率参考: {report['backtest']['win_rate']}%")
```

---

## 3. 自动化复盘工作流

建议的每日复盘流程：

1.  **全局扫描**：运行 `python tools/wyckoff_analyzer.py --batch` 获取当日市场信号概览。
2.  **重点诊断**：对扫描出的“强度 > 3”的个股，在 Cursor 或 Claude 中通过 MCP 工具 `analyze_stock_wyckoff` 进行深度诊断。
3.  **量化校验**：查看 JSON 输出中的 `confidence`（置信度）和 `signals` 列表。
4.  **历史参考**：查看 `backtest_results`，了解该股票在历史上出现类似形态后的平均表现。

---

## 4. 常见问题 (FAQ)

**Q: 为什么工具识别的阶段跟我看的不一样？**
A: 工具基于严格的数学阈值（定义在 `.env` 或 `settings.py` 中）。威科夫分析具有一定的主观性，建议将工具输出作为“第二意见”进行交叉验证。

**Q: 如何调整检测的灵敏度？**
A: 修改 `tools/config/settings.py` 中的阈值。例如，减小 `SPRING_LOOKBACK` 可以检测更短期的震仓行为。

---

**相关文档**：
- [README.md](../README.md) - 项目总览
- [learning-path.md](learning-path.md) - 学习路径
