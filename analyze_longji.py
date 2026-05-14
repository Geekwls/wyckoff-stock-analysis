#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析：隆基绿能 (601012.SH)
"""

import sys
from pathlib import Path

# 确保从项目根目录运行
PROJECT_ROOT = Path(__file__).resolve().parents[0]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.wyckoff.wyckoff_analyzer import WyckoffAnalyzer


def main():
    print("=" * 80)
    print("📈 威科夫分析：隆基绿能 (601012.SH)")
    print("=" * 80)
    print()

    # 创建分析器 - 隆基绿能
    analyzer = WyckoffAnalyzer("sh.601012", period="2y")

    # 获取数据
    print("正在获取数据...")
    analyzer.fetch_data()

    if analyzer.data is None or len(analyzer.data) < 60:
        print("❌ 数据不足，无法进行分析")
        return

    print(f"✅ 数据获取成功！共 {len(analyzer.data)} 条记录")
    print(f"时间范围：{analyzer.data.index[0].strftime('%Y-%m-%d')} 至 {analyzer.data.index[-1].strftime('%Y-%m-%d')}")
    print(f"当前价格：{analyzer.data['Close'].iloc[-1]:.2f} 元")
    print()

    # 生成报告
    print("正在生成威科夫分析报告...")
    print()
    print("=" * 80)
    report = analyzer.generate_report()
    print(report)
    print("=" * 80)

    # 也可以生成JSON格式（供AI读取）
    # json_report = analyzer.generate_json()
    # print("\nJSON报告:")
    # print(json_report)

    analyzer.close()


if __name__ == "__main__":
    main()
