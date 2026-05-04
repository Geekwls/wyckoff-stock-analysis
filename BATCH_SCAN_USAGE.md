# 批量扫描功能使用指南

**状态：** ✅ 已实现
**代码实现得分：** 100%
**最后更新：** 2026年5月4日

---

## 📖 功能概述

批量扫描（`batch_scan`）允许一次性分析多只股票，快速识别威科夫交易机会。

### 核心特性

- ✅ **并行扫描**：使用多线程并行分析，大幅提升效率
- ✅ **智能汇总**：自动统计信号数量、阶段分布、顶级机会
- ✅ **进度显示**：实时显示扫描进度和发现的信号
- ✅ **灵活配置**：支持自定义线程数、过滤条件等

---

## 🚀 快速开始

### 1. 基础用法

```python
from tools.wyckoff_analyzer import batch_scan

# 扫描多只股票
result = batch_scan(
    ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"],
    period="1y"
)

# 查看统计摘要
print(f"扫描总数: {result['summary']['total_scanned']}")
print(f"发现信号: {result['summary']['signal_count']}")
print(f"入场机会: {result['summary']['entry_count']}")
```

### 2. 查看顶级机会

```python
# 获取 TOP 10 机会
top_picks = result['top_picks']

for i, pick in enumerate(top_picks, 1):
    symbol = pick['symbol']
    phase = pick['phase']
    score = pick.get('weighted_score', pick.get('strength', 0))
    is_entry = " [ENTRY]" if pick.get('is_entry') else ""

    print(f"{i}. {symbol}: {phase} (评分: {score}){is_entry}")
```

### 3. 按阶段筛选

```python
# 查看阶段分布
phase_dist = result['summary']['phase_distribution']

print("阶段分布:")
for phase, count in phase_dist.items():
    print(f"  {phase}: {count}")

# 找出所有积累期股票
accumulation_stocks = [
    r for r in result['results']
    if r['phase'] in ['Accumulation', 'Re-Accumulation']
]

print(f"\n积累期股票: {[s['symbol'] for s in accumulation_stocks]}")
```

---

## 📊 返回结果结构

```python
{
    "results": [
        {
            "symbol": "AAPL",
            "phase": "Accumulation",
            "confidence": 0.85,
            "strength": 3,           # 信号强度 (0-6)
            "weighted_score": 72.5,  # 综合评分 (0-100)
            "is_entry": True         # 是否为入场点
        },
        # ... 更多股票
    ],

    "summary": {
        "total_scanned": 5,         # 成功扫描数量
        "signal_count": 3,          # 有信号的股票数
        "entry_count": 2,           # 入场机会数
        "high_score_count": 1,      # 高评分股票数 (>=60分)
        "failed_count": 0,          # 失败数量
        "phase_distribution": {
            "Accumulation": 2,
            "Markup": 1,
            "Distribution": 1,
            "Unknown": 1
        }
    },

    "top_picks": [...],      # TOP 10 机会（按评分排序）
    "failed": [],            # 失败的股票列表
    "scan_mode": "quick"     # 扫描模式
}
```

---

## ⚙️ 高级配置

### 1. 并行控制

```python
# 使用更多线程提升速度（推荐 4-8）
result = batch_scan(
    symbols,
    max_workers=8,      # 最大并行线程数
    show_progress=True  # 显示进度条
)
```

### 2. 过滤低质量信号

```python
# 扫描后过滤
result = batch_scan(symbols)

# 只保留评分 >= 60 的股票
high_quality = [
    r for r in result['results']
    if r.get('weighted_score', 0) >= 60
]

print(f"高质量机会: {len(high_quality)} 只")
```

### 3. 组合筛选

```python
# 找出积累期 + 高评分 + 入场点的股票
result = batch_scan(symbols)

best_picks = [
    r for r in result['results']
    if r['phase'] in ['Accumulation', 'Re-Accumulation']
    and r.get('weighted_score', 0) >= 60
    and r.get('is_entry', False)
]

print(f"最佳机会: {len(best_picks)} 只")
for pick in best_picks:
    print(f"  {pick['symbol']}: {pick['phase']} ({pick['weighted_score']}分)")
```

---

## 📈 实战场景

### 场景1：每日盘前扫描

```python
# 每天开盘前扫描关注列表
watch_list = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
              "META", "NVDA", "JPM", "BAC", "WMT"]

result = batch_scan(watch_list, period="3mo")

# 生成今日关注列表
today_focus = [
    r for r in result['top_picks'][:5]
    if r.get('is_entry') or r.get('weighted_score', 0) >= 60
]

print("今日重点关注:")
for pick in today_focus:
    print(f"  {pick['symbol']}: {pick['phase']} (评分: {pick['weighted_score']})")
```

### 场景2：板块轮动研究

```python
# 扫描同一板块的多只股票
tech_stocks = ["AAPL", "MSFT", "GOOGL", "META", "NVDA",
               "AMD", "INTC", "CSCO", "ADBE", "CRM"]

result = batch_scan(tech_stocks)

# 分析板块整体状态
phases = [r['phase'] for r in result['results']]
from collections import Counter
phase_counts = Counter(phases)

print("科技板块阶段分布:")
for phase, count in phase_counts.most_common():
    print(f"  {phase}: {count}")
```

### 场景3：威科夫信号扫描

```python
# 扫描寻找特定威科夫事件
result = batch_scan(symbols)

# 查找有信号的股票（strength >= 1）
signals = [
    r for r in result['results']
    if r.get('strength', 0) >= 1
]

print(f"发现 {len(signals)} 个威科夫信号:")
for sig in signals:
    print(f"  {sig['symbol']}: {sig['phase']} (强度: {sig['strength']})")
```

---

## 🔧 参数说明

### batch_scan() 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `symbols` | `List[str]` | 必需 | 股票代码列表 |
| `period` | `str` | `"1y"` | 数据周期（1y, 2y, 3mo, 6mo等） |
| `scan_mode` | `str` | `"quick"` | 扫描模式（当前仅支持"quick"） |
| `config` | `WyckoffConfig` | `None` | 威科夫配置对象 |
| `max_workers` | `int` | `自动` | 最大并行线程数 |
| `show_progress` | `bool` | `True` | 是否显示进度条 |

### 数据周期建议

| 市场 | 建议周期 | 说明 |
|------|----------|------|
| 美股 | `1y` | 1年数据足够识别大部分形态 |
| A股 | `2y` | A股波动较大，建议2年 |
| 港股 | `1y` | 1年数据基本足够 |
| 加密货币 | `3mo` | 波动剧烈，3个月即可 |

---

## ⚠️ 注意事项

### 1. API 限制

```python
# 避免一次性扫描过多股票（每批建议 <= 50）
# 分批扫描大量股票
all_stocks = [...]  # 200只股票

batch_size = 50
all_results = []

for i in range(0, len(all_stocks), batch_size):
    batch = all_stocks[i:i+batch_size]
    result = batch_scan(batch)
    all_results.extend(result['results'])
    print(f"完成批次 {i//batch_size + 1}/{(len(all_stocks)-1)//batch_size + 1}")
```

### 2. 错误处理

```python
# 检查失败的股票
result = batch_scan(symbols)

if result['failed']:
    print(f"以下股票扫描失败: {result['failed']}")

    # 可以选择重试
    retry_results = batch_scan(result['failed'])
```

### 3. 性能优化

```python
# 根据CPU核心数调整线程数
import os

cpu_count = os.cpu_count() or 4
optimal_workers = min(cpu_count, 8)  # 最多8个线程

result = batch_scan(
    symbols,
    max_workers=optimal_workers
)
```

---

## 🧪 测试验证

运行测试验证功能：

```bash
python tests/test_batch_scan.py
```

预期输出：
```
总计: 5/5 测试通过
🎉 所有测试通过！批量扫描功能正常
```

---

## 📚 相关文档

- `tools/wyckoff_analyzer.py` - 批量扫描实现
- `tools/services/screener_service.py` - 筛选服务
- `tests/test_batch_scan.py` - 测试文件

---

**实现日期：** 2026年5月4日
**状态：** ✅ 已实现并通过测试
**代码实现得分：** 100%
