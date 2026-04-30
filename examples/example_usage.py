#!/usr/bin/env python3
"""
威科夫分析 API 使用示例
"""

import os
from dotenv import load_dotenv
import sys

# 加载环境变量
load_dotenv()

# 添加api目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
from wyckoff_api import WyckoffAnalyzer


def example_basic_analysis():
    """基础分析示例"""
    print("=" * 60)
    print("示例 1: 基础股票分析")
    print("=" * 60)

    # 使用 OpenAI 分析苹果股票
    analyzer = WyckoffAnalyzer(
        provider="openai",
        model="gpt-4"
    )

    result = analyzer.analyze("AAPL")
    print(result)
    print()


def example_custom_prompt():
    """自定义提示词示例"""
    print("=" * 60)
    print("示例 2: 使用自定义提示词")
    print("=" * 60)

    analyzer = WyckoffAnalyzer(provider="openai")

    custom_prompt = """
    请分析特斯拉(TSLA)股票，重点关注：
    1. 当前处于威科夫周期的哪个阶段？
    2. 有没有识别到 Spring 或 Upthrust？
    3. 给出具体的入场点位建议
    """

    result = analyzer.analyze("TSLA", custom_prompt=custom_prompt)
    print(result)
    print()


def example_chinese_stock():
    """A股分析示例"""
    print("=" * 60)
    print("示例 3: 分析A股（群兴玩具）")
    print("=" * 60)

    analyzer = WyckoffAnalyzer(provider="openai")

    # A股代码需要加上 .SZ 或 .SS 后缀
    result = analyzer.analyze("002575.SZ")
    print(result)
    print()


def example_with_anthropic():
    """使用 Anthropic Claude 分析"""
    print("=" * 60)
    print("示例 4: 使用 Claude 分析")
    print("=" * 60)

    analyzer = WyckoffAnalyzer(
        provider="anthropic",
        model="claude-3-sonnet-20240229"
    )

    result = analyzer.analyze("NVDA")
    print(result)
    print()


def example_get_stock_data_only():
    """仅获取股票数据，不使用AI分析"""
    print("=" * 60)
    print("示例 5: 获取股票数据")
    print("=" * 60)

    analyzer = WyckoffAnalyzer(provider="openai")

    data = analyzer.get_stock_data("AAPL")
    print(f"股票代码: {data['symbol']}")
    print(f"当前价格: {data['current_price']:.2f}")
    print(f"涨跌幅: {data['change_percent']:.2f}%")
    print(f"成交量: {data['volume']:,.0f}")
    print(f"52周最高: {data['52_week_high']}")
    print(f"52周最低: {data['52_week_low']}")
    print()


def example_multiple_stocks():
    """批量分析多只股票"""
    print("=" * 60)
    print("示例 6: 批量分析股票")
    print("=" * 60)

    analyzer = WyckoffAnalyzer(provider="openai")

    stocks = ["AAPL", "MSFT", "GOOGL"]
    results = {}

    for stock in stocks:
        print(f"正在分析 {stock}...")
        results[stock] = analyzer.analyze(stock)
        print(f"✅ {stock} 分析完成")
        print()

    # 输出所有结果
    for stock, analysis in results.items():
        print(f"\n{'='*60}")
        print(f"{stock} 分析结果:")
        print(f"{'='*60}")
        print(analysis)


if __name__ == "__main__":
    # 确保设置了 API 密钥
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ 错误: 请设置 OPENAI_API_KEY 或 ANTHROPIC_API_KEY 环境变量")
        print("💡 提示: 复制 .env.example 为 .env 并填入你的密钥")
        sys.exit(1)

    # 运行示例（根据需要注释/取消注释）

    # 基础示例
    # example_basic_analysis()

    # 自定义提示词
    # example_custom_prompt()

    # A股示例
    # example_chinese_stock()

    # 使用 Claude
    # example_with_anthropic()

    # 仅获取数据
    example_get_stock_data_only()

    # 批量分析
    # example_multiple_stocks()
