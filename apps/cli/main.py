#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析器 - CLI 入口 (应用层)
Wyckoff Analyzer - CLI Entry Point

这是应用层代码，依赖库层 (src/wyckoff/)。
"""

import sys
import os
import argparse
import logging

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# 从库层导入
from src.wyckoff.facade import WyckoffAnalyzer, batch_scan
from src.wyckoff.config.settings import WyckoffConfig

# 强制终端输出为 UTF-8 (解决 Windows 编码问题)
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check_dependencies():
    """检查关键依赖是否已安装"""
    missing = []
    dependencies = {
        'pandas': 'pandas',
        'yfinance': 'yfinance',
        'baostock': 'baostock',
        'pydantic': 'pydantic',
        'tqdm': 'tqdm',
        'numpy': 'numpy',
    }

    for module_name, package_name in dependencies.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)

    if missing:
        print("❌ 缺少依赖包:", ", ".join(missing), file=sys.stderr)
        print("\n请运行以下命令安装依赖:", file=sys.stderr)
        print(f"  pip install -r requirements.txt", file=sys.stderr)
        print("\n或单独安装:", file=sys.stderr)
        print(f"  pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_single(args):
    """分析单只股票"""
    config = WyckoffConfig() if args.use_default else None

    try:
        with WyckoffAnalyzer(args.symbol, args.period, config) as analyzer:
            # 获取数据
            data = analyzer.fetch_data()
            if data is None:
                logger.error(f"无法获取 {args.symbol} 的数据")
                return 1

            # 生成报告
            if args.format == 'json':
                report = analyzer.generate_json()
                print(report)
            else:
                report = analyzer.generate_report()
                print(report)

        return 0

    except Exception as e:
        logger.error(f"分析失败: {e}")
        return 1


def analyze_batch(args):
    """批量扫描股票"""
    try:
        # 解析股票列表
        symbols = args.symbols.split(',') if args.symbols else []
        if not symbols:
            logger.error("请提供股票列表，使用 --symbols 选项")
            return 1

        # 执行批量扫描
        result = batch_scan(
            symbols,
            period=args.period,
            scan_mode=args.mode,
            show_progress=not args.quiet
        )

        # 显示结果
        print(f"\n扫描完成:")
        print(f"  扫描总数: {result['summary']['total_scanned']}")
        print(f"  发现信号: {result['summary']['signal_count']}")
        print(f"  入场机会: {result['summary']['entry_count']}")

        if result['top_picks']:
            print(f"\nTOP 机会:")
            for i, pick in enumerate(result['top_picks'], 1):
                score = pick.get('weighted_score', pick.get('strength', 0))
                phase = pick.get('phase', 'Unknown')
                symbol = pick.get('symbol', 'Unknown')
                entry_tag = " [ENTRY]" if pick.get('is_entry') else ""
                print(f"  {i}. {symbol}: {phase} (评分: {score}){entry_tag}")

        return 0

    except Exception as e:
        logger.error(f"批量扫描失败: {e}")
        return 1


def main():
    """主入口"""
    # 检查依赖
    check_dependencies()

    parser = argparse.ArgumentParser(
        description='威科夫分析器 - 命令行工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 分析单只股票（文本报告）
  python -m apps.cli.main AAPL

  # 分析单只股票（JSON格式）
  python -m apps.cli.main AAPL --format json

  # 批量扫描
  python -m apps.cli.main --batch --symbols "AAPL,MSFT,GOOGL"

  # 使用不同周期
  python -m apps.cli.main AAPL --period 2y
        '''
    )

    # 位置参数
    parser.add_argument(
        'symbol',
        nargs='?',
        help='股票代码（单股票模式）'
    )

    # 通用选项
    parser.add_argument(
        '--period',
        default='1y',
        help='数据周期 (默认: 1y)'
    )
    parser.add_argument(
        '--format',
        choices=['text', 'json'],
        default='text',
        help='输出格式 (默认: text)'
    )
    parser.add_argument(
        '--use-default',
        action='store_true',
        help='使用默认配置'
    )

    # 批量扫描选项
    parser.add_argument(
        '--batch',
        action='store_true',
        help='批量扫描模式'
    )
    parser.add_argument(
        '--symbols',
        help='股票列表（逗号分隔）'
    )
    parser.add_argument(
        '--mode',
        default='quick',
        choices=['quick'],
        help='扫描模式 (默认: quick)'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='安静模式（不显示进度）'
    )

    args = parser.parse_args()

    # 根据模式执行
    if args.batch:
        return analyze_batch(args)
    elif args.symbol:
        return analyze_single(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
