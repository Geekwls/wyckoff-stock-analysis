#!/usr/bin/env python3
"""
威科夫分析使用示例

演示本地工具库用法：
- tools.wyckoff_analyzer.WyckoffAnalyzer：单股分析 / JSON 输出 / 批量扫描
- tools.wyckoff_utils.WyckoffScreener：批量筛选 / 报告生成
"""

import sys
from pathlib import Path

# 确保从项目根目录运行或直接运行本文件时，都能导入项目模块
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def example_local_analyzer():
    """示例1：使用本地分析器进行威科夫分析。"""
    print("=" * 60)
    print("示例 1: 本地分析器 - 威科夫分析")
    print("=" * 60)

    from tools.wyckoff_analyzer import WyckoffAnalyzer

    analyzer = WyckoffAnalyzer("AAPL")
    report = analyzer.generate_report()
    print(report)


def example_local_analyzer_json():
    """示例2：以 JSON 格式获取分析结果（供 AI Agent 读取）。"""
    print("=" * 60)
    print("示例 2: JSON 格式输出")
    print("=" * 60)

    from tools.wyckoff_analyzer import WyckoffAnalyzer

    analyzer = WyckoffAnalyzer("AAPL")
    import os
    from contextlib import redirect_stdout
    with open(os.devnull, 'w') as f, redirect_stdout(f):
        result_json = analyzer.generate_json()
    print(result_json[:500] + "...")


def example_local_screener():
    """示例3：使用本地筛选器进行批量筛选。"""
    print("=" * 60)
    print("示例 3: 本地筛选器 - 批量筛选")
    print("=" * 60)

    from tools.wyckoff_utils import WyckoffScreener

    screener = WyckoffScreener()

    symbols = ["AAPL", "MSFT", "GOOGL"]
    for symbol in symbols:
        if screener.add_stock(symbol):
            print(f"  ✅ {symbol}")
        else:
            print(f"  ❌ {symbol}")

    report = screener.generate_screening_report()
    print(report)


def example_local_batch_scan():
    """示例4：批量扫描多只股票。"""
    print("=" * 60)
    print("示例 4: 批量扫描")
    print("=" * 60)

    from tools.wyckoff_analyzer import batch_scan

    symbols = ["AAPL", "TSLA", "NVDA"]
    results = batch_scan(symbols)

    print(f"\n扫描完成！")
    print(f"总计扫描: {len(symbols)} 只股票")
    print(f"发现信号: {sum(1 for r in results if r['strength'] > 0)} 只")

    if results:
        best = max(results, key=lambda x: x['strength'])
        if best['strength'] > 0:
            print(f"\n最佳机会: {best['symbol']}")
            print(f"   阶段: {best['phase']}")
            print(f"   信号强度: {best['strength']}/6")


def main():
    example_local_analyzer()
    print()
    example_local_screener()
    print()
    example_local_batch_scan()


if __name__ == "__main__":
    main()
