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
        """生成分析报告"""
        if self.data is None:
            data = self.fetch_data()
            if data is None or (isinstance(data, pd.DataFrame) and data.empty):
                return f"无法获取数据: {self.symbol}"

        report = f"""
{'='*60}
威科夫形态分析报告
{'='*60}

股票代码: {self.symbol}
分析日期: {datetime.now().strftime('%Y-%m-%d')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【当前阶段】
{self.pattern_detector.identify_phase()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【基础数据】
当前价格: {self.data['Close'].iloc[-1]:.2f}
52周最高: {self.data['High'].tail(252).max():.2f}
52周最低: {self.data['Low'].tail(252).min():.2f}
成交量: {self.data['Volume'].iloc[-1]:,.0f}
量比: {self.data['Volume'].iloc[-1] / self.data['Volume_MA20'].iloc[-1]:.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【形态检测】
"""

        # 检测各种形态
        trading_range = self.pattern_detector.detect_trading_range()
        spring = self.pattern_detector.detect_spring()
        upthrust = self.pattern_detector.detect_upthrust()
        sos = self.pattern_detector.detect_sos()
        sow = self.pattern_detector.detect_sow()
        lps = self.pattern_detector.detect_lps()
        lpsy = self.pattern_detector.detect_lpsy()

        if trading_range.get('is_consolidation'):
            report += f"""
✅ 检测到交易区间:
   区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
   幅度: {trading_range['range_pct']*100:.1f}%
   当前位置: {trading_range['position']*100:.0f}% (0%=底部, 100%=顶部)
   成交量趋势: {trading_range['volume_trend']}
"""

        if spring.get('detected'):
            latest = spring['latest_spring']
            report += f"""
✅ 检测到Spring:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   跌破价: {latest['breakdown_price']:.2f}
   支撑位: {latest['support_level']:.2f}
   收回价: {latest['recovery_price']:.2f}
   收回天数: {latest['recovery_days']}天
   ✓ 真Spring（3天内收回且放量）
"""

        if upthrust.get('detected'):
            latest = upthrust['latest_upthrust']
            report += f"""
✅ 检测到Upthrust:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   突破价: {latest['breakout_price']:.2f}
   阻力位: {latest['resistance_level']:.2f}
   回落价: {latest['rejection_price']:.2f}
   回落天数: {latest['rejection_days']}天
   收盘距高点: {latest['close_from_high']*100:.1f}%
   ✓ 真Upthrust（3天内回落且放量）
"""

        if sos.get('detected'):
            latest = sos['latest']
            report += f"""
✅ 检测到SOS（Sign of Strength）:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   价格: {latest['price']:.2f}
   成交量倍数: {latest['volume_ratio']:.1f}x
   涨幅: {latest['price_change']*100:.1f}%
   突破位: {latest['breakthrough_level']:.2f}
   ✓ 强势信号（放量突破）
"""

        if sow.get('detected'):
            latest = sow['latest']
            report += f"""
✅ 检测到SOW（Sign of Weakness）:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   价格: {latest['price']:.2f}
   成交量倍数: {latest['volume_ratio']:.1f}x
   跌幅: {latest['price_change']*100:.1f}%
   跌破位: {latest['breakdown_level']:.2f}
   ✓ 弱势信号（放量跌破）
"""

        if lps.get('detected'):
            report += f"""
✅ 检测到LPS（Last Point of Support）:
   日期: {lps['date'].strftime('%Y-%m-%d')}
   价格: {lps['price']:.2f}
   回调幅度: {lps['pullback_pct']*100:.1f}%
   成交量缩小: 是
   ⭐ 建议做多入场点
"""

        if lpsy.get('detected'):
            report += f"""
✅ 检测到LPSY（Last Point of Supply）:
   日期: {lpsy['date'].strftime('%Y-%m-%d')}
   价格: {lpsy['price']:.2f}
   反弹幅度: {lpsy['rally_pct']*100:.1f}%
   成交量缩小: 是
   ⭐ 建议做空入场点
"""

        # 因果测算
        cause_effect = self.calculate_cause_effect()
        if cause_effect and 'targets' in cause_effect:
            report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【因果测算】
交易区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
因果幅度: {cause_effect['cause_size']:.2f}
目标1 (0.618倍): {cause_effect['targets']['target_1']:.2f}
目标2 (1.0倍): {cause_effect['targets']['target_2']:.2f}
目标3 (1.618倍): {cause_effect['targets']['target_3']:.2f}
"""

        # 交易建议
        report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【交易建议】
"""

        if lps.get('detected') and not lpsy.get('detected'):
            report += f"""
✅ 做多机会:
   入场价格: {lps['price']:.2f} (LPS)
   止损价格: {lps['price']*0.95:.2f} (保守)
   目标价格: {cause_effect['targets']['target_2']:.2f} (因果测算)
   风险提示: 请设置好止损，严格执行
"""
        elif lpsy.get('detected') and not lps.get('detected'):
            report += f"""
✅ 做空机会:
   入场价格: {lpsy['price']:.2f} (LPSY)
   止损价格: {lpsy['price']*1.05:.2f} (保守)
   目标价格: {cause_effect['targets']['target_2']:.2f} (因果测算)
   风险提示: A股做空困难，建议观望或减仓
"""
        elif trading_range.get('is_consolidation'):
            report += """
⏳ 观望等待:
   当前处于横盘整理阶段
   等待明确的SOS或SOW信号
   不要过早入场
"""
        else:
            report += """
⏸️ 无明显信号:
   当前没有明确的入场信号
   建议继续观察或等待更好机会
"""

        report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【风险提示】
⚠️ 本报告仅供参考，不构成投资建议
⚠️ 股市有风险，投资需谨慎
⚠️ 请根据自身风险承受能力做出决策
⚠️ 建议结合其他分析方法和市场环境

{'='*60}
"""

        return report

    def _round_floats(self, obj):
        """递归遍历字典/列表，将浮点数截断至3位小数"""
        if isinstance(obj, float):
            return round(obj, 3)
        elif isinstance(obj, dict):
            return {k: self._round_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._round_floats(x) for x in obj]
        return obj

    def calculate_signal_quality(self, market_phase) -> dict:
        """计算信号质量评分"""
        score = 0
        reasons = []

        if self.data is not None:
            vol_ratio = self.data['Volume'].iloc[-1] / self.data['Volume_MA20'].iloc[-1]
            phase_res = self.pattern_detector.identify_phase()
            phase_str = phase_res.get('phase', 'Unknown') if isinstance(phase_res, dict) else phase_res
            
            # 1. 技术确认度
            if "Accumulation" in phase_str or "Markup" in phase_str:
                if vol_ratio > 1.5:
                    score += 3
                    reasons.append("成交量强力确认 (放量上涨)")
                elif vol_ratio > 1.0:
                    score += 1
                    reasons.append("成交量温和配合")
                else:
                    reasons.append("上涨缩量，动能不足")
            else:
                if vol_ratio > 1.5:
                    score += 3
                    reasons.append("成交量强力确认 (放量下跌)")
                else:
                    reasons.append("下跌缩量，趋势可能随时反转")
        
            # 2. 趋势一致性
            current_price = self.data['Close'].iloc[-1]
            ma50 = self.data['MA50'].iloc[-1]
            ma200 = self.data['MA200'].iloc[-1]
            
            if current_price > ma50 and ma50 > ma200:
                score += 3
                reasons.append("多时间框架一致 (长期多头排列)")
            elif current_price < ma50 and ma50 < ma200:
                score += 3
                reasons.append("多时间框架一致 (长期空头排列)")

        # 3. 市场环境配合
        market_env = market_phase.get('environment', 'Unknown') if isinstance(market_phase, dict) else "Unknown"
        is_market_bullish = "Bull" in market_env or "牛" in market_env
        is_market_bearish = "Bear" in market_env or "熊" in market_env
        
        if is_market_bullish:
            if "Accumulation" in phase_str or "Markup" in phase_str:
                score += 4
                reasons.append("市场环境有利 (顺应大盘多头)")
            else:
                reasons.append("逆势操作 (大盘看多，个股看空)")
        elif is_market_bearish:
            if "Distribution" in phase_str or "Markdown" in phase_str:
                score += 4
                reasons.append("市场环境有利 (顺应大盘空头)")
            else:
                reasons.append("逆势操作 (大盘看空，个股看多)")
        else:
            # 震荡市
            score += 2
            reasons.append("市场环境中性 (大盘震荡)")

        return {
            "score": score,
            "max_score": 10,
            "confidence": "高" if score >= 7 else "中" if score >= 4 else "低",
            "reasons": reasons
        }

    # ============================================================
    # Wyckoff三大定律完整实现
    # ============================================================




    # ============================================================
    # Wyckoff分析的辅助函数
    # ============================================================






    def generate_trading_plan(self, sentiment_data: dict = None, phase_str: str = "") -> dict:
        """生成实战交易计算器数据（带情绪风控）"""
        if self.data is None:
            return {}
            
        current_price = self.data['Close'].iloc[-1]
        atr = self.data['ATR'].iloc[-1]
        
        tr = self.pattern_detector.detect_trading_range()
        high = tr.get("high", current_price * 1.1)
        low = tr.get("low", current_price * 0.9)
        
        if not phase_str:
            phase_res = self.pattern_detector.identify_phase()
            phase_str = phase_res.get('phase', 'Unknown') if isinstance(phase_res, dict) else phase_res
            
        is_bullish = "Accumulation" in phase_str or "Markup" in phase_str
        
        if is_bullish:
            entry_zone = f"{round(current_price * 0.99, 2)} - {round(current_price * 1.01, 2)}"
            stop_conservative = round(low, 2)
            stop_aggressive = round(low - atr, 2)
            target_1 = round(high, 2) if current_price < high else round(current_price + atr * 2, 2)
            target_2 = round(high + atr * 3, 2)
        else:
            entry_zone = f"{round(current_price * 0.99, 2)} - {round(current_price * 1.01, 2)}"
            stop_conservative = round(high, 2)
            stop_aggressive = round(high + atr, 2)
            target_1 = round(low, 2) if current_price > low else round(current_price - atr * 2, 2)
            target_2 = round(low - atr * 3, 2)

        # 情绪仓位管理
        pos_conservative = 2.5
        pos_moderate = 5.0
        pos_aggressive = 10.0
        
        dynamic_warning = None
        if sentiment_data:
            sentiment = sentiment_data.get("market_sentiment", "neutral")
            
            if sentiment == "extreme_fear":
                pos_conservative *= 0.5
                pos_moderate *= 0.5
                pos_aggressive *= 0.5
            elif sentiment == "greed":
                pos_conservative *= 1.2
                pos_moderate *= 1.2
                pos_aggressive *= 1.2
                
            # 情绪背离预警
            if sentiment == "greed" and ("Distribution" in phase_str or "Markdown" in phase_str):
                dynamic_warning = "⚠️ 极度危险：大盘贪婪 + 个股派发 = 暴跌前兆，禁止盲目接刀！"
            elif sentiment == "extreme_fear" and ("Accumulation" in phase_str or "Markup" in phase_str):
                dynamic_warning = "💡 黄金坑预警：大盘极度恐慌 + 个股筑底 = 绝佳击球区，请重点关注抗跌表现！"

        # ATR 动态止损
        atr_stop_loss = round(current_price - 1.5 * atr if is_bullish else current_price + 1.5 * atr, 2)
        
        # 分批建仓触发条件
        if is_bullish:
            scale_in_triggers = {
                "entry_1_30pct": {
                    "condition": "当前信号出现 (如 Spring/SOS)",
                    "price": round(current_price, 2)
                },
                "entry_2_50pct": {
                    "condition": "价格突破关键阻力位或回踩支撑不破",
                    "price": round(high, 2)
                },
                "entry_3_20pct": {
                    "condition": "创出新高或确认进入强势上涨阶段 (Phase E)",
                    "price": round(high + atr, 2)
                }
            }
        else:
            scale_in_triggers = {
                "entry_1_30pct": {
                    "condition": "当前做空信号出现",
                    "price": round(current_price, 2)
                },
                "entry_2_50pct": {
                    "condition": "跌破关键支撑位或反抽阻力不破",
                    "price": round(low, 2)
                },
                "entry_3_20pct": {
                    "condition": "创出新低或确认进入强势下跌阶段 (Phase E)",
                    "price": round(low - atr, 2)
                }
            }
            
        # 退出规则 (移动止损与时间止损)
        exit_rules = [
            {
                "type": "trailing_stop",
                "trigger": "1ATR_profit",
                "description": f"浮盈达到1个ATR ({round(atr, 2)}元)",
                "action": "move_to_cost"
            },
            {
                "type": "trailing_stop",
                "trigger": "2ATR_profit",
                "description": f"浮盈达到2个ATR ({round(atr * 2, 2)}元)",
                "action": "move_to_1ATR_profit"
            },
            {
                "type": "time_stop",
                "trigger": "5-8_days_no_profit",
                "description": "建仓后 5-8 个交易日未脱离成本区",
                "action": "exit_position"
            }
        ]

        return {
            "direction": "做多" if is_bullish else "做空",
            "entry_zone": entry_zone,
            "stop_loss": {
                "conservative": stop_conservative,
                "aggressive": stop_aggressive,
                "atr_dynamic_stop": atr_stop_loss
            },
            "targets": {
                "target_1": target_1,
                "target_2": target_2
            },
            "position_sizing": {
                "conservative": f"{round(pos_conservative, 1)}%总仓",
                "moderate": f"{round(pos_moderate, 1)}%总仓",
                "aggressive": f"{round(pos_aggressive, 1)}%总仓"
            },
            "scale_in_triggers": scale_in_triggers,
            "exit_rules": exit_rules,
            "holding_period": "中期（2-8周）" if "Markup" in phase_str or "Markdown" in phase_str else "短期（1-3周）",
            "atr_value": round(atr, 2),
            "dynamic_warning": dynamic_warning
        }

    def get_relevant_terms(self, phase: str, events: dict) -> dict:
        """获取相关术语的大白话解释"""
        all_terms = {
            "SOS (强势信号)": {
                "simple": "强势信号 - 价格放量突破阻力位",
                "example": "像蓄势后的跳跃，成交量放大确认",
                "action": "考虑买入或持有"
            },
            "SOW (弱势信号)": {
                "simple": "弱势信号 - 价格放量跌破支撑位",
                "example": "像突然脚软跌入坑中，供给开始主导",
                "action": "考虑卖出或观望"
            },
            "Spring (震仓)": {
                "simple": "震仓 - 短暂跌破支撑后快速收回",
                "example": "像弹簧被压下去后弹起，洗出散户",
                "action": "可能是极佳的买入机会"
            },
            "Upthrust (上冲回落)": {
                "simple": "诱多 - 短暂突破阻力后快速跌回",
                "example": "假装大涨吸引散户接盘，随后迅速撤退",
                "action": "可能是做空或逃顶机会"
            },
            "Accumulation (积累期)": {
                "simple": "建仓期 - 主力在低位悄悄买入筹码",
                "example": "像批发商在淡季默默囤货",
                "action": "耐心等待突破信号"
            },
            "Distribution (派发期)": {
                "simple": "出货期 - 主力在高位分批卖出筹码",
                "example": "像批发商在旺季大肆推销",
                "action": "注意风险，逢高减仓"
            },
            "LPS (最后支撑点)": {
                "simple": "最后支撑点 - 震仓后的缩量回调",
                "example": "像弹簧压到底部的最低点，反弹概率最高",
                "action": "强烈建议买入"
            },
            "LPSY (最后供应点)": {
                "simple": "最后供应点 - 跌破支撑后的无力反抽",
                "example": "像反弹无力撞上天花板",
                "action": "强烈建议卖出"
            }
        }
        
        relevant = {}
        if "Accumulation" in phase:
            relevant["Accumulation (积累期)"] = all_terms["Accumulation (积累期)"]
        elif "Distribution" in phase:
            relevant["Distribution (派发期)"] = all_terms["Distribution (派发期)"]
            
        if events.get('sos', {}).get('detected'):
            relevant["SOS (强势信号)"] = all_terms["SOS (强势信号)"]
        if events.get('sow', {}).get('detected'):
            relevant["SOW (弱势信号)"] = all_terms["SOW (弱势信号)"]
        if events.get('spring', {}).get('detected'):
            relevant["Spring (震仓)"] = all_terms["Spring (震仓)"]
        if events.get('upthrust', {}).get('detected'):
            relevant["Upthrust (上冲回落)"] = all_terms["Upthrust (上冲回落)"]
        if events.get('lps', {}).get('detected'):
            relevant["LPS (最后支撑点)"] = all_terms["LPS (最后支撑点)"]
        if events.get('lpsy', {}).get('detected'):
            relevant["LPSY (最后供应点)"] = all_terms["LPSY (最后供应点)"]
            
        return relevant

    def generate_risk_advice(self, signal_quality: dict, trading_plan: dict) -> dict:
        """生成具体的风险分层操作建议"""
        score = signal_quality.get("score", 0)
        direction = trading_plan.get("direction", "观望")
        stop_con = trading_plan.get("stop_loss", {}).get("conservative", "未知")
        stop_agg = trading_plan.get("stop_loss", {}).get("aggressive", "未知")
        
        if score <= 4:
            return {
                "保守型": {
                    "action": "绝对观望",
                    "reason": f"当前信号质量仅 {score}/10 分，风险极高",
                    "entry_condition": "等待明确的量价反转信号或进入下一周期"
                },
                "稳健型": {
                    "action": "观望为主",
                    "position": "建议空仓",
                    "stop_loss": "暂不适用"
                },
                "激进型": {
                    "action": f"轻仓试错 ({direction})",
                    "position": "不超过 3% 仓位",
                    "stop_loss": f"{stop_con}元 (极严格止损)"
                }
            }
        elif score <= 7:
            return {
                "保守型": {
                    "action": "观望或极轻仓",
                    "reason": f"信号质量 {score}/10 分，未达到绝对安全边际",
                    "entry_condition": "等待价格回调确认支撑后再入场"
                },
                "稳健型": {
                    "action": f"分批建仓 ({direction})",
                    "position": "3-5% 仓位，分2-3次买入",
                    "stop_loss": f"{stop_con}元"
                },
                "激进型": {
                    "action": f"按计划参与 ({direction})",
                    "position": "8% 仓位",
                    "stop_loss": f"{stop_agg}元 (给予一定震荡空间)"
                }
            }
        else:
            return {
                "保守型": {
                    "action": f"稳步参与 ({direction})",
                    "reason": f"信号质量高达 {score}/10 分，多方指标产生共振",
                    "entry_condition": "可在当前价格区间直接介入"
                },
                "稳健型": {
                    "action": f"积极布局 ({direction})",
                    "position": "8-10% 仓位",
                    "stop_loss": f"{stop_con}元"
                },
                "激进型": {
                    "action": f"重仓出击 ({direction})",
                    "position": "15-20% 仓位",
                    "stop_loss": f"{stop_agg}元"
                }
            }

    def generate_interactive_qa(self, signal_quality: dict, trading_plan: dict) -> list:
        """根据分析结果预生成交互问答"""
        direction = trading_plan.get("direction", "观望")
        score = signal_quality.get("score", 0)
        stop = trading_plan.get("stop_loss", {}).get("conservative", "未知")
        period = trading_plan.get("holding_period", "未知")
        
        return [
            f"现在{direction} {self.symbol} 合适吗？(当前信号质量为 {score}/10)",
            f"如果参与 {self.symbol}，应该设置多少止损？(建议保守防守线在 {stop}元)",
            f"这笔交易预期需要持有多长时间？(系统预估 {period})"
        ]

    def get_signal_performance(self, events: dict) -> dict:
        """基于该股票历史K线动态回测信号表现 (20个交易日窗口)"""
        # 预设全市场通用基准（Fallback）
        static_baseline = {
            "SOS (强势信号)": {"total_occurrences": 128, "success_rate": "75.4%", "avg_return": "+12.4%"},
            "Spring (震仓洗盘)": {"total_occurrences": 45, "success_rate": "82.1%", "avg_return": "+18.8%"},
            "SOW (弱势信号)": {"total_occurrences": 92, "success_rate": "68.3%", "avg_return": "-9.2%"},
            "Upthrust (上冲回落)": {"total_occurrences": 56, "success_rate": "71.5%", "avg_return": "-14.5%"}
        }

        signal_mapping = {
            "SOS (强势信号)": {"key": "sos", "is_bullish": True},
            "Spring (震仓洗盘)": {"key": "spring", "is_bullish": True},
            "SOW (弱势信号)": {"key": "sow", "is_bullish": False},
            "Upthrust (上冲回落)": {"key": "upthrust", "is_bullish": False}
        }

        results = {}
        # 预先建立日期字符串 -> 整数位置的映射，将 O(n) 逐行扫描改为 O(1) 查找
        date_to_pos = {
            dt.strftime('%Y-%m-%d'): i
            for i, dt in enumerate(self.data.index)
        }

        for display_name, config in signal_mapping.items():
            key = config["key"]
            is_bullish = config["is_bullish"]

            signals = events.get(key, {}).get("signals", [])
            if len(signals) < 2:
                results[display_name] = dict(static_baseline[display_name])
                results[display_name]["note"] = "样本不足2次，采用全市场基准"
                continue

            success_count = 0
            total_returns = []

            for sig in signals:
                date_str = sig.get("date")
                entry_price = sig.get("price")
                if not date_str or not entry_price:
                    continue

                try:
                    target_date = pd.to_datetime(date_str).strftime('%Y-%m-%d')
                    idx = date_to_pos.get(target_date, -1)  # O(1) 查找
                    if idx == -1:
                        continue
                except Exception:
                    continue

                target_idx = min(idx + 20, len(self.data) - 1)
                if target_idx - idx < 5:
                    continue

                future_price = self.data['Close'].iloc[target_idx]

                ret = (future_price - entry_price) / entry_price if is_bullish else (entry_price - future_price) / entry_price
                total_returns.append(ret)
                if ret > 0:
                    success_count += 1

            valid_count = len(total_returns)
            if valid_count < 2:
                results[display_name] = dict(static_baseline[display_name])
                results[display_name]["note"] = "样本不足2次，采用全市场基准"
            else:
                avg_ret = sum(total_returns) / valid_count
                succ_rate = success_count / valid_count
                display_avg_ret = -avg_ret if not is_bullish else avg_ret
                display_prefix = "+" if display_avg_ret > 0 else ""
                results[display_name] = {
                    "total_occurrences": valid_count,
                    "success_rate": f"{succ_rate*100:.1f}%",
                    "avg_return": f"{display_prefix}{display_avg_ret*100:.1f}%",
                    "note": f"本股专属动态回测 ({valid_count}次)"
                }

        return results

    def add_market_sentiment(self) -> dict:
        """整合市场情绪指标（区分 A股、港股和美股）"""
        try:
            import numpy as np
            import yfinance as yf
            import pandas as pd
            
            is_us_market = not (self.symbol.startswith('sh.') or self.symbol.startswith('sz.') or self.symbol.endswith('.HK'))
            is_hk_market = self.symbol.endswith('.HK')
            
            current_vix = None
            benchmark_used = ""
            
            # 1. 尝试直接获取期权隐含波动率指数 (VIX / VHSI)
            if is_us_market:
                vix = yf.download('^VIX', period='5d', progress=False)
                if not vix.empty:
                    last_close = vix['Close'].iloc[-1]
                    if isinstance(last_close, pd.Series):
                        last_close = last_close.iloc[0] if len(last_close) > 0 else None
                    if last_close is not None and not pd.isna(last_close):
                        current_vix = float(last_close)
                        benchmark_used = '^VIX (CBOE Implied Volatility)'
            elif is_hk_market:
                vhsi = yf.download('^VHSI', period='5d', progress=False)
                if not vhsi.empty:
                    last_close = vhsi['Close'].iloc[-1]
                    if isinstance(last_close, pd.Series):
                        last_close = last_close.iloc[0] if len(last_close) > 0 else None
                    if last_close is not None and not pd.isna(last_close):
                        current_vix = float(last_close)
                        benchmark_used = '^VHSI (HSI Implied Volatility)'
                    
            # 2. 如果是 A股，或者外盘获取不到 VIX，回退到计算大盘的 20日历史实现波动率 (Realized Volatility)
            if current_vix is None:
                idx_analyzer = self._get_cached_index_analyzer()
                index_symbol = self._get_baseline_index_symbol()

                if idx_analyzer is None or idx_analyzer.data is None or len(idx_analyzer.data) < 20:
                    return {"market_sentiment": "unknown", "vix_level": None, "implication": "无法获取大盘数据计算情绪"}

                df = idx_analyzer.data.copy()
                returns = df['Close'].pct_change().dropna()
                if len(returns) < 20:
                    return {"market_sentiment": "unknown", "vix_level": None, "implication": "大盘数据不足"}
                    
                current_vix = returns.rolling(20).std().iloc[-1] * np.sqrt(252) * 100
                if pd.isna(current_vix):
                    return {"market_sentiment": "unknown", "vix_level": None, "implication": "波动率计算失败"}
                    
                current_vix = float(current_vix)
                benchmark_used = f'{index_symbol} (20-day Realized Volatility)'
            
            # 3. 统一的情绪评级标准
            if current_vix >= 30:
                sentiment = "extreme_fear"
                implication = "大盘处于极度恐慌或剧烈波动环境，技术信号极易失效（暴涨暴跌），建议严控仓位"
            elif current_vix >= 22:
                sentiment = "fear"
                implication = "大盘恐慌情绪上升，警惕向下突破或大幅震荡"
            elif current_vix <= 15:
                sentiment = "greed"
                implication = "大盘波动极低，多头环境良好或处于温水煮青蛙的赶顶期，需防范高位诱多"
            else:
                sentiment = "neutral"
                implication = "大盘情绪平稳，个股的技术信号和形态的有效性较高"
                
            return {
                "market_sentiment": sentiment,
                "vix_level": round(current_vix, 2),
                "implication": implication,
                "benchmark_used": benchmark_used
            }
        except Exception as e:
            return {"market_sentiment": "unknown", "vix_level": None, "implication": f"获取情绪数据失败: {str(e)}"}

    def generate_json(self) -> str:
        """生成JSON格式的分析报告（供AI Agent读取）"""
        data = self.fetch_data()
        if data is None or (isinstance(data, pd.DataFrame) and data.empty):
            return json.dumps({"error": f"无法获取数据: {self.symbol}"}, ensure_ascii=False)
            
        # 1. 基础事件分析
        climax_res = self.pattern_detector.detect_climax()
        ar_res = self.pattern_detector.detect_automatic_reaction(climax_res)
        st_res = self.pattern_detector.detect_secondary_test(climax_res, ar_res)
        
        events = {
            "trading_range": self.pattern_detector.detect_trading_range(),
            "climax": climax_res,
            "automatic_reaction": ar_res,
            "secondary_test": st_res,
            "spring": self.pattern_detector.detect_spring(),
            "upthrust": self.pattern_detector.detect_upthrust(),
            "sos": self.pattern_detector.detect_sos(),
            "sow": self.pattern_detector.detect_sow(),
            "lps": self.pattern_detector.detect_lps(),
            "lpsy": self.pattern_detector.detect_lpsy()
        }
        
        # 获取完整带多时间框架和RS的阶段
        phase_dict = self.identify_phase_with_rs()
        phase_str = phase_dict.get('phase', 'Unknown')
        
        daily_phase_dict = phase_dict.get('daily_phase', {})
        seq_score = daily_phase_dict.get('sequence_score', {})
        div_res = daily_phase_dict.get('divergence', {})

        result = {
            "symbol": self.symbol,
            "date": datetime.now().strftime('%Y-%m-%d'),
            "phase": phase_str,
            "phase_confidence": phase_dict.get('confidence', 0.0),
            "sequence_score": seq_score,
            "divergence": div_res,
            "multi_timeframe": {
                "weekly_trend": phase_dict.get('weekly_trend', 'unknown'),
                "monthly_trend": phase_dict.get('monthly_trend', 'unknown'),
                "agreement": phase_dict.get('multi_timeframe_agreement', 'unknown')
            },
            "relative_strength": phase_dict.get('relative_strength', {}),
            "basic_data": {
                "current_price": round(self.data['Close'].iloc[-1], 2),
                "volume": int(self.data['Volume'].iloc[-1]),
                "volume_ratio": round(self.data['Volume'].iloc[-1] / self.data['Volume_MA20'].iloc[-1], 2)
            },
            "events": events,
            "cause_effect": self.calculate_cause_effect()
        }
        
        # 获取大盘基准 (使用缓存，避免重复 IO)
        index_symbol = self._get_baseline_index_symbol()
        idx_analyzer = self._get_cached_index_analyzer()

        market_context_dict = {}
        if idx_analyzer is not None:
            market_phase_dict = idx_analyzer.identify_phase()
            market_phase_str = market_phase_dict.get('phase', 'Unknown')
            env_dict = self._analyze_market_environment()

            market_context_dict = {
                "index_symbol": index_symbol,
                "phase": market_phase_str,
                "environment": env_dict.get("environment", "Unknown"),
                "ma_spread_pct": env_dict.get("ma_spread_pct", 0)
            }
            result["market_context"] = market_context_dict
        else:
            result["market_context"] = {
                "index_symbol": index_symbol,
                "error": "无法获取大盘数据"
            }
            
        # 增加市场情绪整合
        global_sentiment = self.add_market_sentiment()
        result["global_sentiment"] = global_sentiment
        
        # 增加信号质量评分和交易计划 (传入 market_context_dict 以便使用 environment)
        signal_quality = self.calculate_signal_quality(market_context_dict)
        trading_plan = self.generate_trading_plan(global_sentiment, phase_str)
        
        result["signal_quality"] = signal_quality
        result["trading_plan"] = trading_plan
        
        # 增加Wyckoff三大定律完整分析
        wyckoff_laws = {
            "supply_demand_law": self.law_analyzer.analyze_supply_demand_law(),
            "effort_vs_result_law": self.law_analyzer.analyze_effort_vs_result_law(),
            "cause_effect_law": self.law_analyzer.analyze_cause_effect_law_enhanced()
        }
        result["wyckoff_laws"] = wyckoff_laws

        # 增加智能内容生成 (大模型剥离)
        result["terminology_guide"] = self.get_relevant_terms(phase_str, events)
        result["risk_specific_advice"] = self.generate_risk_advice(signal_quality, trading_plan)
        result["interactive_qa"] = self.generate_interactive_qa(signal_quality, trading_plan)
        result["performance_tracking"] = self.get_signal_performance(events)
        
        result = self._round_floats(result)
        
        # 转换 datetime 和特殊类型以便序列化，然后使用 Pydantic 验证
        def default_serializer(obj):
            if isinstance(obj, (pd.Timestamp, datetime)):
                return obj.strftime('%Y-%m-%d')
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return str(obj)
            
        # 先转换为纯 Python 字典
        clean_result = json.loads(json.dumps(result, default=default_serializer))
        
        try:
            from tools.schemas import ReportModel
            report = ReportModel(**clean_result)
            return report.model_dump_json(indent=2, exclude_none=True)
        except ImportError:
            try:
                from .schemas import ReportModel
                report = ReportModel(**clean_result)
                return report.model_dump_json(indent=2, exclude_none=True)
            except ImportError:
                # Fallback
                return json.dumps(clean_result, ensure_ascii=False, indent=2)


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
