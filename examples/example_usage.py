#!/usr/bin/env python3
"""
威科夫分析使用示例

包含两类用法：
1. AI API 分析入口：api.wyckoff_api.WyckoffAnalyzer
2. 本地工具库：tools.wyckoff_analyzer / tools.wyckoff_utils
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 确保从项目根目录运行或直接运行本文件时，都能导入项目模块
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")


def example_api_basic_analysis():
    """示例1：使用AI API进行基础分析。需要 OPENAI_API_KEY 或 ANTHROPIC_API_KEY。"""
    print("=" * 60)
    print("示例 1: AI API 基础股票分析")
    print("=" * 60)

    if not os.getenv("OPENAI_API_KEY"):
        print("跳过：未设置 OPENAI_API_KEY")
        return

    from api.wyckoff_api import WyckoffAnalyzer

    analyzer = WyckoffAnalyzer(provider="openai", model="gpt-4")
    result = analyzer.analyze("AAPL")
    print(result)


def example_api_get_stock_data_only():
    """示例2：仅获取股票数据，不调用AI。"""
    print("=" * 60)
    print("示例 2: 获取股票数据")
    print("=" * 60)

    from api.wyckoff_api import WyckoffAnalyzer

    # get_stock_data 不依赖 OpenAI，但 WyckoffAnalyzer(provider='ollama') 可避免API Key检查
    analyzer = WyckoffAnalyzer(provider="ollama", model="llama2")
    data = analyzer.get_stock_data("AAPL")

    if "error" in data:
        print(data["error"])
        return

    print(f"股票代码: {data['symbol']}")
    print(f"当前价格: {data['current_price']:.2f}")
    print(f"涨跌幅: {data['change_percent']:.2f}%")
    print(f"成交量: {data['volume']:,.0f}")
    print(f"52周最高: {data['52_week_high']}")
    print(f"52周最低: {data['52_week_low']}")


def example_local_analyzer():
    """示例3：使用本地分析器进行威科夫分析。"""
    print("=" * 60)
    print("示例 3: 本地分析器 - 威科夫分析")
    print("=" * 60)

    from tools.wyckoff_analyzer import WyckoffAnalyzer

    # 初始化分析器
    analyzer = WyckoffAnalyzer("AAPL")

    # 生成分析报告
    report = analyzer.generate_report()
    print(report)


def example_local_screener():
    """示例4：使用本地筛选器进行批量筛选。"""
    print("=" * 60)
    print("示例 4: 本地筛选器 - 批量筛选")
    print("=" * 60)

    from tools.wyckoff_utils import WyckoffScreener

    # 创建筛选器
    screener = WyckoffScreener()

    # 添加股票
    symbols = ["AAPL", "MSFT", "GOOGL"]
    for symbol in symbols:
        if screener.add_stock(symbol):
            print(f"  ✅ {symbol}")
        else:
            print(f"  ❌ {symbol}")

    # 生成筛选报告
    report = screener.generate_screening_report()
    print(report)


def example_local_batch_scan():
    """示例5：使用本地分析器进行批量扫描。"""
    print("=" * 60)
    print("示例 5: 本地分析器 - 批量扫描")
    print("=" * 60)

    from tools.wyckoff_analyzer import batch_scan

    # 批量扫描
    symbols = ["AAPL", "TSLA", "NVDA"]
    results = batch_scan(symbols)

    # 显示结果
    print(f"\n扫描完成！")
    print(f"总计扫描: {len(symbols)} 只股票")
    print(f"发现信号: {sum(1 for r in results if r['strength'] > 0)} 只")

    # 显示最佳机会
    if results:
        best = max(results, key=lambda x: x['strength'])
        if best['strength'] > 0:
            print(f"\n最佳机会: {best['symbol']}")
            print(f"   阶段: {best['phase']}")
            print(f"   信号强度: {best['strength']}/4")


def main():
    """默认运行无需API Key的本地示例。"""
    example_local_analyzer()
    print()
    example_local_screener()
    print()
    example_local_batch_scan()

    # 如需真实行情/AI分析，可手动取消注释：
    # example_api_get_stock_data_only()
    # example_api_basic_analysis()


if __name__ == "__main__":
    main()
