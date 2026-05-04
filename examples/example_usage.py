#!/usr/bin/env python3
"""
威科夫分析使用示例

演示库层用法：
- src.wyckoff.facade.WyckoffAnalyzer：单股分析 / JSON 输出 / 批量扫描
- src.wyckoff.facade.batch_scan：批量扫描
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

    from src.wyckoff.facade import WyckoffAnalyzer

    analyzer = WyckoffAnalyzer("AAPL")
    analyzer.fetch_data()
    report = analyzer.generate_report()
    print(report)


def example_local_analyzer_json():
    """示例2：以 JSON 格式获取分析结果（供 AI Agent 读取）。"""
    print("=" * 60)
    print("示例 2: JSON 格式输出")
    print("=" * 60)

    from src.wyckoff.facade import WyckoffAnalyzer

    analyzer = WyckoffAnalyzer("AAPL")
    analyzer.fetch_data()
    result_json = analyzer.generate_json()
    print(result_json[:500] + "...")


def example_local_batch_scan():
    """示例3：批量扫描多只股票。"""
    print("=" * 60)
    print("示例 3: 批量扫描")
    print("=" * 60)

    from src.wyckoff.facade import batch_scan

    symbols = ["AAPL", "TSLA", "NVDA"]
    result = batch_scan(symbols, show_progress=False)

    print(f"\n扫描完成！")
    print(f"总计扫描: {result['summary']['total_scanned']} 只股票")
    print(f"发现信号: {result['summary']['signal_count']} 只")

    if result['top_picks']:
        best = result['top_picks'][0]
        print(f"\n最佳机会: {best['symbol']}")
        print(f"   阶段: {best['phase']}")
        print(f"   综合评分: {best.get('weighted_score', best.get('strength', 0))}")


def main():
    example_local_analyzer()
    print()
    example_local_analyzer_json()
    print()
    example_local_batch_scan()


if __name__ == "__main__":
    main()
