#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫工具集 - 筛选和报告
Wyckoff Utilities - Screening and Reporting

合并了原 screener.py 的功能

功能：
1. 股票筛选（积累期/分布期）
2. 入场信号筛选（LPS/LPSY）
3. 生成筛选报告
4. 预定义股票池
"""

import pandas as pd
from typing import List, Dict
from wyckoff_analyzer import WyckoffAnalyzer


class WyckoffScreener:
    """威科夫股票筛选器"""

    def __init__(self):
        self.analyzers = {}

    def add_stock(self, symbol: str, period: str = "1y") -> bool:
        """
        添加股票到筛选列表

        Args:
            symbol: 股票代码
            period: 数据周期

        Returns:
            是否成功添加
        """
        analyzer = WyckoffAnalyzer(symbol, period)
        if analyzer.fetch_data():
            self.analyzers[symbol] = analyzer
            return True
        return False

    def screen_accumulation(self) -> List[Dict]:
        """
        筛选处于积累期的股票

        Returns:
            符合条件的股票列表
        """
        results = []

        for symbol, analyzer in self.analyzers.items():
            phase = analyzer.identify_phase()

            if 'Accumulation' in phase:
                trading_range = analyzer.detect_trading_range()
                spring = analyzer.detect_spring()
                sos = analyzer.detect_sos()
                lps = analyzer.detect_lps()

                score = 0
                if spring['detected']:
                    score += 2
                if sos['detected']:
                    score += 2
                if lps['detected']:
                    score += 3

                if score >= 3:
                    results.append({
                        'symbol': symbol,
                        'phase': phase,
                        'score': score,
                        'has_spring': spring['detected'],
                        'has_sos': sos['detected'],
                        'has_lps': lps['detected'],
                        'trading_range': trading_range,
                        'current_price': analyzer.data['Close'].iloc[-1]
                    })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results

    def screen_distribution(self) -> List[Dict]:
        """
        筛选处于分布期的股票

        Returns:
            符合条件的股票列表
        """
        results = []

        for symbol, analyzer in self.analyzers.items():
            phase = analyzer.identify_phase()

            if 'Distribution' in phase:
                trading_range = analyzer.detect_trading_range()
                upthrust = analyzer.detect_upthrust()
                sow = analyzer.detect_sow()
                lpsy = analyzer.detect_lpsy()

                score = 0
                if upthrust['detected']:
                    score += 2
                if sow['detected']:
                    score += 2
                if lpsy['detected']:
                    score += 3

                if score >= 3:
                    results.append({
                        'symbol': symbol,
                        'phase': phase,
                        'score': score,
                        'has_upthrust': upthrust['detected'],
                        'has_sow': sow['detected'],
                        'has_lpsy': lpsy['detected'],
                        'trading_range': trading_range,
                        'current_price': analyzer.data['Close'].iloc[-1]
                    })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results

    def screen_lps_entries(self) -> List[Dict]:
        """
        筛选有LPS入场信号的股票（做多机会）

        Returns:
            符合条件的股票列表
        """
        results = []

        for symbol, analyzer in self.analyzers.items():
            lps = analyzer.detect_lps()

            if lps['detected']:
                current_price = lps['price']
                stop_loss = current_price * 0.95
                trading_range = analyzer.detect_trading_range()

                if trading_range.get('is_consolidation'):
                    cause_size = trading_range['high'] - trading_range['low']
                    target = trading_range['high'] + cause_size

                    risk = current_price - stop_loss
                    reward = target - current_price
                    rr_ratio = reward / risk if risk > 0 else 0

                    if rr_ratio >= 1.5:
                        results.append({
                            'symbol': symbol,
                            'entry_price': current_price,
                            'stop_loss': stop_loss,
                            'target_price': target,
                            'risk_reward_ratio': rr_ratio,
                            'pullback_pct': lps['pullback_pct'] * 100
                        })

        results.sort(key=lambda x: x['risk_reward_ratio'], reverse=True)
        return results

    def screen_lpsy_entries(self) -> List[Dict]:
        """
        筛选有LPSY入场信号的股票（做空机会）

        Returns:
            符合条件的股票列表
        """
        results = []

        for symbol, analyzer in self.analyzers.items():
            lpsy = analyzer.detect_lpsy()

            if lpsy['detected']:
                current_price = lpsy['price']
                stop_loss = current_price * 1.05
                trading_range = analyzer.detect_trading_range()

                if trading_range.get('is_consolidation'):
                    cause_size = trading_range['high'] - trading_range['low']
                    target = trading_range['low'] - cause_size

                    risk = stop_loss - current_price
                    reward = current_price - target
                    rr_ratio = reward / risk if risk > 0 else 0

                    if rr_ratio >= 1.5:
                        results.append({
                            'symbol': symbol,
                            'entry_price': current_price,
                            'stop_loss': stop_loss,
                            'target_price': target,
                            'risk_reward_ratio': rr_ratio,
                            'rally_pct': lpsy['rally_pct'] * 100
                        })

        results.sort(key=lambda x: x['risk_reward_ratio'], reverse=True)
        return results

    def generate_screening_report(self) -> str:
        """
        生成筛选报告

        Returns:
            格式化的报告文本
        """
        report = """
╔══════════════════════════════════════════════════════════════╗
║           威科夫股票筛选报告                                ║
╚══════════════════════════════════════════════════════════════╝

"""

        # 筛选积累期
        accumulation_stocks = self.screen_accumulation()
        if accumulation_stocks:
            report += f"""
【积累期股票 - 潜在做多机会】

{'='*60}
{'股票代码':<10} {'阶段':<30} {'评分':<5} {'Spring':<8} {'SOS':<8} {'LPS':<8}
{'='*60}
"""
            for stock in accumulation_stocks[:10]:
                report += f"""
{stock['symbol']:<10} {stock['phase']:<30} {stock['score']:<5} {'Y' if stock['has_spring'] else 'N':<8} {'Y' if stock['has_sos'] else 'N':<8} {'Y' if stock['has_lps'] else 'N':<8}
"""
        else:
            report += "\n【积累期股票】\n   暂无符合条件的股票\n"

        # 筛选分布期
        distribution_stocks = self.screen_distribution()
        if distribution_stocks:
            report += f"""
{'='*60}

【分布期股票 - 潜在做空机会】

{'='*60}
{'股票代码':<10} {'阶段':<30} {'评分':<5} {'Upthrust':<8} {'SOW':<8} {'LPSY':<8}
{'='*60}
"""
            for stock in distribution_stocks[:10]:
                report += f"""
{stock['symbol']:<10} {stock['phase']:<30} {stock['score']:<5} {'Y' if stock['has_upthrust'] else 'N':<8} {'Y' if stock['has_sow'] else 'N':<8} {'Y' if stock['has_lpsy'] else 'N':<8}
"""
        else:
            report += "\n【分布期股票】\n   暂无符合条件的股票\n"

        # LPS做多机会
        lps_entries = self.screen_lps_entries()
        if lps_entries:
            report += f"""
{'='*60}

【LPS入场机会 - 做多】

{'='*60}
{'股票代码':<10} {'入场价':<10} {'止损价':<10} {'目标价':<10} {'风险/回报':<10} {'回调%':<10}
{'='*60}
"""
            for entry in lps_entries[:10]:
                report += f"""
{entry['symbol']:<10} ${entry['entry_price']:<9.2f} ${entry['stop_loss']:<9.2f} ${entry['target_price']:<9.2f} {entry['risk_reward_ratio']:<9.2f} {entry['pullback_pct']:<9.1f}%
"""
        else:
            report += "\n【LPS入场机会】\n   暂无符合条件的入场点\n"

        # LPSY做空机会
        lpsy_entries = self.screen_lpsy_entries()
        if lpsy_entries:
            report += f"""
{'='*60}

【LPSY入场机会 - 做空】

{'='*60}
{'股票代码':<10} {'入场价':<10} {'止损价':<10} {'目标价':<10} {'风险/回报':<10} {'反弹%':<10}
{'='*60}
"""
            for entry in lpsy_entries[:10]:
                report += f"""
{entry['symbol']:<10} ${entry['entry_price']:<9.2f} ${entry['stop_loss']:<9.2f} ${entry['target_price']:<9.2f} {entry['risk_reward_ratio']:<9.2f} {entry['rally_pct']:<9.1f}%
"""
        else:
            report += "\n【LPSY入场机会】\n   暂无符合条件的入场点\n"

        report += f"""
{'='*60}

⚠️  风险提示
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

本报告基于威科夫理论和历史数据分析，仅供参考。

1. 所有信号都需要结合其他分析方法确认
2. 请设置好止损，严格执行风险管理
3. A股做空困难，建议谨慎
4. 市场环境变化可能改变形态
5. 建议等待明确确认后再入场

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
股票数量: {len(self.analyzers)}

"""

        return report


# ============================================================
# 预定义股票池
# ============================================================

STOCK_POOLS = {
    'tech': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'INTC', 'CSCO'],
    'china_adrs': ['BABA', 'JD', 'PDD', 'BIDU', 'NTES', 'TCEHY', 'LI', 'NIO'],
    'ev': ['TSLA', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI'],
    'semiconductors': ['NVDA', 'AMD', 'INTC', 'MU', 'ASML', 'TSM', 'SOXX'],
    'a_share_blue': ['贵州茅台', '比亚迪', '宁德时代', '中国平安', '招商银行', '五粮液', '美的集团'],
    'a_share_tech': ['立讯精密', '海康威视', '中芯国际', '韦尔股份', '北方华创'],
}


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import sys

    screener = WyckoffScreener()

    if len(sys.argv) > 1:
        symbols = sys.argv[1:]
    else:
        symbols = STOCK_POOLS['tech']
        print(f"使用默认科技股池: {', '.join(symbols)}\n")

    print("正在获取数据...\n")

    for symbol in symbols:
        if screener.add_stock(symbol):
            print(f"  ✅ {symbol}")
        else:
            print(f"  ❌ {symbol}")

    print("\n" + "="*60)
    print("生成筛选报告...\n")

    report = screener.generate_screening_report()
    print(report)

    filename = f"wyckoff_screening_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n报告已保存到: {filename}")
