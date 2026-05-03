#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析器 - 核心分析工具
Wyckoff Analyzer - Core Analysis Tool

合并了原 wyckoff_detector.py 和 enhanced_wyckoff_analyzer.py 的核心功能

功能：
1. 数据获取（支持A股、美股、港股）
2. 形态检测（Spring/Upthrust/SOS/SOW/LPS/LPSY）
3. 阶段识别（积累/分布/上涨/下跌）
4. 成交量分析
5. 因果定律计算
6. 相对强度分析
7. 生成分析报告
"""

import pandas as pd
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

# 智能导入：尝试相对导入，失败则用绝对导入
try:
    from .exceptions import WyckoffError, DataFetchError, InsufficientDataError, AnalysisError, PatternDetectionError
    from .config.settings import WyckoffConfig, WyckoffThresholds
    from .core.data_fetcher import WyckoffDataFetcher
    from .core.pattern_detector import WyckoffPatternDetector
    from .core.law_analyzer import WyckoffLawAnalyzer
    from .core.report_generator import WyckoffReportGenerator
    from .core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
    from .core.relative_strength_analyzer import RelativeStrengthAnalyzer
    from .core.cache import LRUCache
except ImportError:
    # 当直接运行脚本时，使用绝对导入
    import sys
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from tools.exceptions import WyckoffError, DataFetchError, InsufficientDataError, AnalysisError, PatternDetectionError
    from tools.config.settings import WyckoffConfig, WyckoffThresholds
    from tools.core.data_fetcher import WyckoffDataFetcher
    from tools.core.pattern_detector import WyckoffPatternDetector
    from tools.core.law_analyzer import WyckoffLawAnalyzer
    from tools.core.report_generator import WyckoffReportGenerator
    from tools.core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
    from tools.core.relative_strength_analyzer import RelativeStrengthAnalyzer
    from tools.core.cache import LRUCache


# 模块级日志，默认不输出；调用方可以通过 logging.basicConfig() 开启
logger = logging.getLogger(__name__)


# ============================================================
# 主分析器类
# ============================================================


class WyckoffAnalyzer:
    """威科夫分析器"""

    def __init__(self, symbol: str, period: str = "1y", config: WyckoffConfig = None):
        """
        初始化分析器

        Args:
            symbol: 股票代码或中文名称
            period: 数据周期 (1y, 2y, 3y, 5y)
            config: 配置参数
        """
        self.symbol = symbol
        self.period = period
        self.config = config or WyckoffConfig()
        self.data_fetcher = WyckoffDataFetcher(self.config)
        self.data = None
        self.pattern_detector = None
        self._index_analyzer_cache: Optional['WyckoffAnalyzer'] = None  # 大盘数据缓存，避免重复IO
        self._analysis_cache = LRUCache(max_size=256, ttl_seconds=3600)
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口，释放资源"""
        self.close()
        return False
    
    def close(self):
        """释放资源"""
        self._analysis_cache.invalidate()
        self._index_analyzer_cache = None
        self.data = None
        self.pattern_detector = None
        self.law_analyzer = None
        self.mtf_analyzer = None
        self.rs_analyzer = None
        
        # 登出baostock
        if hasattr(self.data_fetcher, 'logout_baostock'):
            self.data_fetcher.logout_baostock()

    def _get_cached_index_analyzer(self) -> Optional['WyckoffAnalyzer']:
        """获取大盘分析器（带缓存，避免同一次分析中多次拉取大盘数据）"""
        if self._index_analyzer_cache is not None:
            return self._index_analyzer_cache

        index_symbol = self._get_baseline_index_symbol()
        idx_analyzer = WyckoffAnalyzer(index_symbol, self.period, self.config)

        from contextlib import redirect_stdout
        with open(os.devnull, 'w') as f, redirect_stdout(f):
            data = idx_analyzer.fetch_data()

        if data is not None and not data.empty and idx_analyzer.data is not None:
            self._index_analyzer_cache = idx_analyzer

        return self._index_analyzer_cache

    # ----------------------------------------------------------
    # 数据获取
    # ----------------------------------------------------------

    def fetch_data(self) -> pd.DataFrame:
        """获取股票数据（自动识别市场）"""
        self._analysis_cache.invalidate()
        symbol, data = self.data_fetcher.fetch_data(self.symbol, self.period)
        self.symbol = symbol
        self.data = data
        if self.data is not None:
            self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)
            self.law_analyzer = WyckoffLawAnalyzer(self.data, self.config, self.pattern_detector)
            self.mtf_analyzer = MultiTimeframeAnalyzer(self.data, self.pattern_detector)
            self.rs_analyzer = RelativeStrengthAnalyzer(self.data, self.symbol)
        return self.data

    def _is_a_stock(self, symbol: str) -> bool:
        return self.data_fetcher._is_a_stock(symbol)

    def _get_baseline_index_symbol(self) -> str:
        """获取大盘基准指数代码"""
        symbol = self.symbol.upper()
        if self._is_a_stock(symbol):
            code = symbol.split('.')[-1] if '.' in symbol else symbol
            if code.startswith('6'):
                return "sh.000001"  # 上交所 - 上证指数
            elif code.startswith('3'):
                return "sz.399006"  # 创业板 - 创业板指
            elif code.startswith('0'):
                return "sz.399001"  # 深交所 - 深证成指
            else:
                return "sh.000001"
        elif symbol.endswith('.HK'):
            return "^HSI"  # 港股 - 恒生指数
        else:
            return "SPY"  # 美股/其他 - 标普500

    # ----------------------------------------------------------
    # 形态检测（委托给 WyckoffPatternDetector，通过 pattern_detector 属性访问）
    # 例如：self.pattern_detector.detect_spring()、detect_joc()、detect_vsa_signals() 等
    # ----------------------------------------------------------

    # ----------------------------------------------------------
    # 阶段识别
    # ----------------------------------------------------------

    # ----------------------------------------------------------


    # ----------------------------------------------------------
    # 阶段识别
    # ----------------------------------------------------------






























    # ----------------------------------------------------------
    # 阶段识别
    # ----------------------------------------------------------




    def _get_weekly_trend(self) -> str:
        """获取周线趋势（委派至 mtf_analyzer）"""
        return self.mtf_analyzer.get_weekly_trend()

    def _get_monthly_trend(self) -> str:
        """获取月线趋势（委派至 mtf_analyzer）"""
        return self.mtf_analyzer.get_monthly_trend()

    def _check_timeframe_agreement(self, daily_phase: str, weekly_trend: str, monthly_trend: str) -> str:
        """检查多时间框架是否一致"""
        if 'Accumulation' in daily_phase or 'Markup' in daily_phase:
            if weekly_trend == 'bullish' and monthly_trend == 'bullish': return 'strong_agreement'
            elif weekly_trend == 'bullish' or monthly_trend == 'bullish': return 'moderate_agreement'
            return 'disagreement'
        elif 'Distribution' in daily_phase or 'Markdown' in daily_phase:
            if weekly_trend == 'bearish' and monthly_trend == 'bearish': return 'strong_agreement'
            elif weekly_trend == 'bearish' or monthly_trend == 'bearish': return 'moderate_agreement'
            return 'disagreement'
        return 'unknown'

    def analyze_timeframe_resonance(self) -> Dict:
        """增强的多时间框架共振分析（委派至 mtf_analyzer）"""
        res = self.mtf_analyzer.analyze_resonance()
        res['implication'] = self._get_resonance_implication(res['resonance_level'])
        res['trading_recommendation'] = self._get_resonance_trading_recommendation(res['resonance_level'], {'phase': res['daily_phase']})
        return res

    def _get_resonance_implication(self, level: str) -> str:
        mapping = {
            'strong_resonance': '多时间框架强烈共振，信号可靠性极高',
            'moderate_resonance': '多时间框架共振良好，信号可靠性较高',
            'weak_resonance': '多时间框架有共振迹象，需要进一步确认',
            'no_resonance': '多时间框架无共振，信号可靠性较低'
        }
        return mapping.get(level, '未知共振状态')

    def _get_resonance_trading_recommendation(self, resonance_level: str, daily_analysis: Dict) -> Dict:
        """根据共振等级提供交易建议"""
        phase = daily_analysis.get('phase', '')
        if resonance_level == 'strong_resonance':
            if 'Accumulation' in phase or 'Markup' in phase:
                return {'action': 'strong_buy', 'position_size': 'aggressive', 'reason': f'多时间框架强烈共振 + {phase}'}
            else:
                return {'action': 'strong_sell', 'position_size': 'aggressive', 'reason': f'多时间框架强烈共振 + {phase}'}
        elif resonance_level == 'moderate_resonance':
            if 'Accumulation' in phase or 'Markup' in phase:
                return {'action': 'moderate_buy', 'position_size': 'moderate', 'reason': f'多时间框架中等共振 + {phase}'}
            else:
                return {'action': 'moderate_sell', 'position_size': 'moderate', 'reason': f'多时间框架中等共振 + {phase}'}
        return {'action': 'wait', 'position_size': 'conservative', 'reason': '共振信号不足'}

    def identify_phase_with_rs(self) -> Dict:
        """结合相对强度的阶段识别"""
        # 获取大盘分析器
        idx_analyzer = self._get_cached_index_analyzer()
        if idx_analyzer is None or idx_analyzer.data is None:
            rs_data = {'rs_trend': 'unknown', 'rs_value': None}
        else:
            rs_data = self.rs_analyzer.calculate_rs(idx_analyzer.data)
        
        base_phase = self.identify_phase_multi_timeframe()
        confidence = base_phase.get('confidence', 0.0)
        
        if rs_data.get('rs_trend') == 'rising':
            if 'Accumulation' in base_phase['phase'] or 'Markup' in base_phase['phase']:
                confidence *= 1.15
            elif 'Distribution' in base_phase['phase'] or 'Markdown' in base_phase['phase']:
                confidence *= 0.75
        elif rs_data.get('rs_trend') == 'falling':
            if 'Distribution' in base_phase['phase'] or 'Markdown' in base_phase['phase']:
                confidence *= 1.15
            elif 'Accumulation' in base_phase['phase'] or 'Markup' in base_phase['phase']:
                confidence *= 0.75
                
        base_phase['relative_strength'] = rs_data
        base_phase['confidence'] = min(confidence, 1.0)
        return base_phase

    def identify_phase_multi_timeframe(self) -> Dict:
        """多时间框架综合阶段识别"""
        daily_analysis = self.pattern_detector.identify_phase()
        weekly_trend = self.mtf_analyzer.get_weekly_trend()
        monthly_trend = self.mtf_analyzer.get_monthly_trend()
        
        agreement = self._check_timeframe_agreement(daily_analysis['phase'], weekly_trend, monthly_trend)
        
        confidence = daily_analysis.get('confidence', 0.5)
        if agreement == 'strong_agreement': confidence = min(confidence * 1.25, 1.0)
        elif agreement == 'moderate_agreement': confidence = min(confidence * 1.1, 1.0)
        elif agreement == 'disagreement': confidence = confidence * 0.8
            
        return {
            'phase': daily_analysis['phase'],
            'confidence': round(confidence, 2),
            'daily_analysis': daily_analysis,
            'weekly_trend': weekly_trend,
            'monthly_trend': monthly_trend,
            'agreement': agreement
        }

    def _analyze_market_environment(self) -> Dict:
        """量化大盘环境（强牛/牛/弱牛/震荡/熊/强熊）- 使用缓存避免重复 IO"""
        try:
            index_symbol = self._get_baseline_index_symbol()
            idx_analyzer = self._get_cached_index_analyzer()
                
            if idx_analyzer is None or idx_analyzer.data is None or len(idx_analyzer.data) < 200:
                return {'environment': 'unknown', 'index': index_symbol}
                
            df = idx_analyzer.data
            close = df['Close'].iloc[-1]
            ma20 = df['MA20'].iloc[-1]
            ma50 = df['MA50'].iloc[-1]
            ma200 = df['MA200'].iloc[-1]
            
            # 判断均线粘合 (震荡市特征)
            ma_values = [ma20, ma50, ma200]
            max_ma = max(ma_values)
            min_ma = min(ma_values)
            ma_spread_pct = (max_ma - min_ma) / min_ma
            
            if ma_spread_pct < 0.02:
                environment = 'Range Bound (震荡)'
            elif close > ma20 and ma20 > ma50 and ma50 > ma200:
                environment = 'Strong Bull (强牛)'
            elif close > ma50 and ma50 > ma200:
                environment = 'Bull (牛)'
            elif close > ma200 and ma20 < ma50:
                environment = 'Weak Bull (弱牛)'
            elif close < ma20 and ma20 < ma50 and ma50 < ma200:
                environment = 'Strong Bear (强熊)'
            elif close < ma50 and ma50 < ma200:
                environment = 'Bear (熊)'
            else:
                environment = 'Range Bound (震荡)'
                
            return {
                'environment': environment,
                'index': index_symbol,
                'ma_spread_pct': round(ma_spread_pct * 100, 2)
            }
        except Exception:
            return {'environment': 'unknown', 'index': self._get_baseline_index_symbol()}

    # ----------------------------------------------------------
    # 因果定律计算
    # ----------------------------------------------------------

    def calculate_cause_effect(self) -> Dict:
        """计算因果定律目标 - 升级版
        升级：将积累期持续时间（consolidation_duration_days）纳入目标价成气计算
        原则：积累时间越长，因果越大，突破目标距离越远
        """
        if self.data is None or len(self.data) < 60:
            return {}

        tr_info = self.pattern_detector.detect_trading_range()
        if not tr_info.get('is_consolidation'):
            raise PatternDetectionError("交易区间", "无法识别有效的交易区间")

        cause_size = tr_info['high'] - tr_info['low']
        current_price = tr_info['current_price']
        position = tr_info['position']

        # 时间因子：积累期越长，目标逐渐放大。基准是 60 天
        duration_days = tr_info.get('consolidation_duration_days', 60)
        time_factor = min(duration_days / 60.0, 3.0)  # 最多放大到 3倍，防止过于乐观

        # 目标位 = 突破点 + 区间幅度 x 时间因子 x 费波那奇系数
        if position > 0.5:
            breakout_point = tr_info['high']
            targets = {
                'target_1': round(breakout_point + cause_size * 0.618 * time_factor, 2),
                'target_2': round(breakout_point + cause_size * 1.0   * time_factor, 2),
                'target_3': round(breakout_point + cause_size * 1.618 * time_factor, 2),
            }
        else:
            breakout_point = tr_info['low']
            targets = {
                'target_1': round(breakout_point - cause_size * 0.618 * time_factor, 2),
                'target_2': round(breakout_point - cause_size * 1.0   * time_factor, 2),
                'target_3': round(breakout_point - cause_size * 1.618 * time_factor, 2),
            }

        return {
            'cause_size': round(cause_size, 2),
            'breakout_point': round(breakout_point, 2),
            'targets': targets,
            'current_position': round(position, 2),
            'consolidation_duration_days': duration_days,
            'time_factor': round(time_factor, 2),
            'method': 'Wyckoff Cause & Effect (duration-adjusted Fibonacci)'
        }

    # ----------------------------------------------------------
    # 报告生成
    # ----------------------------------------------------------

    def generate_report(self) -> str:
        return WyckoffReportGenerator(self).generate_report()
        
    def generate_json(self) -> str:
        return WyckoffReportGenerator(self).generate_json()

# ============================================================
# 批量扫描功能
# ============================================================

def batch_scan(symbols: List[str], period: str = "1y", use_json: bool = False,
               max_workers: int = None, show_progress: bool = True) -> List[Dict]:
    """
    批量扫描股票 (统一转发至 ScreenerService)
    """
    try:
        from .services.screener_service import ScreenerService
    except ImportError:
        from tools.services.screener_service import ScreenerService
        
    screener = ScreenerService()
    return screener.quick_scan(
        symbols=symbols, 
        period=period, 
        max_workers=max_workers, 
        show_progress=show_progress
    )

# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse
    import sys
    import io
    
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    parser = argparse.ArgumentParser(description="威科夫股票分析工具")
    parser.add_argument("symbol", nargs="?", help="股票代码 (如 AAPL, 600519)")
    parser.add_argument("--json", action="store_true", help="以JSON格式输出 (供AI Agent使用)")
    parser.add_argument("--batch", action="store_true", help="运行批量扫描示例")
    
    args = parser.parse_args()

    if args.symbol:
        analyzer = WyckoffAnalyzer(args.symbol)
        if args.json:
            import os, sys
            from contextlib import redirect_stdout
            with open(os.devnull, 'w') as f, redirect_stdout(f):
                result_json = analyzer.generate_json()
            print(result_json)
        else:
            print(analyzer.generate_report())
    elif args.batch:
        symbols = ['AAPL', 'TSLA', 'NVDA', 'MSFT', 'GOOGL']
        print("批量扫描美股示例...\n")
        results = batch_scan(symbols)

        print("\n扫描完成！\n")
        print(f"总计扫描: {len(symbols)} 只股票")
        print(f"发现信号: {sum(1 for r in results if r['strength'] > 0)} 只")

        if results:
            best = max(results, key=lambda x: x['strength'])
            if best['strength'] > 0:
                print(f"\n最佳机会: {best['symbol']}")
                print(f"   阶段: {best['phase']}")
                print(f"   信号强度: {best['strength']}/6")
    else:
        parser.print_help()
