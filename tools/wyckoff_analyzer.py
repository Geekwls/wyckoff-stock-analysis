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

import yfinance as yf
import baostock as bs
import pandas as pd
import numpy as np
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any, TypedDict
from enum import Enum, auto
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 智能导入：尝试相对导入，失败则用绝对导入
try:
    from .exceptions import WyckoffError, DataFetchError, InsufficientDataError, AnalysisError
    from .config.settings import WyckoffConfig, WyckoffThresholds
    from .core.data_fetcher import WyckoffDataFetcher
    from .core.pattern_detector import WyckoffPatternDetector
    from .core.law_analyzer import WyckoffLawAnalyzer
    from .core.report_generator import WyckoffReportGenerator
    from .core.report_generator import WyckoffReportGenerator
except ImportError:
    # 当直接运行脚本时，使用绝对导入
    import sys
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from tools.exceptions import WyckoffError, DataFetchError, InsufficientDataError, AnalysisError
    from tools.config.settings import WyckoffConfig, WyckoffThresholds
    from tools.core.data_fetcher import WyckoffDataFetcher
    from tools.core.pattern_detector import WyckoffPatternDetector
    from tools.core.law_analyzer import WyckoffLawAnalyzer
    from tools.core.report_generator import WyckoffReportGenerator
    from tools.core.report_generator import WyckoffReportGenerator

# 模块级日志，默认不输出；调用方可以通过 logging.basicConfig() 开启
logger = logging.getLogger(__name__)


# ============================================================
# 枚举和配置
# ============================================================

class MarketPhase(Enum):
    """市场阶段枚举"""
    ACCUMULATION = auto()
    MARKUP = auto()
    DISTRIBUTION = auto()
    MARKDOWN = auto()
    UNKNOWN = auto()


class PhaseResult(TypedDict):
    """阶段识别结果类型"""
    phase: str
    confidence: float
    events_detected: Dict[str, Any]
    ma_confidence: float
    vol_confidence: float
    sequence_score: Dict[str, Any]
    divergence: Dict[str, Any]


class SpringSignal(TypedDict):
    """Spring信号类型"""
    date: datetime
    breakdown_price: float
    support_level: float
    recovery_day: int
    recovery_price: float
    close_above_support: bool
    vol_pattern: str
    confidence: float


class SpringResult(TypedDict):
    """Spring检测结果类型"""
    detected: bool
    reason: Optional[str]
    signals: Optional[List[SpringSignal]]
    latest_spring: Optional[SpringSignal]





@dataclass
class AnalysisCache:
    """分析结果缓存"""
    _cache: Dict[str, Any] = None
    
    def __post_init__(self):
        self._cache = {}
    
    def get_or_compute(self, key: str, compute_fn, *args, **kwargs):
        if key not in self._cache:
            self._cache[key] = compute_fn(*args, **kwargs)
        return self._cache[key]
    
    def invalidate(self, key: str = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


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
        self._analysis_cache = AnalysisCache()

    def _get_cached_index_analyzer(self) -> Optional['WyckoffAnalyzer']:
        """获取大盘分析器（带缓存，避免同一次分析中多次拉取大盘数据）"""
        if self._index_analyzer_cache is not None:
            return self._index_analyzer_cache

        index_symbol = self._get_baseline_index_symbol()
        idx_analyzer = WyckoffAnalyzer(index_symbol, self.period, self.config)

        import os as _os
        from contextlib import redirect_stdout
        with open(_os.devnull, 'w') as f, redirect_stdout(f):
            success = idx_analyzer.fetch_data()

        if success is not None and (not isinstance(success, pd.DataFrame) or not success.empty) and idx_analyzer.data is not None:
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
    # 形态检测
    # ----------------------------------------------------------




























    # ----------------------------------------------------------
    # 阶段识别
    # ----------------------------------------------------------





    def identify_phase_multi_timeframe(self) -> Dict:
        """多时间框架阶段确认"""
        daily_phase = self.pattern_detector.identify_phase()
        weekly_trend = self._get_weekly_trend()
        monthly_trend = self._get_monthly_trend()
        
        final_confidence = daily_phase['confidence']
        phase_str = daily_phase['phase']
        
        if 'Accumulation' in phase_str or 'Markup' in phase_str:
            if weekly_trend == 'bullish' and monthly_trend != 'bearish':
                final_confidence *= 1.2
            elif weekly_trend == 'bearish':
                final_confidence *= 0.7
        elif 'Distribution' in phase_str or 'Markdown' in phase_str:
            if weekly_trend == 'bearish' and monthly_trend != 'bullish':
                final_confidence *= 1.2
            elif weekly_trend == 'bullish':
                final_confidence *= 0.7
                
        return {
            'phase': phase_str,
            'confidence': min(final_confidence, 1.0),
            'daily_phase': daily_phase,
            'weekly_trend': weekly_trend,
            'monthly_trend': monthly_trend,
            'multi_timeframe_agreement': self._check_timeframe_agreement(phase_str, weekly_trend, monthly_trend)
        }

    def _get_weekly_trend(self) -> str:
        """获取周线趋势"""
        df = self.data.copy()
        df['Week'] = df.index.isocalendar().week
        df['Year'] = df.index.isocalendar().year
        
        weekly = df.groupby(['Year', 'Week']).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })
        
        if len(weekly) < 20:
            return 'unknown'
            
        weekly['MA10'] = weekly['Close'].rolling(10).mean()
        weekly['MA20'] = weekly['Close'].rolling(20).mean()
        
        current_close = weekly['Close'].iloc[-1]
        ma10 = weekly['MA10'].iloc[-1]
        ma20 = weekly['MA20'].iloc[-1]
        
        if current_close > ma10 > ma20: return 'bullish'
        elif current_close < ma10 < ma20: return 'bearish'
        return 'neutral'

    def _get_monthly_trend(self) -> str:
        """获取月线趋势"""
        df = self.data.copy()
        df['Month'] = df.index.month
        df['Year'] = df.index.year
        
        monthly = df.groupby(['Year', 'Month']).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })
        
        if len(monthly) < 12:
            return 'unknown'
            
        monthly['MA6'] = monthly['Close'].rolling(6).mean()
        monthly['MA12'] = monthly['Close'].rolling(12).mean()
        
        current_close = monthly['Close'].iloc[-1]
        ma6 = monthly['MA6'].iloc[-1]
        ma12 = monthly['MA12'].iloc[-1]
        
        if current_close > ma6 > ma12: return 'bullish'
        elif current_close < ma6 < ma12: return 'bearish'
        return 'neutral'

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
        """
        增强的多时间框架共振分析
        分析日线、周线、月线的威科夫形态共振情况
        """
        # 获取日线分析结果
        daily_analysis = self.pattern_detector.identify_phase()
        daily_events = daily_analysis.get('events_detected', {}) or {}

        # 检查周线和月线是否出现相似形态
        weekly_resonance = self._check_timeframe_signal_resonance('weekly')
        monthly_resonance = self._check_timeframe_signal_resonance('monthly')

        # 计算共振强度
        resonance_strength = 0
        resonance_signals = []

        # 检查Spring共振
        spring_upthrust = daily_events.get('spring_upthrust') or {}
        if spring_upthrust.get('_type') == 'spring':
            resonance_strength += 1
            resonance_signals.append('daily_spring')

        if weekly_resonance.get('has_spring'):
            resonance_strength += 2
            resonance_signals.append('weekly_spring')

        if monthly_resonance.get('has_spring'):
            resonance_strength += 3
            resonance_signals.append('monthly_spring')

        # 检查SOS共振
        sos_sow = daily_events.get('sos_sow') or {}
        if sos_sow.get('_type') == 'sos':
            resonance_strength += 1
            resonance_signals.append('daily_sos')

        if weekly_resonance.get('has_sos'):
            resonance_strength += 2
            resonance_signals.append('weekly_sos')

        if monthly_resonance.get('has_sos'):
            resonance_strength += 3
            resonance_signals.append('monthly_sos')

        # 检查趋势共振
        weekly_trend = self._get_weekly_trend()
        monthly_trend = self._get_monthly_trend()

        trend_agreement = False
        if 'Accumulation' in daily_analysis.get('phase', '') or 'Markup' in daily_analysis.get('phase', ''):
            trend_agreement = (weekly_trend == 'bullish' and monthly_trend != 'bearish')
        elif 'Distribution' in daily_analysis.get('phase', '') or 'Markdown' in daily_analysis.get('phase', ''):
            trend_agreement = (weekly_trend == 'bearish' and monthly_trend != 'bullish')

        if trend_agreement:
            resonance_strength += 2
            resonance_signals.append('trend_agreement')

        # 评估共振等级
        if resonance_strength >= 8:
            resonance_level = 'strong_resonance'
            implication = '多时间框架强烈共振，信号可靠性极高'
        elif resonance_strength >= 5:
            resonance_level = 'moderate_resonance'
            implication = '多时间框架共振良好，信号可靠性较高'
        elif resonance_strength >= 2:
            resonance_level = 'weak_resonance'
            implication = '多时间框架有共振迹象，需要进一步确认'
        else:
            resonance_level = 'no_resonance'
            implication = '多时间框架无共振，信号可靠性较低'

        return {
            'resonance_level': resonance_level,
            'resonance_strength': resonance_strength,
            'resonance_signals': resonance_signals,
            'implication': implication,
            'daily_phase': daily_analysis.get('phase', 'unknown'),
            'weekly_trend': weekly_trend,
            'monthly_trend': monthly_trend,
            'trend_agreement': trend_agreement,
            'weekly_analysis': weekly_resonance,
            'monthly_analysis': monthly_resonance,
            'trading_recommendation': self._get_resonance_trading_recommendation(resonance_level, daily_analysis)
        }

    def _check_timeframe_signal_resonance(self, timeframe: str) -> Dict:
        """
        检查特定时间框架的威科夫形态信号
        timeframe: 'weekly' 或 'monthly'
        """
        if self.data is None or len(self.data) < 60:
            return {}

        try:
            # 重采样数据
            if timeframe == 'weekly':
                df = self.data.copy()
                df['Week'] = df.index.isocalendar().week
                df['Year'] = df.index.isocalendar().year
                resampled = df.groupby(['Year', 'Week']).agg({
                    'Open': 'first', 'High': 'max', 'Low': 'min',
                    'Close': 'last', 'Volume': 'sum'
                })
                min_periods = 20
            else:  # monthly
                df = self.data.copy()
                df['Month'] = df.index.month
                df['Year'] = df.index.year
                resampled = df.groupby(['Year', 'Month']).agg({
                    'Open': 'first', 'High': 'max', 'Low': 'min',
                    'Close': 'last', 'Volume': 'sum'
                })
                min_periods = 12

            if len(resampled) < min_periods:
                return {'insufficient_data': True}

            # 简化的形态检测（基于关键指标）
            has_spring = False
            has_sos = False
            has_upthrust = False

            # 检测Spring（低位支撑测试）
            recent_data = resampled.tail(10)
            low = recent_data['Low'].min()
            recent_low = recent_data['Low'].iloc[-1]

            # 简化Spring检测：接近最低点后反弹
            if recent_low <= low * 1.02:
                recent_close = recent_data['Close'].iloc[-1]
                if recent_close > recent_data['Open'].iloc[-1]:
                    has_spring = True

            # 检测SOS（放量突破）
            recent_data['Volume_MA'] = recent_data['Volume'].rolling(5).mean()
            latest_vol_ratio = recent_data['Volume'].iloc[-1] / recent_data['Volume_MA'].iloc[-1]

            if latest_vol_ratio > 1.3:
                price_change = (recent_data['Close'].iloc[-1] - recent_data['Close'].iloc[-2]) / recent_data['Close'].iloc[-2]
                if price_change > 0.03:
                    has_sos = True

            # 检测Upthrust（假突破）
            recent_high = recent_data['High'].max()
            if recent_data['High'].iloc[-1] >= recent_high * 0.98:
                if recent_data['Close'].iloc[-1] < recent_data['Open'].iloc[-1]:
                    has_upthrust = True

            return {
                'has_spring': has_spring,
                'has_sos': has_sos,
                'has_upthrust': has_upthrust,
                'timeframe': timeframe,
                'data_points': len(resampled)
            }

        except Exception as e:
            logger.exception(f"Error checking {timeframe} signal resonance: {e}")
            return {'error': str(e)}

    def _get_resonance_trading_recommendation(self, resonance_level: str, daily_analysis: Dict) -> Dict:
        """
        根据共振等级提供交易建议
        """
        phase = daily_analysis.get('phase', '')
        confidence = daily_analysis.get('confidence', 0.0)

        if resonance_level == 'strong_resonance':
            if 'Accumulation' in phase or 'Markup' in phase:
                return {
                    'action': 'strong_buy',
                    'position_size': 'aggressive',
                    'reason': f'多时间框架强烈共振 + {phase}，可考虑积极建仓'
                }
            else:
                return {
                    'action': 'strong_sell',
                    'position_size': 'aggressive',
                    'reason': f'多时间框架强烈共振 + {phase}，可考虑积极做空'
                }

        elif resonance_level == 'moderate_resonance':
            if 'Accumulation' in phase or 'Markup' in phase:
                return {
                    'action': 'moderate_buy',
                    'position_size': 'moderate',
                    'reason': f'多时间框架中等共振 + {phase}，可考虑适度建仓'
                }
            else:
                return {
                    'action': 'moderate_sell',
                    'position_size': 'moderate',
                    'reason': f'多时间框架中等共振 + {phase}，可考虑适度做空'
                }

        elif resonance_level == 'weak_resonance':
            return {
                'action': 'wait_or_small_position',
                'position_size': 'conservative',
                'reason': '多时间框架共振较弱，建议观望或轻仓试探'
            }

        else:  # no_resonance
            return {
                'action': 'avoid',
                'position_size': 'none',
                'reason': '多时间框架无共振，建议暂时观望'
            }

    def identify_phase_with_rs(self) -> Dict:
        """结合相对强度的阶段识别"""
        benchmark_symbol = self._get_baseline_index_symbol()
        rs_data = self._calculate_relative_strength(benchmark_symbol)
        
        base_phase = self.identify_phase_multi_timeframe()
        confidence = base_phase['confidence']
        
        if rs_data['rs_trend'] == 'rising':
            if 'Accumulation' in base_phase['phase'] or 'Markup' in base_phase['phase']:
                confidence *= 1.15
            elif 'Distribution' in base_phase['phase'] or 'Markdown' in base_phase['phase']:
                confidence *= 0.75
        elif rs_data['rs_trend'] == 'falling':
            if 'Distribution' in base_phase['phase'] or 'Markdown' in base_phase['phase']:
                confidence *= 1.15
            elif 'Accumulation' in base_phase['phase'] or 'Markup' in base_phase['phase']:
                confidence *= 0.75
                
        base_phase['relative_strength'] = rs_data
        base_phase['confidence'] = min(confidence, 1.0)
        return base_phase

    def _calculate_relative_strength(self, benchmark_symbol: str) -> Dict:
        """计算相对强度"""
        try:
            # 若基准就是大盘指数，直接用缓存
            if benchmark_symbol == self._get_baseline_index_symbol():
                benchmark_analyzer = self._get_cached_index_analyzer()
            else:
                benchmark_analyzer = WyckoffAnalyzer(benchmark_symbol, period=self.period, config=self.config)
                if not benchmark_analyzer.fetch_data():
                    return {'rs_trend': 'unknown', 'rs_value': None}
                
            common_dates = self.data.index.intersection(benchmark_analyzer.data.index)
            stock_data = self.data.loc[common_dates]
            benchmark_data = benchmark_analyzer.data.loc[common_dates]
            
            rs = stock_data['Close'] / benchmark_data['Close']
            rs_ma20 = rs.rolling(20).mean()
            rs_ma50 = rs.rolling(50).mean()
            
            if rs_ma20.iloc[-1] > rs_ma50.iloc[-1]: rs_trend = 'rising'
            elif rs_ma20.iloc[-1] < rs_ma50.iloc[-1]: rs_trend = 'falling'
            else: rs_trend = 'flat'
            
            rs_change = (rs.iloc[-1] / rs.iloc[-20] - 1) * 100 if len(rs) > 20 else 0
            
            return {
                'benchmark_used': benchmark_symbol,
                'rs_value': rs.iloc[-1],
                'rs_ma20': rs_ma20.iloc[-1],
                'rs_ma50': rs_ma50.iloc[-1],
                'rs_trend': rs_trend,
                'rs_change_20d': rs_change
            }
        except Exception:
            return {'rs_trend': 'unknown', 'rs_value': None}


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
            return {'error': '无法识别有效的交易区间'}

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
    # Wyckoff三大定律完整实现
    # ============================================================




    # ============================================================
    # Wyckoff分析的辅助函数
    # ============================================================














# ============================================================
# 批量扫描功能
# ============================================================

def batch_scan(symbols: List[str], period: str = "1y", use_json: bool = False,
               max_workers: int = None, show_progress: bool = True) -> List[Dict]:
    """
    批量扫描股票 - 增强版
    增强特性：
    - 并行处理支持（使用ThreadPoolExecutor）
    - 进度显示
    - 改进的异常处理和错误恢复
    - 更好的内存管理

    Args:
        symbols: 股票代码列表
        period: 数据周期
        use_json: True 则完整解析 JSON 输出（较慢），False 则仅提取摘要
        max_workers: 最大并行工作线程数，默认为CPU核心数
        show_progress: 是否显示进度条

    Returns:
        扫描结果列表，每项包含 symbol / phase / strength / signals
    """
    import concurrent.futures
    from tqdm import tqdm
    import os

    # 自动确定最大工作线程数
    if max_workers is None:
        max_workers = min(os.cpu_count() or 4, 8)  # 最多8个线程

    results = []
    failed_symbols = []

    def scan_single_symbol(symbol: str) -> Dict:
        """扫描单个股票的内部函数"""
        try:
            analyzer = WyckoffAnalyzer(symbol, period)

            data = analyzer.fetch_data()
            if data is None or (isinstance(data, pd.DataFrame) and data.empty):
                logger.warning("batch_scan: 获取数据失败 symbol=%s", symbol)
                return {'error': 'data_fetch_failed', 'symbol': symbol}

            # 从 identify_phase 结果中提取事件，避免重复计算
            phase_res = analyzer.identify_phase()
            events = phase_res.get('events_detected', {})

            phase_str = (phase_res.get('phase') or 'Unknown') if isinstance(phase_res, dict) else str(phase_res)

            # 从 events 中提取各信号检测结果
            spring_upthrust = events.get('spring_upthrust') or {}
            sos_sow = events.get('sos_sow') or {}
            lps_lpsy = events.get('lps_lpsy') or {}

            has_spring = spring_upthrust.get('detected', False) and spring_upthrust.get('_type') == 'spring'
            has_upthrust = spring_upthrust.get('detected', False) and spring_upthrust.get('_type') == 'upthrust'
            has_sos = sos_sow.get('detected', False) and sos_sow.get('_type') == 'sos'
            has_sow = sos_sow.get('detected', False) and sos_sow.get('_type') == 'sow'
            has_lps = lps_lpsy.get('detected', False) and lps_lpsy.get('_type') == 'lps'
            has_lpsy = lps_lpsy.get('detected', False) and lps_lpsy.get('_type') == 'lpsy'

            # 信号强度：各项汇总，最高 6 分
            strength = sum([has_spring, has_upthrust, has_sos, has_sow, has_lps, has_lpsy])

            return {
                'symbol':       symbol,
                'phase':        phase_str,
                'confidence':   round((phase_res.get('confidence') or 0.0) if isinstance(phase_res, dict) else 0.0, 2),
                'has_spring':   has_spring,
                'has_upthrust': has_upthrust,
                'has_sos':      has_sos,
                'has_sow':      has_sow,
                'has_lps':      has_lps,
                'has_lpsy':     has_lpsy,
                'strength':     strength,
            }

        except Exception as exc:
            logger.exception("batch_scan exception for symbol=%s: %s", symbol, exc)
            return {'error': str(exc), 'symbol': symbol}

    # 并行扫描所有股票
    if show_progress:
        print(f"[PARALLEL] 开始并行扫描 {len(symbols)} 只股票 (使用 {max_workers} 线程)...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 使用tqdm显示进度条
        futures = {executor.submit(scan_single_symbol, symbol): symbol for symbol in symbols}

        for future in tqdm(concurrent.futures.as_completed(futures),
                          total=len(symbols),
                          desc="扫描进度",
                          disable=not show_progress):
            result = future.result()
            if 'error' not in result:
                results.append(result)

                # 显示找到信号的股票
                if result['strength'] >= 1:
                    icons = []
                    if result['has_spring']:   icons.append('Spring')
                    if result['has_lps']:      icons.append('LPS')
                    if result['has_upthrust']: icons.append('Upthrust')
                    if result['has_lpsy']:     icons.append('LPSY')
                    if result['has_sos']:      icons.append('SOS')
                    if result['has_sow']:      icons.append('SOW')

                    print(f"  [OK] {result['symbol']}: [{result['phase']}] {' | '.join(icons)} (强度{result['strength']}/6)")
            else:
                failed_symbols.append(result.get('symbol', 'unknown'))

    # 显示统计信息
    if show_progress:
        print(f"\n[SUMMARY] 扫描完成:")
        print(f"  成功: {len(results)}/{len(symbols)}")
        if failed_symbols:
            print(f"  失败: {len(failed_symbols)} ({', '.join(failed_symbols[:5])}{'...' if len(failed_symbols) > 5 else ''})")

        # 按信号强度排序
        top_signals = sorted(results, key=lambda x: x['strength'], reverse=True)[:5]
        if top_signals and top_signals[0]['strength'] > 0:
            print(f"\n[TOP] 信号强度 TOP 5:")
            for i, stock in enumerate(top_signals, 1):
                print(f"  {i}. {stock['symbol']} - {stock['phase']} (强度{stock['strength']}/6)")

    return results


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
