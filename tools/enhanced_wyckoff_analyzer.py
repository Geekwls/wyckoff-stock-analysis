#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强的威科夫分析系统
Enhanced Wyckoff Analysis System

实现了威科夫理论的第1-8项优化建议：
1. 阶段识别精度提升
2. 威科夫事件识别增强
3. 成交量分析增强
4. 因果定律量化
5. 交易时机精确化
6. 风险管理优化
7. A股市场特定优化
8. 多时间框架整合

性能优化：
- 向量化操作替代循环
- ATR自适应阈值
- 标准Volume Profile算法
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum, auto
from dataclasses import dataclass, field
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# 枚举类型定义
# ============================================================

class MarketPhase(Enum):
    """市场阶段枚举"""
    ACCUMULATION = auto()
    MARKUP = auto()
    DISTRIBUTION = auto()
    MARKDOWN = auto()
    UNKNOWN = auto()


class TradeDirection(Enum):
    """交易方向枚举"""
    LONG = auto()
    SHORT = auto()
    NEUTRAL = auto()


class SignalStrength(Enum):
    """信号强度枚举"""
    STRONG = auto()
    MODERATE = auto()
    WEAK = auto()


class RSStatus(Enum):
    """相对强度状态枚举"""
    STRONG = "Strong"
    IMPROVING = "Improving"
    NEUTRAL = "Neutral"
    DETERIORATING = "Deteriorating"
    WEAK = "Weak"


# ============================================================
# 配置类定义
# ============================================================

@dataclass
class WyckoffConfig:
    """威科夫分析配置类 - 统一管理所有参数"""

    # 阶段识别参数
    confidence_threshold: float = 0.85
    min_data_length: int = 60

    # ATR参数
    atr_period: int = 14
    atr_multiplier_spring: float = 1.5
    atr_multiplier_upthrust: float = 1.5
    atr_multiplier_stop_loss: float = 2.0

    # 成交量参数
    volume_climax_std_mult: float = 2.0
    volume_ma_short: int = 5
    volume_ma_long: int = 20

    # 趋势参数
    trend_lookback: int = 20
    adx_period: int = 14
    adx_threshold: float = 25.0

    # 价格区间参数
    consolidation_range_pct: float = 0.30  # 30%震荡区间
    breakout_threshold_pct: float = 0.02   # 2%突破确认

    # 价值区域参数
    value_area_pct: float = 0.70  # 70%成交量

    # A股特定参数
    a_share_price_limit: float = 0.10      # 主板涨跌停10%
    a_share_price_limit_kcb: float = 0.20  # 科创板/创业板涨跌停20%
    a_share_t_plus_one: bool = True        # T+1交易制度

    # 交易参数
    default_risk_per_trade: float = 0.02   # 每笔交易风险2%
    min_position_size: int = 100           # 最小交易单位

    @classmethod
    def from_dict(cls, config_dict: Dict) -> 'WyckoffConfig':
        """从字典创建配置"""
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# ============================================================
# ATR计算工具函数
# ============================================================

def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    计算ATR（Average True Range）

    Args:
        data: OHLC数据
        period: 计算周期

    Returns:
        ATR序列
    """
    high = pd.to_numeric(data['High'], errors='coerce')
    low = pd.to_numeric(data['Low'], errors='coerce')
    close = pd.to_numeric(data['Close'], errors='coerce').shift(1)

    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=1).mean()

    return pd.Series(atr, index=data.index, name='ATR')


def calculate_adx(data: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    计算ADX（Average Directional Index）

    Args:
        data: OHLC数据
        period: 计算周期

    Returns:
        包含ADX、+DI、-DI的DataFrame
    """
    high = pd.to_numeric(data['High'], errors='coerce')
    low = pd.to_numeric(data['Low'], errors='coerce')

    # 标准ADX算法：+DM = 当前高点 - 前高；-DM = 前低 - 当前低
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # 计算ATR，并防止除零
    atr = calculate_atr(data, period).replace(0, np.nan)

    # 计算+DI和-DI
    plus_di = 100 * (plus_dm.rolling(window=period, min_periods=1).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period, min_periods=1).mean() / atr)

    # 计算DX
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum

    # 计算ADX
    adx = dx.rolling(window=period, min_periods=1).mean()

    return pd.DataFrame({
        'ADX': adx.fillna(0),
        'Plus_DI': plus_di.fillna(0),
        'Minus_DI': minus_di.fillna(0)
    }, index=data.index)


def prepare_wyckoff_data(data: pd.DataFrame, config: Optional[WyckoffConfig] = None) -> pd.DataFrame:
    """
    统一预计算常用指标，避免各分析器重复 rolling 计算。

    预计算字段：MA20、MA50、MA200、Volume_MA5、Volume_MA20、Volume_MA60、ATR、ADX、Plus_DI、Minus_DI。
    """
    cfg = config or WyckoffConfig()
    prepared = data.copy()

    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in prepared.columns:
            prepared[col] = pd.to_numeric(prepared[col], errors='coerce')

    prepared = prepared.dropna(subset=['High', 'Low', 'Close', 'Volume'])

    if 'MA20' not in prepared.columns:
        prepared['MA20'] = prepared['Close'].rolling(20, min_periods=1).mean()
    if 'MA50' not in prepared.columns:
        prepared['MA50'] = prepared['Close'].rolling(50, min_periods=1).mean()
    if 'MA200' not in prepared.columns:
        prepared['MA200'] = prepared['Close'].rolling(200, min_periods=1).mean()
    if 'Volume_MA5' not in prepared.columns:
        prepared['Volume_MA5'] = prepared['Volume'].rolling(cfg.volume_ma_short, min_periods=1).mean()
    if 'Volume_MA20' not in prepared.columns:
        prepared['Volume_MA20'] = prepared['Volume'].rolling(cfg.volume_ma_long, min_periods=1).mean()
    if 'Volume_MA60' not in prepared.columns:
        prepared['Volume_MA60'] = prepared['Volume'].rolling(60, min_periods=1).mean()
    if 'ATR' not in prepared.columns:
        prepared['ATR'] = calculate_atr(prepared, cfg.atr_period)
    if not {'ADX', 'Plus_DI', 'Minus_DI'}.issubset(prepared.columns):
        adx_data = calculate_adx(prepared, cfg.adx_period)
        prepared[['ADX', 'Plus_DI', 'Minus_DI']] = adx_data[['ADX', 'Plus_DI', 'Minus_DI']]

    return prepared


class EnhancedPhaseDetector:
    """增强的阶段检测器 - 优化建议1"""

    def __init__(self, config: Optional[WyckoffConfig] = None):
        self.config = config or WyckoffConfig()
        self.confidence_threshold = self.config.confidence_threshold

    def identify_phase_with_confidence(self, data: pd.DataFrame) -> Dict[str, Any]:
        """带置信度的阶段识别"""
        if data is None or len(data) < self.config.min_data_length:
            return {'phase': MarketPhase.UNKNOWN, 'confidence': 0.0}

        data = prepare_wyckoff_data(data, self.config)
        if len(data) < self.config.min_data_length:
            return {'phase': MarketPhase.UNKNOWN, 'confidence': 0.0, 'error': '有效数据不足'}

        # 复用预计算ATR
        current_atr = float(data['ATR'].iloc[-1]) if 'ATR' in data.columns else 0.0

        phases = {
            MarketPhase.ACCUMULATION: self._analyze_accumulation_characteristics(data, current_atr),
            MarketPhase.MARKUP: self._analyze_markup_characteristics(data, current_atr),
            MarketPhase.DISTRIBUTION: self._analyze_distribution_characteristics(data, current_atr),
            MarketPhase.MARKDOWN: self._analyze_markdown_characteristics(data, current_atr)
        }

        # 计算每个阶段的置信度分数
        for phase, analysis in phases.items():
            phases[phase]['confidence'] = self._calculate_confidence(analysis)

        # 返回最高置信度的阶段
        best_phase = max(phases.items(), key=lambda x: x[1]['confidence'])

        if best_phase[1]['confidence'] >= self.confidence_threshold:
            return {
                'phase': best_phase[0],
                'confidence': best_phase[1]['confidence'],
                'details': best_phase[1],
                'all_phases': phases,
                'atr': current_atr
            }
        else:
            return {
                'phase': MarketPhase.UNKNOWN,
                'confidence': best_phase[1]['confidence'],
                'details': best_phase[1],
                'all_phases': phases,
                'atr': current_atr
            }

    def _analyze_accumulation_characteristics(self, data: pd.DataFrame, atr: float = 0.0) -> Dict:
        """分析积累期特征"""
        # 价格横向移动
        recent_data = data.tail(60)
        price_range = (recent_data['High'].max() - recent_data['Low'].min()) / recent_data['Low'].min()
        is_sideways = price_range < 0.3

        # 成交量特征
        volume_trend = self._calculate_volume_trend(recent_data)
        volume_contraction = volume_trend == 'decreasing'

        # Spring检测
        spring_score = self._detect_spring_patterns(recent_data)

        # 支撑强度
        support_strength = self._measure_support_quality(recent_data)

        # 阶段持续时间
        phase_duration = self._calculate_phase_timing(recent_data)

        return {
            'price_action': is_sideways,
            'volume_profile': volume_contraction,
            'spring_presence': spring_score,
            'support_strength': support_strength,
            'phase_duration': phase_duration,
            'characteristics_score': np.mean([is_sideways, volume_contraction,
                                           spring_score > 0, support_strength > 0.6])
        }

    def _analyze_markup_characteristics(self, data: pd.DataFrame, atr: float = 0) -> Dict:
        """分析上涨期特征"""
        recent_data = data.tail(30)

        # 价格趋势
        price_trend = self._calculate_price_trend(recent_data)
        is_uptrend = price_trend['direction'] > 0 and price_trend['strength'] > 0.01

        # 成交量确认
        volume_confirmation = self._check_volume_confirmation(recent_data, 'up')

        # 回调特征
        pullback_characteristics = self._analyze_pullback_patterns(recent_data)

        return {
            'trend_strength': price_trend['strength'],
            'trend_direction': price_trend['direction'],
            'r_squared': price_trend['r_squared'],
            'adx': price_trend['adx'],
            'volume_confirmation': volume_confirmation,
            'pullback_quality': pullback_characteristics,
            'characteristics_score': np.mean([is_uptrend, volume_confirmation,
                                           pullback_characteristics > 0.5])
        }

    def _analyze_distribution_characteristics(self, data: pd.DataFrame, atr: float = 0.0) -> Dict:
        """分析分布期特征"""
        recent_data = data.tail(60)

        # 价格横向移动（顶部）
        price_range = (recent_data['High'].max() - recent_data['Low'].min()) / recent_data['Low'].min()
        is_topping = price_range < 0.3 and recent_data['Close'].iloc[-1] > recent_data['Close'].mean()

        # 成交量特征
        volume_trend = self._calculate_volume_trend(recent_data)
        volume_pattern = volume_trend == 'decreasing' or self._has_volume_divergence(recent_data)

        # Upthrust检测
        upthrust_score = self._detect_upthrust_patterns(recent_data)

        return {
            'price_action': is_topping,
            'volume_pattern': volume_pattern,
            'upthrust_presence': upthrust_score,
            'characteristics_score': np.mean([is_topping, volume_pattern, upthrust_score > 0])
        }

    def _analyze_markdown_characteristics(self, data: pd.DataFrame, atr: float = 0) -> Dict:
        """分析下跌期特征"""
        recent_data = data.tail(30)

        # 价格趋势
        price_trend = self._calculate_price_trend(recent_data)
        is_downtrend = price_trend['direction'] < 0 and price_trend['strength'] > 0.01

        # 成交量确认
        volume_confirmation = self._check_volume_confirmation(recent_data, 'down')

        return {
            'trend_strength': price_trend['strength'],
            'trend_direction': price_trend['direction'],
            'r_squared': price_trend['r_squared'],
            'adx': price_trend['adx'],
            'volume_confirmation': volume_confirmation,
            'characteristics_score': np.mean([is_downtrend, volume_confirmation])
        }

    def _calculate_confidence(self, analysis: Dict) -> float:
        """计算置信度分数"""
        return analysis.get('characteristics_score', 0.0)

    def _calculate_volume_trend(self, data: pd.DataFrame) -> str:
        """计算成交量趋势"""
        if len(data) < 20:
            return 'unknown'

        recent_vol = data['Volume'].iloc[-10:].mean()
        past_vol = data['Volume'].iloc[-30:-10].mean()

        if recent_vol > past_vol * 1.2:
            return 'increasing'
        elif recent_vol < past_vol * 0.8:
            return 'decreasing'
        else:
            return 'stable'

    def _calculate_price_trend(self, data: pd.DataFrame) -> Dict[str, float]:
        """
        计算价格趋势强度 - 使用线性回归和ADX

        Returns:
            包含趋势方向、强度、R²和ADX的字典
        """
        if len(data) < 20:
            return {'direction': 0, 'strength': 0, 'r_squared': 0, 'adx': 0, 'slope': 0}

        close = pd.to_numeric(data['Close'], errors='coerce').dropna().to_numpy(dtype=float)
        if len(close) < 2:
            return {'direction': 0, 'strength': 0, 'r_squared': 0, 'adx': 0, 'slope': 0}

        # 线性回归计算趋势，过滤NaN后避免polyfit崩溃
        x = np.arange(len(close), dtype=float)
        slope, intercept = np.polyfit(x, close, 1)

        # 计算R²（趋势的"平稳度"）
        y_pred = slope * x + intercept
        ss_res = np.sum((close - y_pred) ** 2)
        ss_tot = np.sum((close - close.mean()) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

        # 复用预计算ADX，缺失时再计算
        if 'ADX' in data.columns and len(data['ADX'].dropna()) > 0:
            current_adx = float(data['ADX'].iloc[-1])
        else:
            adx_data = calculate_adx(data, self.config.adx_period)
            current_adx = float(adx_data['ADX'].iloc[-1]) if not adx_data.empty else 0.0

        # 趋势强度 = 斜率 * R² * ADX权重
        trend_direction = 1 if slope > 0 else -1 if slope < 0 else 0
        adx_weight = min(current_adx / 50, 1.0)  # ADX归一化到0-1
        trend_strength = abs(slope) * r_squared * adx_weight

        return {
            'direction': trend_direction,
            'strength': trend_strength,
            'r_squared': r_squared,
            'adx': current_adx,
            'slope': slope
        }

    def _detect_spring_patterns(self, data: pd.DataFrame) -> int:
        """检测Spring模式 - 向量化版本。"""
        if len(data) < 25:
            return 0
        support = data['Low'].rolling(window=20, min_periods=20).min().shift(5)
        atr = data['ATR'] if 'ATR' in data.columns else calculate_atr(data, self.config.atr_period)
        threshold = atr.fillna(data['Close'].mean() * 0.02) * self.config.atr_multiplier_spring
        future_recovery = data['High'].shift(-4).rolling(window=4, min_periods=1).max()
        spring_mask = (data['Low'] < support - threshold) & (future_recovery > support + threshold)
        return int(spring_mask.fillna(False).sum())

    def _is_spring(self, window_data: pd.DataFrame) -> bool:
        """判断是否为Spring - 使用ATR自适应阈值"""
        if len(window_data) < 25:
            return False

        # 计算ATR
        atr = calculate_atr(window_data, self.config.atr_period)
        current_atr = atr.iloc[-1] if not atr.empty else 0

        # 如果ATR为0，使用百分比回退
        if current_atr == 0:
            current_atr = window_data['Close'].mean() * 0.02

        # 寻找跌破支撑后快速收回
        support_level = window_data['Low'].iloc[:-5].min()
        breakdown_day = window_data.iloc[-5]
        recovery_period = window_data.iloc[-4:]

        # 使用ATR定义跌破和收回阈值
        breakdown_threshold = support_level - current_atr * self.config.atr_multiplier_spring
        recovery_threshold = support_level + current_atr * self.config.atr_multiplier_spring

        if (breakdown_day['Low'] < breakdown_threshold and
            recovery_period['High'].max() > recovery_threshold):
            return True
        return False

    def _detect_upthrust_patterns(self, data: pd.DataFrame) -> int:
        """检测Upthrust模式 - 向量化版本。"""
        if len(data) < 25:
            return 0
        resistance = data['High'].rolling(window=20, min_periods=20).max().shift(5)
        atr = data['ATR'] if 'ATR' in data.columns else calculate_atr(data, self.config.atr_period)
        threshold = atr.fillna(data['Close'].mean() * 0.02) * self.config.atr_multiplier_upthrust
        future_rejection = data['Low'].shift(-4).rolling(window=4, min_periods=1).min()
        upthrust_mask = (data['High'] > resistance + threshold) & (future_rejection < resistance - threshold)
        return int(upthrust_mask.fillna(False).sum())

    def _is_upthrust(self, window_data: pd.DataFrame) -> bool:
        """判断是否为Upthrust - 使用ATR自适应阈值"""
        if len(window_data) < 25:
            return False

        # 计算ATR
        atr = calculate_atr(window_data, self.config.atr_period)
        current_atr = atr.iloc[-1] if not atr.empty else 0

        # 如果ATR为0，使用百分比回退
        if current_atr == 0:
            current_atr = window_data['Close'].mean() * 0.02

        resistance_level = window_data['High'].iloc[:-5].max()
        breakout_day = window_data.iloc[-5]
        rejection_period = window_data.iloc[-4:]

        # 使用ATR定义突破和回落阈值
        breakout_threshold = resistance_level + current_atr * self.config.atr_multiplier_upthrust
        rejection_threshold = resistance_level - current_atr * self.config.atr_multiplier_upthrust

        if (breakout_day['High'] > breakout_threshold and
            rejection_period['Low'].min() < rejection_threshold):
            return True
        return False

    def _measure_support_quality(self, data: pd.DataFrame) -> float:
        """测量支撑质量"""
        # 基于支撑被测试次数和反弹力度
        support_tests = 0
        bounce_strength = 0.0

        low_points = data['Low'].nsmallest(5)
        for idx, low in low_points.items():
            if low < data['Low'].mean() * 0.95:
                support_tests += 1
                # 检查低点之后的反弹，避免布尔切片误用
                pos = data.index.get_loc(idx)
                if isinstance(pos, slice):
                    pos = pos.start
                elif not isinstance(pos, int):
                    pos = int(np.asarray(pos)[0])
                subsequent_data = data.iloc[pos:pos + 5]
                if len(subsequent_data) > 1:
                    bounce = subsequent_data['Close'].max() - low
                    bounce_strength += bounce / low

        return (support_tests * 0.3 + bounce_strength * 0.7) if support_tests > 0 else 0.0

    def _calculate_phase_timing(self, data: pd.DataFrame) -> Dict:
        """计算阶段时间特征"""
        days_in_phase = len(data)

        # 理想阶段持续时间（天）
        ideal_durations = {
            MarketPhase.ACCUMULATION: (40, 120),
            MarketPhase.DISTRIBUTION: (40, 120),
            MarketPhase.MARKUP: (30, 180),
            MarketPhase.MARKDOWN: (30, 180)
        }

        return {
            'days_in_phase': days_in_phase,
            'timing_quality': self._score_timing_quality(days_in_phase, ideal_durations)
        }

    def _score_timing_quality(self, days: int, ideal_durations: Dict) -> float:
        """评分时间质量"""
        best_score = 0.0
        for phase, (min_days, max_days) in ideal_durations.items():
            if min_days <= days <= max_days:
                score = 1.0 - abs(days - (min_days + max_days) / 2) / (max_days - min_days)
                best_score = max(best_score, score)
        return max(0.0, best_score)

    def _check_volume_confirmation(self, data: pd.DataFrame, direction: str) -> bool:
        """检查成交量确认"""
        if direction == 'up':
            # 上涨时成交量应该增加
            up_days = data[data['Close'] > data['Open']]
            if len(up_days) > 0:
                return up_days['Volume'].mean() > data['Volume'].mean()
        else:
            # 下跌时成交量应该增加
            down_days = data[data['Close'] < data['Open']]
            if len(down_days) > 0:
                return down_days['Volume'].mean() > data['Volume'].mean()
        return False

    def _analyze_pullback_patterns(self, data: pd.DataFrame) -> float:
        """分析回调模式"""
        # 计算回调的质量分数
        pullbacks = []
        for i in range(1, len(data)):
            if data['Close'].iloc[i] < data['Close'].iloc[i-1]:
                pullback_size = (data['Close'].iloc[i-1] - data['Close'].iloc[i]) / data['Close'].iloc[i-1]
                pullbacks.append(pullback_size)

        if not pullbacks:
            return 0.0

        # 回调应该温和（2-8%）
        good_pullbacks = [p for p in pullbacks if 0.02 <= p <= 0.08]
        return len(good_pullbacks) / len(pullbacks)

    def _has_volume_divergence(self, data: pd.DataFrame) -> bool:
        """检查量价背离"""
        price_trend = self._calculate_price_trend(data)
        volume_trend = 1 if self._calculate_volume_trend(data) == 'increasing' else -1

        # 价格上涨但成交量下降，或价格下跌但成交量上升
        return (price_trend['direction'] > 0 and volume_trend < 0) or (price_trend['direction'] < 0 and volume_trend > 0)


class AdvancedVolumeAnalyzer:
    """高级成交量分析器 - 优化建议3"""

    def __init__(self):
        self.volume_threshold_multiplier = 1.5

    def analyze_volume_profile(self, data: pd.DataFrame) -> Dict[str, Any]:
        """高级成交量分析"""
        if data is None or len(data) < 20:
            return {}
        data = prepare_wyckoff_data(data)
        if len(data) < 20:
            return {'error': '有效数据不足'}

        return {
            'volume_trend': self._calculate_volume_trend(data),
            'volume_climax': self._identify_volume_climax(data),
            'volume_divergence': self._detect_volume_divergence(data),
            'relative_volume': self._calculate_relative_volume(data),
            'volume_at_price': self._analyze_volume_at_price(data),
            'volume_profile': self._create_volume_profile(data)
        }

    def _calculate_volume_trend(self, data: pd.DataFrame) -> Dict:
        """计算成交量趋势"""
        ma5 = data['Volume'].rolling(5).mean().iloc[-1]
        ma20 = data['Volume'].rolling(20).mean().iloc[-1]
        ma60 = data['Volume'].rolling(60).mean().iloc[-1] if len(data) >= 60 else ma20

        current_volume = data['Volume'].iloc[-1]

        return {
            'current_vs_ma5': current_volume / ma5 if ma5 > 0 else 1,
            'current_vs_ma20': current_volume / ma20 if ma20 > 0 else 1,
            'current_vs_ma60': current_volume / ma60 if ma60 > 0 else 1,
            'trend': 'increasing' if ma5 > ma20 else 'decreasing' if ma5 < ma20 else 'stable'
        }

    def _identify_volume_climax(self, data: pd.DataFrame) -> Dict:
        """识别成交量高潮"""
        recent_volume = data['Volume'].tail(20)
        avg_volume = recent_volume.mean()
        max_volume = recent_volume.max()

        climax_threshold = avg_volume * 3  # 3倍平均量为高潮
        climax_days = recent_volume[recent_volume >= climax_threshold]

        return {
            'has_climax': len(climax_days) > 0,
            'climax_days': climax_days.index.tolist(),
            'max_volume_ratio': max_volume / avg_volume if avg_volume > 0 else 1,
            'climax_threshold': climax_threshold
        }

    def _detect_volume_divergence(self, data: pd.DataFrame) -> Dict:
        """检测量价背离"""
        if len(data) < 20:
            return {'has_divergence': False}

        # 价格新高但成交量下降
        recent_high = data['High'].tail(10).dropna()
        if recent_high.empty:
            return {'has_divergence': False}
        recent_price_high_idx = recent_high.idxmax()

        volume_at_high = data.loc[recent_price_high_idx, 'Volume']
        avg_volume_before = data['Volume'].loc[:recent_price_high_idx].tail(10).mean()

        bullish_divergence = False
        bearish_divergence = False

        if volume_at_high < avg_volume_before * 0.7:
            # 新高但成交量下降 - 看跌背离
            bearish_divergence = True

        # 价格新低但成交量下降
        recent_low = data['Low'].tail(10).dropna()
        if recent_low.empty:
            return {'has_divergence': bearish_divergence, 'bearish_divergence': bearish_divergence}
        recent_price_low_idx = recent_low.idxmin()

        volume_at_low = data.loc[recent_price_low_idx, 'Volume']
        avg_volume_before_low = data['Volume'].loc[:recent_price_low_idx].tail(10).mean()

        if volume_at_low < avg_volume_before_low * 0.7:
            # 新低但成交量下降 - 看涨背离
            bullish_divergence = True

        return {
            'has_divergence': bullish_divergence or bearish_divergence,
            'bullish_divergence': bullish_divergence,
            'bearish_divergence': bearish_divergence,
            'divergence_type': 'bullish' if bullish_divergence else 'bearish' if bearish_divergence else 'none'
        }

    def _calculate_relative_volume(self, data: pd.DataFrame, lookback_period: int = 20) -> float:
        """计算相对成交量"""
        current_volume = data['Volume'].iloc[-1]
        average_volume = data['Volume'].iloc[-lookback_period:].mean()
        return current_volume / average_volume if average_volume > 0 else 1.0

    def _analyze_volume_at_price(self, data: pd.DataFrame) -> Dict:
        """分析价格区间成交量 - 向量化优化版本"""
        if len(data) < 50:
            return {}

        # 使用pd.cut进行向量化分箱，替代O(n^2)的双重循环
        bin_data = pd.cut(data['Close'], bins=10)
        vp_series = data.groupby(bin_data, observed=True)['Volume'].sum()

        # 构建成交量分布字典
        volume_profile = {
            f"{interval.left:.2f}-{interval.right:.2f}": vol
            for interval, vol in vp_series.items()
        }

        # 找到最大成交量区间（POC - Point of Control）
        max_interval = vp_series.idxmax()

        return {
            'volume_profile': volume_profile,
            'max_volume_area': f"{max_interval.left:.2f}-{max_interval.right:.2f}",
            'max_volume': vp_series.max(),
            'value_area': self._calculate_value_area(volume_profile)
        }

    def _calculate_value_area(self, volume_profile: Dict) -> Dict:
        """
        计算价值区域 - 标准Volume Profile算法

        标准算法：从POC（最大成交量区间）开始，
        比较其上方和下方区间的成交量，将较大的一方纳入计算，
        直到达到总成交量的约68-70%。
        确保价值区域是连续的价格带。
        """
        if not volume_profile:
            return {'value_area_bins': [], 'cumulative_volume': 0, 'percentage': 0}

        total_volume = sum(volume_profile.values())
        if total_volume == 0:
            return {'value_area_bins': [], 'cumulative_volume': 0, 'percentage': 0}

        # 解析价格区间并排序
        bins_with_price = []
        for bin_range, volume in volume_profile.items():
            parts = bin_range.split('-')
            low = float(parts[0])
            high = float(parts[1])
            mid_price = (low + high) / 2
            bins_with_price.append({
                'range': bin_range,
                'low': low,
                'high': high,
                'mid': mid_price,
                'volume': volume
            })

        # 按价格排序
        bins_with_price.sort(key=lambda x: x['mid'])

        # 找到POC（最大成交量区间）
        poc_idx = max(range(len(bins_with_price)), key=lambda i: bins_with_price[i]['volume'])

        # 从POC开始，向两侧扩展
        value_area_bins = [bins_with_price[poc_idx]['range']]
        cumulative_volume = bins_with_price[poc_idx]['volume']

        upper_idx = poc_idx + 1
        lower_idx = poc_idx - 1

        target_volume = total_volume * 0.70  # 目标70%成交量

        while cumulative_volume < target_volume and (upper_idx < len(bins_with_price) or lower_idx >= 0):
            upper_vol = bins_with_price[upper_idx]['volume'] if upper_idx < len(bins_with_price) else 0
            lower_vol = bins_with_price[lower_idx]['volume'] if lower_idx >= 0 else 0

            # 选择成交量较大的一侧
            if upper_vol >= lower_vol and upper_idx < len(bins_with_price):
                value_area_bins.append(bins_with_price[upper_idx]['range'])
                cumulative_volume += upper_vol
                upper_idx += 1
            elif lower_idx >= 0:
                value_area_bins.append(bins_with_price[lower_idx]['range'])
                cumulative_volume += lower_vol
                lower_idx -= 1
            else:
                break

        # 按价格排序value_area_bins
        value_area_bins.sort(key=lambda x: float(x.split('-')[0]))

        return {
            'value_area_bins': value_area_bins,
            'cumulative_volume': cumulative_volume,
            'percentage': cumulative_volume / total_volume if total_volume > 0 else 0,
            'poc_price': bins_with_price[poc_idx]['mid'] if poc_idx < len(bins_with_price) else 0
        }

    def _create_volume_profile(self, data: pd.DataFrame) -> Dict:
        """创建成交量剖面图数据"""
        return {
            'high_volume_nodes': self._find_high_volume_nodes(data),
            'low_volume_nodes': self._find_low_volume_nodes(data),
            'point_of_control': self._find_point_of_control(data)
        }

    def _find_high_volume_nodes(self, data: pd.DataFrame) -> List[float]:
        """找到高成交量节点"""
        volume_ma = data['Volume'].rolling(20).mean()
        high_volume_days = data[data['Volume'] > volume_ma * 1.5]
        return high_volume_days['Close'].tolist()

    def _find_low_volume_nodes(self, data: pd.DataFrame) -> List[float]:
        """找到低成交量节点"""
        volume_ma = data['Volume'].rolling(20).mean()
        low_volume_days = data[data['Volume'] < volume_ma * 0.5]
        return low_volume_days['Close'].tolist()

    def _find_point_of_control(self, data: pd.DataFrame) -> float:
        """找到控制点（最大成交量对应的价格）"""
        if len(data) == 0:
            return 0.0

        # 简化：返回最大成交量日的收盘价
        max_volume_idx = data['Volume'].idxmax()
        return data.loc[max_volume_idx, 'Close']


class CauseEffectCalculator:
    """因果定律计算器 - 优化建议4"""

    def __init__(self):
        self.fibonacci_levels = [0.618, 1.0, 1.618, 2.0, 2.618]

    def calculate_targets(self, data: pd.DataFrame, breakout_direction: str,
                         breakout_point: Optional[float] = None) -> Dict[str, Any]:
        """因果定律目标计算"""
        if data is None or len(data) < 30:
            return {}

        # 识别交易区间
        trading_range = self._identify_trading_range(data)

        if not trading_range['valid']:
            return {'error': '无法识别有效的交易区间'}

        cause_size = trading_range['height']

        if breakout_point is None:
            breakout_point = trading_range.get('breakout_level')
        if breakout_point is None:
            if breakout_direction.lower() in ['up', 'long', 'bullish']:
                breakout_point = float(trading_range['high'])
            else:
                breakout_point = float(trading_range['low'])

        targets = self._calculate_target_levels(float(breakout_point), cause_size, breakout_direction)

        return {
            'trading_range': trading_range,
            'cause_size': cause_size,
            'breakout_point': float(breakout_point),
            'targets': targets,
            'risk_reward_analysis': self._analyze_risk_reward(targets, float(breakout_point))
        }

    def _identify_trading_range(self, data: pd.DataFrame) -> Dict:
        """识别交易区间"""
        # 寻找横盘整理区间
        recent_data = data.tail(60)

        high_max = recent_data['High'].max()
        low_min = recent_data['Low'].min()
        range_height = high_max - low_min

        # 判断是否为有效的交易区间
        range_pct = range_height / low_min
        is_valid_range = 0.15 <= range_pct <= 0.4  # 15%-40%的区间

        # 寻找突破点
        breakout_level = None
        if len(data) > 60:
            # 检查最近是否有突破
            latest_close = data['Close'].iloc[-1]
            if latest_close > high_max * 1.02:
                breakout_level = high_max
            elif latest_close < low_min * 0.98:
                breakout_level = low_min

        return {
            'valid': is_valid_range,
            'high': high_max,
            'low': low_min,
            'height': range_height,
            'range_percentage': range_pct,
            'breakout_level': breakout_level,
            'duration': len(recent_data)
        }

    def _calculate_target_levels(self, breakout_point: float, cause_size: float,
                                direction: str) -> Dict[str, float]:
        """计算目标价位"""
        targets = {}

        if direction.lower() in ['up', 'long', 'bullish']:
            for i, level in enumerate(self.fibonacci_levels):
                targets[f'target_{i+1}'] = breakout_point + (cause_size * level)
                targets[f'target_{i+1}_description'] = f'{level}倍因果幅度'
        else:
            for i, level in enumerate(self.fibonacci_levels):
                targets[f'target_{i+1}'] = breakout_point - (cause_size * level)
                targets[f'target_{i+1}_description'] = f'{level}倍因果幅度'

        return targets

    def _analyze_risk_reward(self, targets: Dict, entry_point: float) -> Dict:
        """分析风险收益比"""
        if 'target_1' not in targets:
            return {}

        # 假设止损在入场点下方3%
        stop_loss = entry_point * 0.97
        risk = entry_point - stop_loss

        risk_reward_ratios = {}
        for i in range(1, len(self.fibonacci_levels) + 1):
            target_key = f'target_{i}'
            if target_key in targets:
                reward = abs(targets[target_key] - entry_point)
                risk_reward_ratios[f'rr_ratio_{i}'] = reward / risk if risk > 0 else 0

        return {
            'risk_per_share': risk,
            'risk_reward_ratios': risk_reward_ratios,
            'best_rr_ratio': max(risk_reward_ratios.values()) if risk_reward_ratios else 0
        }

    def calculate_position_size(self, account_size: float, risk_per_trade: float,
                               entry_price: float, stop_loss: float) -> Dict:
        """计算头寸规模"""
        risk_amount = account_size * risk_per_trade
        risk_per_share = abs(entry_price - stop_loss)

        position_size = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0

        return {
            'position_size': position_size,
            'risk_amount': risk_amount,
            'risk_per_share': risk_per_share,
            'total_position_value': position_size * entry_price,
            'risk_percentage': (risk_amount / account_size) * 100
        }


class OptimalEntryDetector:
    """最佳入场点检测器 - 优化建议5"""

    def __init__(self):
        self.entry_filters = {
            'volume_confirmation': True,
            'price_action_confirmation': True,
            'multi_timeframe_confirmation': True
        }

    def find_entry_points(self, data: pd.DataFrame, phase: str, events: Dict) -> List[Dict]:
        """寻找最佳入场点"""
        entries = []

        if phase == 'accumulation':
            entries.extend(self._find_long_entries(data, events))
        elif phase == 'distribution':
            entries.extend(self._find_short_entries(data, events))

        # 过滤和排序入场点
        filtered_entries = self._filter_entries(entries, data)
        return sorted(filtered_entries, key=lambda x: x['quality_score'], reverse=True)

    def _find_long_entries(self, data: pd.DataFrame, events: Dict) -> List[Dict]:
        """寻找做多入场点"""
        entries = []

        # LPS入场点
        if events.get('lps_detected', False):
            lps_data = events.get('lps_data', {})
            entries.append({
                'type': 'LPS',
                'price': lps_data.get('price', data['Close'].iloc[-1]),
                'stop_loss': lps_data.get('stop_loss'),
                'quality_score': self._calculate_entry_quality(data, lps_data, 'long'),
                'entry_reason': 'LPS回调结束，成交量萎缩',
                'timeframe': 'primary'
            })

        # SOS确认后入场
        if events.get('sos_detected', False):
            sos_data = events.get('sos_data', {})
            entries.append({
                'type': 'SOS_CONFIRMATION',
                'price': sos_data.get('confirmation_price', data['Close'].iloc[-1]),
                'stop_loss': sos_data.get('pullback_low'),
                'quality_score': self._calculate_entry_quality(data, sos_data, 'long'),
                'entry_reason': 'SOS强势信号确认突破',
                'timeframe': 'primary'
            })

        # Spring入场点
        if events.get('spring_detected', False):
            spring_data = events.get('spring_data', {})
            entries.append({
                'type': 'SPRING',
                'price': spring_data.get('recovery_price', data['Close'].iloc[-1]),
                'stop_loss': spring_data.get('breakdown_price') * 0.98,
                'quality_score': self._calculate_entry_quality(data, spring_data, 'long'),
                'entry_reason': 'Spring震仓结束，快速收回',
                'timeframe': 'primary'
            })

        return entries

    def _find_short_entries(self, data: pd.DataFrame, events: Dict) -> List[Dict]:
        """寻找做空入场点"""
        entries = []

        # LPSY入场点
        if events.get('lpsy_detected', False):
            lpsy_data = events.get('lpsy_data', {})
            entries.append({
                'type': 'LPSY',
                'price': lpsy_data.get('price', data['Close'].iloc[-1]),
                'stop_loss': lpsy_data.get('stop_loss'),
                'quality_score': self._calculate_entry_quality(data, lpsy_data, 'short'),
                'entry_reason': 'LPSY反弹结束，成交量萎缩',
                'timeframe': 'primary'
            })

        # SOW确认后入场
        if events.get('sow_detected', False):
            sow_data = events.get('sow_data', {})
            entries.append({
                'type': 'SOW_CONFIRMATION',
                'price': sow_data.get('confirmation_price', data['Close'].iloc[-1]),
                'stop_loss': sow_data.get('pullback_high'),
                'quality_score': self._calculate_entry_quality(data, sow_data, 'short'),
                'entry_reason': 'SOW弱势信号确认跌破',
                'timeframe': 'primary'
            })

        # Upthrust入场点
        if events.get('upthrust_detected', False):
            upthrust_data = events.get('upthrust_data', {})
            entries.append({
                'type': 'UPTHRUST',
                'price': upthrust_data.get('rejection_price', data['Close'].iloc[-1]),
                'stop_loss': upthrust_data.get('breakout_price') * 1.02,
                'quality_score': self._calculate_entry_quality(data, upthrust_data, 'short'),
                'entry_reason': 'Upthrust假突破结束，快速回落',
                'timeframe': 'primary'
            })

        return entries

    def _calculate_entry_quality(self, data: pd.DataFrame, entry_data: Dict, direction: str) -> float:
        """计算入场点质量分数"""
        quality_score = 0.0

        # 成交量因素 (30%)
        volume_score = self._evaluate_volume_quality(data, entry_data, direction)
        quality_score += volume_score * 0.3

        # 价格行为因素 (40%)
        price_action_score = self._evaluate_price_action_quality(data, entry_data, direction)
        quality_score += price_action_score * 0.4

        # 市场环境因素 (30%)
        market_context_score = self._evaluate_market_context(data, direction)
        quality_score += market_context_score * 0.3

        return min(1.0, quality_score)

    def _evaluate_volume_quality(self, data: pd.DataFrame, entry_data: Dict, direction: str) -> float:
        """评估成交量质量"""
        if 'volume_ratio' in entry_data:
            volume_ratio = entry_data['volume_ratio']
            if direction == 'long':
                # 做多需要放量确认
                return min(1.0, volume_ratio / 2.0) if volume_ratio >= 1.2 else 0.0
            else:
                # 做空也需要放量确认
                return min(1.0, volume_ratio / 2.0) if volume_ratio >= 1.2 else 0.0
        return 0.5

    def _evaluate_price_action_quality(self, data: pd.DataFrame, entry_data: Dict, direction: str) -> float:
        """评估价格行为质量"""
        score = 0.0

        # 检查是否有明确的形态确认
        if 'confirmation_quality' in entry_data:
            score += entry_data['confirmation_quality'] * 0.6

        # 检查支撑/阻力位置
        if 'support_resistance_quality' in entry_data:
            score += entry_data['support_resistance_quality'] * 0.4

        return min(1.0, score)

    def _evaluate_market_context(self, data: pd.DataFrame, direction: str) -> float:
        """评估市场环境"""
        # 简化版市场环境评估
        recent_trend = self._calculate_recent_trend(data)

        if direction == 'long' and recent_trend > 0:
            return 0.8  # 上升趋势中做多有利
        elif direction == 'short' and recent_trend < 0:
            return 0.8  # 下降趋势中做空有利
        else:
            return 0.4  # 逆势操作风险较高

    def _calculate_recent_trend(self, data: pd.DataFrame) -> float:
        """计算近期趋势"""
        if len(data) < 10:
            return 0.0

        recent_returns = data['Close'].pct_change().tail(10)
        return float(recent_returns.mean())

    def _filter_entries(self, entries: List[Dict], data: pd.DataFrame) -> List[Dict]:
        """过滤入场点"""
        filtered = []

        for entry in entries:
            # 质量分数过滤
            if entry['quality_score'] < 0.6:
                continue

            # 价格合理性过滤
            current_price = data['Close'].iloc[-1]
            entry_price = entry['price']

            if abs(entry_price - current_price) / current_price > 0.1:  # 超过10%偏差
                continue

            filtered.append(entry)

        return filtered


class ChinaMarketAdapter:
    """A股市场适配器 - 优化建议7"""

    def __init__(self, config: Optional[WyckoffConfig] = None):
        self.config = config or WyckoffConfig()
        self.market_specific_rules = {
            't_plus_one': self.config.a_share_t_plus_one,
            'price_limit_main': self.config.a_share_price_limit,
            'price_limit_kcb': self.config.a_share_price_limit_kcb,
            'trading_hours': ['09:30-11:30', '13:00-15:00'],
            'lot_size': self.config.min_position_size,
            'stamp_duty': 0.001,
            'commission_rate': 0.00025
        }

    def adapt_wyckoff_analysis(self, data: pd.DataFrame, analysis_type: str) -> Dict:
        """适配A股市场的威科夫分析"""
        if analysis_type == 'accumulation':
            return self._adapt_accumulation_for_a_shares(data)
        elif analysis_type == 'distribution':
            return self._adapt_distribution_for_a_shares(data)
        elif analysis_type == 'trading':
            return self._adapt_trading_strategy_for_a_shares(data)
        else:
            return self._general_a_share_adaptation(data)

    def _adapt_accumulation_for_a_shares(self, data: pd.DataFrame) -> Dict:
        """A股积累期分析适配"""
        # 考虑T+1对交易策略的影响
        t_plus_one_adjustment = self._adjust_for_t_plus_one()

        # 考虑涨跌停限制对价格行为的限制
        price_limit_adjustment = self._adjust_for_price_limits(data)

        # 考虑A股特有的成交量特征
        volume_characteristics = self._analyze_a_share_volume_patterns(data)

        # 机构行为分析
        institutional_behavior = self._analyze_a_share_institutions(data)

        # 涨跌停板价量关系修正
        price_limit_volume_fix = self._fix_price_limit_volume(data)

        # ST风险检测
        st_risk = self._detect_st_risk(data)

        return {
            't_plus_one_impact': t_plus_one_adjustment,
            'price_limit_impact': price_limit_adjustment,
            'volume_patterns': volume_characteristics,
            'institutional_activity': institutional_behavior,
            'price_limit_volume_fix': price_limit_volume_fix,
            'st_risk': st_risk,
            'adapted_signals': self._generate_adapted_signals(data, 'accumulation')
        }

    def _adapt_distribution_for_a_shares(self, data: pd.DataFrame) -> Dict:
        """A股分布期分析适配"""
        # 考虑做空限制
        short_selling_constraints = self._analyze_short_selling_constraints()

        # 大股东减持模式
        insider_selling_patterns = self._analyze_insider_selling(data)

        # 市场情绪指标
        sentiment_indicators = self._analyze_a_share_sentiment(data)

        # 涨跌停板价量关系修正
        price_limit_volume_fix = self._fix_price_limit_volume(data)

        # A股分布期应给出清仓信号而非做空信号
        exit_signals = self._generate_exit_signals(data)

        return {
            'short_selling_constraints': short_selling_constraints,
            'insider_selling_patterns': insider_selling_patterns,
            'sentiment_analysis': sentiment_indicators,
            'price_limit_volume_fix': price_limit_volume_fix,
            'exit_signals': exit_signals,
            'adapted_signals': self._generate_adapted_signals(data, 'distribution')
        }

    def _adapt_trading_strategy_for_a_shares(self, data: pd.DataFrame) -> Dict:
        """A股交易策略适配"""
        # 交易成本计算
        trading_costs = self._calculate_trading_costs()

        # 流动性分析
        liquidity_analysis = self._analyze_liquidity(data)

        # 市场情绪影响
        sentiment_impact = self._analyze_sentiment_impact(data)

        return {
            'trading_costs': trading_costs,
            'liquidity_analysis': liquidity_analysis,
            'sentiment_impact': sentiment_impact,
            'recommended_strategy': self._recommend_a_share_strategy(data)
        }

    def _general_a_share_adaptation(self, data: pd.DataFrame) -> Dict:
        """通用A股适配分析"""
        return {
            'market_characteristics': self._analyze_market_characteristics(data),
            'regulatory_factors': self._analyze_regulatory_factors(),
            'cultural_factors': self._analyze_cultural_factors(),
            'adaptation_score': self._calculate_adaptation_score(data)
        }

    def _adjust_for_t_plus_one(self) -> Dict:
        """T+1交易制度调整"""
        return {
            'immediate_execution': False,
            'overnight_risk': True,
            'entry_timing_adjustment': '需要更精确的入场时机',
            'exit_flexibility': '降低，需要提前规划出场策略'
        }

    def _adjust_for_price_limits(self, data: pd.DataFrame) -> Dict:
        """涨跌停限制调整"""
        # 分析涨跌停对威科夫形态的影响
        limit_up_days = len(data[data['Close'] == data['High']])  # 涨停日
        limit_down_days = len(data[data['Close'] == data['Low']])  # 跌停日

        return {
            'limit_up_frequency': limit_up_days / len(data) if len(data) > 0 else 0,
            'limit_down_frequency': limit_down_days / len(data) if len(data) > 0 else 0,
            'impact_on_patterns': '涨跌停可能中断威科夫形态的自然发展',
            'adjustment_needed': limit_up_days + limit_down_days > len(data) * 0.1
        }

    def _fix_price_limit_volume(self, data: pd.DataFrame) -> Dict:
        """
        涨跌停板价量关系修正

        A股涨跌停板状态下，成交量会因为"无法成交"而极度缩小（缩量一字板）。
        系统原本的量价逻辑在涨停板时会失效。

        优化：如果遇到涨幅 > 9.8%（科创/创业板 19.8%），即使缩量也应视为极度强势。
        """
        if len(data) < 5:
            return {'needs_fix': False}

        recent_data = data.tail(20)

        # 检测涨跌停板
        limit_up_threshold = 1 + self.config.a_share_price_limit - 0.002  # 9.8%
        limit_down_threshold = 1 - self.config.a_share_price_limit + 0.002  # -9.8%

        # 计算日收益率
        daily_returns = recent_data['Close'].pct_change()

        # 检测涨停日
        limit_up_days = recent_data[daily_returns >= limit_up_threshold]
        limit_down_days = recent_data[daily_returns <= -limit_down_threshold]

        # 涨停板的特殊处理
        volume_fixes = []
        for idx in limit_up_days.index:
            # 涨停日即使缩量也视为强势
            volume_fixes.append({
                'date': idx,
                'type': 'limit_up',
                'adjustment': '涨停板缩量仍视为强势，忽略传统量价逻辑'
            })

        for idx in limit_down_days.index:
            # 跌停日的成交量分析需特殊处理
            volume_fixes.append({
                'date': idx,
                'type': 'limit_down',
                'adjustment': '跌停日成交量可能失真，需结合封单金额分析'
            })

        return {
            'needs_fix': len(volume_fixes) > 0,
            'limit_up_count': len(limit_up_days),
            'limit_down_count': len(limit_down_days),
            'fixes': volume_fixes,
            'recommendation': '涨跌停板期间需使用封单金额/流通市值代替传统成交量分析'
        }

    def _detect_st_risk(self, data: pd.DataFrame) -> Dict:
        """
        ST风险检测

        A股针对亏损有ST和退市机制，如果在低位（假定的积累期）价格跌破历史重大支撑
        并且没有成交量配合，这不是Spring震仓，极有可能是因为基本面暴雷导致的流动性丧失退市趋势。

        需要加入财务/公告因子的过滤器。
        """
        if len(data) < 60:
            return {'risk_level': 'unknown', 'needs_filter': False}

        # 检测异常下跌模式
        recent_data = data.tail(60)
        price_change_60d = (recent_data['Close'].iloc[-1] / recent_data['Close'].iloc[0] - 1) * 100

        # 检测是否处于历史低位
        all_time_low = data['Low'].min()
        current_price = data['Close'].iloc[-1]
        distance_from_low = (current_price - all_time_low) / all_time_low * 100

        # 检测成交量异常（持续缩量可能是流动性丧失）
        recent_volume = recent_data['Volume'].tail(20).mean()
        historical_volume = data['Volume'].mean()
        volume_ratio = recent_volume / historical_volume if historical_volume > 0 else 1

        # 风险评估
        risk_factors = []

        if price_change_60d < -30:
            risk_factors.append('60日跌幅超过30%')

        if distance_from_low < 5:  # 距离历史低点不到5%
            risk_factors.append('接近历史低点')

        if volume_ratio < 0.3:  # 成交量萎缩到历史的30%以下
            risk_factors.append('成交量极度萎缩，可能存在流动性风险')

        # 判断风险等级
        if len(risk_factors) >= 3:
            risk_level = 'high'
        elif len(risk_factors) >= 2:
            risk_level = 'medium'
        elif len(risk_factors) >= 1:
            risk_level = 'low'
        else:
            risk_level = 'normal'

        return {
            'risk_level': risk_level,
            'needs_filter': risk_level in ['high', 'medium'],
            'risk_factors': risk_factors,
            'price_change_60d': price_change_60d,
            'distance_from_low': distance_from_low,
            'volume_ratio': volume_ratio,
            'recommendation': '建议查询公司公告和财务数据，排除ST/退市风险' if risk_level != 'normal' else '暂无明显ST风险'
        }

    def _generate_exit_signals(self, data: pd.DataFrame) -> Dict:
        """
        生成清仓信号（A股分布期专用）

        A股融券做空受到极大约束，在 DISTRIBUTION（派发期）的建议
        不应是寻找 Short Entries，而是给出强烈的 Exit Long (清仓) 信号。
        """
        if len(data) < 20:
            return {'should_exit': False}

        recent_data = prepare_wyckoff_data(data).tail(20)

        # 检测分布期特征
        exit_signals = []

        # 1. 价格在高位滞涨
        price_range = (recent_data['High'].max() - recent_data['Low'].min()) / recent_data['Close'].mean()
        if price_range < 0.1 and recent_data['Close'].iloc[-1] > recent_data['Close'].mean():
            exit_signals.append('高位横盘滞涨')

        # 2. 成交量放大但价格不涨（放量滞涨）
        volume_increasing = recent_data['Volume'].iloc[-5:].mean() > recent_data['Volume'].mean() * 1.5
        price_flat = abs(recent_data['Close'].iloc[-1] / recent_data['Close'].iloc[-5] - 1) < 0.03
        if volume_increasing and price_flat:
            exit_signals.append('放量滞涨，可能是主力出货')

        # 3. 连续阴线/连续下跌，向量化倒序计算尾部连续True数量
        is_down = recent_data['Close'].diff() < 0
        consecutive_down = int(is_down.iloc[::-1].cumprod().sum())
        if consecutive_down >= 5:
            exit_signals.append(f'连续{consecutive_down}日下跌')

        # 4. 跌破重要均线，复用预计算MA20
        ma20 = recent_data['MA20'] if 'MA20' in recent_data.columns else recent_data['Close'].rolling(20, min_periods=1).mean()
        if recent_data['Close'].iloc[-1] < ma20.iloc[-1] * 0.95:
            exit_signals.append('跌破20日均线5%以上')

        # 生成清仓建议
        should_exit = len(exit_signals) >= 2

        return {
            'should_exit': should_exit,
            'exit_signals': exit_signals,
            'urgency': 'high' if len(exit_signals) >= 3 else 'medium' if len(exit_signals) >= 2 else 'low',
            'recommendation': '建议清仓或大幅减仓' if should_exit else '可继续持有但需密切关注'
        }

    def _analyze_a_share_volume_patterns(self, data: pd.DataFrame) -> Dict:
        """分析A股特有的成交量模式"""
        # A股成交量特征：
        # 1. 开盘和收盘成交量通常较大
        # 2. 涨停/跌停日成交量异常
        # 3. 消息驱动型成交量激增

        avg_volume = data['Volume'].mean()
        volume_std = data['Volume'].std()

        # 识别异常成交量日
        abnormal_volume_days = len(data[data['Volume'] > avg_volume + 2 * volume_std])

        return {
            'average_volume': avg_volume,
            'volume_volatility': volume_std / avg_volume,
            'abnormal_volume_frequency': abnormal_volume_days / len(data) if len(data) > 0 else 0,
            'characteristic_patterns': '消息驱动型成交量激增常见'
        }

    def _analyze_a_share_institutions(self, data: pd.DataFrame) -> Dict:
        """分析A股机构行为"""
        # 简化版机构行为分析
        # 在真实环境中，这里需要接入机构持仓数据

        return {
            'institutional_presence': '需要外部数据支持',
            'estimated_institutional_activity': self._estimate_institutional_activity(data),
            'retail_trader_impact': 'A股散户参与度较高，可能影响威科夫形态'
        }

    def _estimate_institutional_activity(self, data: pd.DataFrame) -> str:
        """估计机构活动水平"""
        # 基于成交量和价格波动性估计
        volume_stability = data['Volume'].std() / data['Volume'].mean()
        price_volatility = data['Close'].pct_change().std()

        if volume_stability < 0.5 and price_volatility < 0.02:
            return '机构参与度较高（稳定成交量，低波动）'
        elif volume_stability > 1.0 and price_volatility > 0.03:
            return '散户参与度较高（高成交量波动，高价格波动）'
        else:
            return '混合参与（机构和散户共同参与）'

    def _analyze_short_selling_constraints(self) -> Dict:
        """分析做空限制"""
        return {
            'margin_trading_available': True,
            'short_selling_difficulty': '较高，需要转融通',
            'cost_of_shorting': '较高，利息成本+融券费用',
            'alternative_strategies': ['看跌期权', '反向ETF', '直接卖出持仓']
        }

    def _analyze_insider_selling(self, data: pd.DataFrame) -> Dict:
        """分析内部人减持"""
        # 简化版分析，真实环境需要接入公告数据
        return {
            'insider_selling_detection': '需要公告数据',
            'pattern_recognition': '大股东减持前通常有价格异动',
            'warning_signals': '成交量异常放大伴随价格滞涨'
        }

    def _analyze_a_share_sentiment(self, data: pd.DataFrame) -> Dict:
        """分析A股市场情绪"""
        # 基于价格和成交量数据的情绪分析
        recent_performance = data['Close'].pct_change(10).iloc[-1]
        volume_trend = data['Volume'].iloc[-10:].mean() / data['Volume'].iloc[-30:-10].mean()

        sentiment_score = 0.5  # 中性
        if recent_performance > 0.05 and volume_trend > 1.2:
            sentiment_score = 0.8  # 乐观
        elif recent_performance < -0.05 and volume_trend > 1.2:
            sentiment_score = 0.2  # 悲观

        return {
            'sentiment_score': sentiment_score,
            'sentiment_trend': 'optimistic' if sentiment_score > 0.6 else 'pessimistic' if sentiment_score < 0.4 else 'neutral',
            'retail_trader_sentiment': 'A股散户情绪波动较大，需要谨慎对待'
        }

    def _generate_adapted_signals(self, data: pd.DataFrame, phase: str) -> List[Dict]:
        """生成适配A股的信号"""
        signals = []

        if phase == 'accumulation':
            # A股积累期特殊信号
            signals.append({
                'signal_type': 'institutional_buying',
                'description': '机构建仓信号（基于成交量分析）',
                'confidence': 0.7,
                'a_share_specific': True
            })

            signals.append({
                'signal_type': 'retail_panic',
                'description': '散户恐慌性抛售（Spring形态）',
                'confidence': 0.8,
                'a_share_specific': True
            })

        elif phase == 'distribution':
            # A股分布期特殊信号
            signals.append({
                'signal_type': 'insider_selling',
                'description': '内部人减持信号',
                'confidence': 0.6,
                'a_share_specific': True
            })

            signals.append({
                'signal_type': 'retail_fomo',
                'description': '散户FOMO追高（Upthrust形态）',
                'confidence': 0.8,
                'a_share_specific': True
            })

        return signals

    def _calculate_trading_costs(self) -> Dict:
        """计算A股交易成本"""
        return {
            'stamp_duty': self.market_specific_rules['stamp_duty'],
            'commission': self.market_specific_rules['commission_rate'],
            'total_round_trip_cost': (self.market_specific_rules['stamp_duty'] +
                                    self.market_specific_rules['commission_rate']) * 2,
            'impact_on_trading': '交易成本相对较高，需要更大的价格波动才能盈利'
        }

    def _analyze_liquidity(self, data: pd.DataFrame) -> Dict:
        """分析流动性"""
        avg_daily_volume = data['Volume'].mean()
        turnover_rate = avg_daily_volume / 1000000  # 假设总股本100万股

        return {
            'average_daily_volume': avg_daily_volume,
            'estimated_turnover_rate': turnover_rate,
            'liquidity_classification': 'high' if turnover_rate > 0.05 else 'medium' if turnover_rate > 0.02 else 'low',
            'trading_impact': '高流动性有利于威科夫策略执行'
        }

    def _analyze_sentiment_impact(self, data: pd.DataFrame) -> Dict:
        """分析市场情绪影响"""
        return {
            'retail_dominance': 'A股散户占比较高，情绪化交易明显',
            'policy_sensitivity': '对政策消息敏感，可能影响威科夫形态',
            'herd_behavior': '羊群效应明显，可能放大威科夫信号',
            'adaptation_needed': '需要结合市场情绪指标进行确认'
        }

    def _recommend_a_share_strategy(self, data: pd.DataFrame) -> Dict:
        """推荐A股交易策略"""
        return {
            'position_sizing': '建议降低仓位，考虑T+1限制',
            'entry_timing': '选择流动性好的时段入场（10:00-11:00, 14:00-15:00）',
            'risk_management': '严格止损，考虑涨跌停限制',
            'holding_period': 'A股波动较大，建议缩短持仓周期',
            'confirmation_needed': '需要更多确认信号，避免假突破'
        }

    def _analyze_market_characteristics(self, data: pd.DataFrame) -> Dict:
        """分析A股市场特征"""
        return {
            'volatility_profile': 'A股波动性较高，有利于威科夫策略',
            'trending_behavior': '趋势性较强，但持续时间可能较短',
            'news_impact': '对消息面反应强烈，可能影响形态发展',
            'seasonal_patterns': '存在一定的季节性特征（如年底行情）'
        }

    def _analyze_regulatory_factors(self) -> Dict:
        """分析监管因素"""
        return {
            'policy_risk': '政策变化可能影响市场走势',
            'trading_restrictions': '涨跌停、T+1等限制需要特别考虑',
            'disclosure_requirements': '信息披露制度相对完善',
            'investor_protection': '投资者保护机制逐步完善'
        }

    def _analyze_cultural_factors(self) -> Dict:
        """分析文化因素"""
        return {
            'investment_horizon': 'A股投资者普遍偏短线',
            'risk_tolerance': '风险偏好较高，追涨杀跌明显',
            'herd_mentality': '羊群效应显著',
            'adaptation_needed': '威科夫策略需要更强的确认信号'
        }

    def _calculate_adaptation_score(self, data: pd.DataFrame) -> float:
        """计算A股适配分数"""
        # 基于市场特征计算适配度
        volatility_score = min(1.0, data['Close'].pct_change().std() * 50)  # 波动性有利
        volume_score = min(1.0, data['Volume'].mean() / 1000000)  # 成交量
        trend_score = abs(data['Close'].pct_change(20).iloc[-1])  # 趋势强度

        return (volatility_score + volume_score + trend_score) / 3


class MultiTimeframeAnalyzer:
    """多时间框架分析器 - 优化建议8"""

    def __init__(self):
        self.timeframes = {
            'monthly': 252,    # 月线
            'weekly': 52,     # 周线
            'daily': 252,     # 日线
            '4hour': 1260,    # 4小时线（假设每天6根）
            'hourly': 1512    # 小时线（假设每天6根，63天）
        }

    def analyze_across_timeframes(self, symbol: str, data_dict: Dict[str, pd.DataFrame]) -> Dict:
        """多时间框架综合分析"""
        if not data_dict:
            return {'error': '无有效数据'}

        results = {}

        # 分析每个时间框架
        for timeframe, data in data_dict.items():
            if data is not None and len(data) > 0:
                prepared = prepare_wyckoff_data(data)
                results[timeframe] = {
                    'phase': self._identify_phase_tf(prepared),
                    'trend': self._identify_trend_tf(prepared),
                    'key_levels': self._identify_key_levels_tf(prepared),
                    'events': self._detect_events_tf(prepared),
                    'strength': self._calculate_strength_tf(prepared)
                }

        # 整合多时间框架分析结果
        integrated_analysis = self._integrate_timeframe_analysis(results)

        return {
            'individual_timeframes': results,
            'integrated_analysis': integrated_analysis,
            'trading_recommendations': self._generate_trading_recommendations(results, integrated_analysis)
        }

    def _identify_phase_tf(self, data: pd.DataFrame) -> str:
        """单时间框架阶段识别"""
        # 简化的阶段识别
        if len(data) < 20:
            return 'Insufficient Data'

        # 复用预计算均线
        ma20 = data['MA20'].iloc[-1] if 'MA20' in data.columns else data['Close'].rolling(20, min_periods=1).mean().iloc[-1]
        ma50 = data['MA50'].iloc[-1] if 'MA50' in data.columns else data['Close'].rolling(50, min_periods=1).mean().iloc[-1]
        current_price = data['Close'].iloc[-1]

        # 判断趋势方向
        if current_price > ma20 > ma50:
            return 'Bullish'
        elif current_price < ma20 < ma50:
            return 'Bearish'
        else:
            return 'Consolidating'

    def _identify_trend_tf(self, data: pd.DataFrame) -> Dict:
        """单时间框架趋势识别"""
        if len(data) < 20:
            return {'direction': 'Unknown', 'strength': 0.0}

        # 计算趋势指标
        price_change = (data['Close'].iloc[-1] - data['Close'].iloc[-20]) / data['Close'].iloc[-20]
        ma_slope = self._calculate_ma_slope(data)

        if price_change > 0.05 and ma_slope > 0:
            direction = 'Up'
            strength = min(1.0, abs(price_change) * 10)
        elif price_change < -0.05 and ma_slope < 0:
            direction = 'Down'
            strength = min(1.0, abs(price_change) * 10)
        else:
            direction = 'Sideways'
            strength = abs(price_change) * 5

        return {
            'direction': direction,
            'strength': strength,
            'price_change_20': price_change,
            'ma_slope': ma_slope
        }

    def _identify_key_levels_tf(self, data: pd.DataFrame) -> List[Dict]:
        """识别关键支撑阻力位"""
        if len(data) < 50:
            return []

        levels = []

        window_size = 25
        local_min = data['Low'].rolling(window=window_size, center=True, min_periods=window_size).min()
        support_points = data[data['Low'].eq(local_min)]
        for idx, row in support_points.iterrows():
            i = data.index.get_loc(idx)
            if isinstance(i, slice):
                i = i.start
            elif not isinstance(i, int):
                i = int(np.asarray(i)[0])
            levels.append({
                'price': row['Low'],
                'type': 'Support',
                'strength': self._calculate_level_strength(data, i, 'support')
            })

        local_max = data['High'].rolling(window=window_size, center=True, min_periods=window_size).max()
        resistance_points = data[data['High'].eq(local_max)]
        for idx, row in resistance_points.iterrows():
            i = data.index.get_loc(idx)
            if isinstance(i, slice):
                i = i.start
            elif not isinstance(i, int):
                i = int(np.asarray(i)[0])
            levels.append({
                'price': row['High'],
                'type': 'Resistance',
                'strength': self._calculate_level_strength(data, i, 'resistance')
            })

        # 按强度排序，返回前5个
        levels.sort(key=lambda x: x['strength'], reverse=True)
        return levels[:5]

    def _detect_events_tf(self, data: pd.DataFrame) -> List[Dict]:
        """检测威科夫事件"""
        events = []
        if len(data) < 25:
            return events

        support = data['Low'].rolling(window=20, min_periods=20).min().shift(5)
        spring_mask = (data['Low'] < support * 0.98) & (data['High'].shift(-4).rolling(4, min_periods=1).max() > support * 1.02)
        for idx, row in data[spring_mask.fillna(False)].iterrows():
            events.append({
                'type': 'Spring',
                'date': idx,
                'price': row['Low'],
                'confidence': 0.8
            })

        resistance = data['High'].rolling(window=20, min_periods=20).max().shift(5)
        vol_ma = data['Volume'].rolling(window=20, min_periods=1).mean()
        sos_mask = (data['Close'] > resistance * 1.03) & (data['Volume'] > vol_ma * 1.5)
        for idx, row in data[sos_mask.fillna(False)].iterrows():
            events.append({
                'type': 'SOS',
                'date': idx,
                'price': row['High'],
                'confidence': 0.8
            })

        return events

    def _calculate_strength_tf(self, data: pd.DataFrame) -> float:
        """计算时间框架强度"""
        if len(data) < 20:
            return 0.0

        # 基于趋势一致性和成交量
        trend_consistency = self._calculate_trend_consistency(data)
        volume_support = self._calculate_volume_support(data)

        return (trend_consistency + volume_support) / 2

    def _integrate_timeframe_analysis(self, results: Dict) -> Dict:
        """整合多时间框架分析"""
        if not results:
            return {}

        # 主要趋势由最高时间框架决定
        primary_timeframe = max(results.keys(), key=lambda x: self.timeframes.get(x, 0))
        primary_trend = results[primary_timeframe]['trend']

        # 交易信号需要至少2个时间框架确认
        confirmed_signals = self._find_confirmed_signals(results)

        # 关键支撑阻力取各时间框架的交集
        key_levels = self._consolidate_key_levels(results)

        # 计算整体市场状态
        market_state = self._determine_market_state(results)

        return {
            'primary_trend': primary_trend,
            'confirmed_signals': confirmed_signals,
            'key_levels': key_levels,
            'market_state': market_state,
            'trading_bias': self._determine_trading_bias(results),
            'confidence_level': self._calculate_overall_confidence(results)
        }

    def _find_confirmed_signals(self, results: Dict) -> List[Dict]:
        """寻找确认的信号"""
        confirmed = []

        # 统计各时间框架的信号
        signal_counts = {}
        for timeframe, analysis in results.items():
            for event in analysis.get('events', []):
                event_key = f"{event['type']}_{event['price']:.2f}"
                if event_key not in signal_counts:
                    signal_counts[event_key] = {
                        'event': event,
                        'timeframes': [],
                        'count': 0
                    }
                signal_counts[event_key]['timeframes'].append(timeframe)
                signal_counts[event_key]['count'] += 1

        # 选择被多个时间框架确认的信号
        for signal_info in signal_counts.values():
            if signal_info['count'] >= 2:  # 至少2个时间框架确认
                confirmed.append({
                    'event': signal_info['event'],
                    'confirming_timeframes': signal_info['timeframes'],
                    'confirmation_strength': signal_info['count'] / len(results)
                })

        return confirmed

    def _consolidate_key_levels(self, results: Dict) -> List[Dict]:
        """整合关键支撑阻力位"""
        all_levels = []

        # 收集所有时间框架的支撑阻力位
        for timeframe, analysis in results.items():
            for level in analysis.get('key_levels', []):
                level['timeframe'] = timeframe
                all_levels.append(level)

        # 按价格聚类相似的支撑阻力位
        consolidated = self._cluster_similar_levels(all_levels)

        # 按强度排序
        consolidated.sort(key=lambda x: x['combined_strength'], reverse=True)

        return consolidated[:10]  # 返回前10个最强的关键位

    def _cluster_similar_levels(self, levels: List[Dict]) -> List[Dict]:
        """聚类相似的价格水平"""
        if not levels:
            return []

        # 按价格排序
        levels.sort(key=lambda x: x['price'])

        clusters = []
        current_cluster = [levels[0]]

        for level in levels[1:]:
            # 如果价格差异小于2%，认为是同一水平
            if abs(level['price'] - current_cluster[-1]['price']) / current_cluster[-1]['price'] < 0.02:
                current_cluster.append(level)
            else:
                # 创建聚类
                clusters.append(self._create_level_cluster(current_cluster))
                current_cluster = [level]

        # 添加最后一个聚类
        if current_cluster:
            clusters.append(self._create_level_cluster(current_cluster))

        return clusters

    def _create_level_cluster(self, cluster_levels: List[Dict]) -> Dict:
        """创建支撑阻力位聚类"""
        avg_price = sum(level['price'] for level in cluster_levels) / len(cluster_levels)
        combined_strength = sum(level['strength'] for level in cluster_levels)

        # 确定主要类型（支撑或阻力）
        support_count = sum(1 for level in cluster_levels if level['type'] == 'Support')
        resistance_count = len(cluster_levels) - support_count

        primary_type = 'Support' if support_count > resistance_count else 'Resistance'

        return {
            'price': avg_price,
            'type': primary_type,
            'combined_strength': combined_strength,
            'supporting_timeframes': [level['timeframe'] for level in cluster_levels],
            'level_count': len(cluster_levels)
        }

    def _determine_market_state(self, results: Dict) -> str:
        """确定整体市场状态"""
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        for analysis in results.values():
            trend = analysis.get('trend', {}).get('direction', 'Unknown')
            if trend == 'Up':
                bullish_count += 1
            elif trend == 'Down':
                bearish_count += 1
            else:
                neutral_count += 1

        total = len(results)
        if total == 0:
            return 'Unknown'

        bullish_ratio = bullish_count / total
        bearish_ratio = bearish_count / total

        if bullish_ratio >= 0.6:
            return 'Strongly Bullish'
        elif bearish_ratio >= 0.6:
            return 'Strongly Bearish'
        elif bullish_ratio >= 0.4:
            return 'Mildly Bullish'
        elif bearish_ratio >= 0.4:
            return 'Mildly Bearish'
        else:
            return 'Neutral/Consolidating'

    def _determine_trading_bias(self, results: Dict) -> str:
        """确定交易偏向"""
        market_state = self._determine_market_state(results)

        if 'Bullish' in market_state:
            return 'Long Bias'
        elif 'Bearish' in market_state:
            return 'Short Bias'
        else:
            return 'Neutral/Wait'

    def _calculate_overall_confidence(self, results: Dict) -> float:
        """计算整体置信度"""
        if not results:
            return 0.0

        # 基于时间框架的一致性
        trend_agreement = self._calculate_trend_agreement(results)
        strength_average = sum(analysis.get('strength', 0) for analysis in results.values()) / len(results)

        return (trend_agreement + strength_average) / 2

    def _calculate_trend_agreement(self, results: Dict) -> float:
        """计算趋势一致性"""
        directions = [analysis.get('trend', {}).get('direction', 'Unknown') for analysis in results.values()]

        if not directions:
            return 0.0

        # 计算最频繁的方向
        from collections import Counter
        direction_counts = Counter(directions)
        most_common_count = direction_counts.most_common(1)[0][1]

        return most_common_count / len(directions)

    def _calculate_ma_slope(self, data: pd.DataFrame, period: int = 20, lookback: int = 5) -> float:
        """计算均线斜率，优先复用预计算MA。"""
        if len(data) < max(period, lookback):
            return 0.0
        ma_col = f'MA{period}'
        ma = data[ma_col] if ma_col in data.columns else data['Close'].rolling(period, min_periods=1).mean()
        recent_ma = ma.dropna().tail(lookback)
        if len(recent_ma) < 2 or recent_ma.iloc[0] == 0:
            return 0.0
        return float((recent_ma.iloc[-1] - recent_ma.iloc[0]) / recent_ma.iloc[0])

    def _calculate_level_strength(self, data: pd.DataFrame, level_idx: int, level_type: str) -> float:
        """计算支撑/阻力强度：测试次数 + 成交量确认。"""
        if len(data) == 0 or level_idx < 0 or level_idx >= len(data):
            return 0.0
        price_level = data['Low'].iloc[level_idx] if level_type == 'support' else data['High'].iloc[level_idx]
        if price_level == 0:
            return 0.0
        start = max(0, level_idx - 60)
        end = min(len(data), level_idx + 20)
        window = data.iloc[start:end]
        if level_type == 'support':
            touches = ((window['Low'] - price_level).abs() / price_level < 0.02).sum()
        else:
            touches = ((window['High'] - price_level).abs() / price_level < 0.02).sum()
        vol_ma = window['Volume'].mean() if len(window) > 0 else 0
        level_vol = data['Volume'].iloc[level_idx]
        volume_bonus = min(0.3, (level_vol / vol_ma - 1) * 0.1) if vol_ma > 0 and level_vol > vol_ma else 0
        return float(min(1.0, touches * 0.15 + volume_bonus))

    def _calculate_trend_consistency(self, data: pd.DataFrame) -> float:
        """计算多个短中期窗口的趋势一致性。"""
        if len(data) < 20:
            return 0.0
        directions = []
        for period in (5, 10, 20):
            if len(data) >= period and data['Close'].iloc[-period] != 0:
                change = (data['Close'].iloc[-1] - data['Close'].iloc[-period]) / data['Close'].iloc[-period]
                directions.append(1 if change > 0 else -1 if change < 0 else 0)
        if not directions:
            return 0.0
        positive = sum(1 for direction in directions if direction > 0)
        negative = sum(1 for direction in directions if direction < 0)
        return max(positive, negative) / len(directions)

    def _calculate_volume_support(self, data: pd.DataFrame) -> float:
        """计算成交量是否支持当前趋势。"""
        if len(data) < 20:
            return 0.0
        up_days = data[data['Close'] > data['Open']]
        down_days = data[data['Close'] < data['Open']]
        if len(up_days) == 0 or len(down_days) == 0:
            return 0.5
        up_volume = up_days['Volume'].mean()
        down_volume = down_days['Volume'].mean()
        trend = self._identify_trend_tf(data).get('direction', 'Sideways')
        if trend == 'Up':
            return float(min(1.0, up_volume / down_volume)) if down_volume > 0 else 1.0
        if trend == 'Down':
            return float(min(1.0, down_volume / up_volume)) if up_volume > 0 else 1.0
        return 0.5

    def _generate_trading_recommendations(self, results: Dict, integrated: Dict) -> List[Dict]:
        """生成交易建议"""
        recommendations = []

        trading_bias = integrated.get('trading_bias', 'Neutral/Wait')

        if trading_bias == 'Long Bias':
            recommendations.append({
                'action': 'Look for long entries',
                'timeframe': 'Primary',
                'conditions': 'Wait for LPS after SOS confirmation',
                'risk_management': 'Stop loss below Spring low',
                'position_size': 'Conservative until confirmation'
            })
        elif trading_bias == 'Short Bias':
            recommendations.append({
                'action': 'Look for short entries',
                'timeframe': 'Primary',
                'conditions': 'Wait for LPSY after SOW confirmation',
                'risk_management': 'Stop loss above Upthrust high',
                'position_size': 'Conservative, A-stock shorting limited'
            })
        else:
            recommendations.append({
                'action': 'Wait and observe',
                'timeframe': 'All',
                'conditions': 'No clear directional bias',
                'risk_management': 'Preserve capital',
                'position_size': 'No new positions'
            })

        return recommendations


class RelativeStrengthAnalyzer:
    """相对强度分析器 - 威科夫5步骤方法Step 2"""

    def __init__(self, benchmark_symbol: str = '000300'):
        """
        初始化相对强度分析器

        Args:
            benchmark_symbol: 基准指数代码（默认沪深300）
        """
        self.benchmark_symbol = benchmark_symbol
        self.rs_period = 20  # RS计算周期
        self.rs_ma_period = 10  # RS均线周期

    def calculate_rs(self, stock_data: pd.DataFrame, benchmark_data: pd.DataFrame) -> Dict[str, Any]:
        """
        计算相对强度

        Args:
            stock_data: 股票数据
            benchmark_data: 基准指数数据

        Returns:
            相对强度分析结果
        """
        if stock_data is None or benchmark_data is None:
            return {'error': '数据不足'}

        if len(stock_data) < self.rs_period or len(benchmark_data) < self.rs_period:
            return {'error': '数据长度不足'}

        # 对齐数据日期
        aligned_data = self._align_data(stock_data, benchmark_data)
        if aligned_data is None:
            return {'error': '无法对齐数据'}

        stock_aligned, benchmark_aligned = aligned_data

        # 计算RS线
        rs_line = self._calculate_rs_line(stock_aligned, benchmark_aligned)

        # 计算RS变化率
        rs_change = self._calculate_rs_change(rs_line)

        # 计算RS趋势
        rs_trend = self._calculate_rs_trend(rs_line)

        # 计算RS动量
        rs_momentum = self._calculate_rs_momentum(rs_line)

        # 判断相对强弱状态
        rs_status = self._determine_rs_status(rs_line, rs_trend, rs_momentum)

        return {
            'rs_line': rs_line,
            'rs_current': rs_line.iloc[-1] if len(rs_line) > 0 else 1.0,
            'rs_change': rs_change,
            'rs_trend': rs_trend,
            'rs_momentum': rs_momentum,
            'rs_status': rs_status,
            'is_outperforming': rs_status in [RSStatus.STRONG.value, RSStatus.IMPROVING.value, RSStatus.STRONG, RSStatus.IMPROVING],
            'recommendation': self._generate_rs_recommendation(rs_status, rs_trend)
        }

    def _align_data(self, stock_data: pd.DataFrame, benchmark_data: pd.DataFrame) -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
        """对齐股票和基准数据"""
        try:
            # 获取共同日期
            common_dates = stock_data.index.intersection(benchmark_data.index)

            if len(common_dates) < self.rs_period:
                return None

            stock_aligned = stock_data.loc[common_dates]
            benchmark_aligned = benchmark_data.loc[common_dates]

            return stock_aligned, benchmark_aligned
        except Exception:
            return None

    def _calculate_rs_line(self, stock_data: pd.DataFrame, benchmark_data: pd.DataFrame) -> pd.Series:
        """计算RS线 = 股票价格 / 基准价格"""
        rs_line = stock_data['Close'] / benchmark_data['Close']
        # 归一化到100
        rs_line = (rs_line / rs_line.iloc[0]) * 100
        return rs_line

    def _calculate_rs_change(self, rs_line: pd.Series) -> Dict[str, float]:
        """计算RS变化率"""
        if len(rs_line) < 2:
            return {'daily': 0, 'weekly': 0, 'monthly': 0}

        daily_change = (rs_line.iloc[-1] / rs_line.iloc[-2] - 1) * 100

        weekly_change = 0
        if len(rs_line) >= 5:
            weekly_change = (rs_line.iloc[-1] / rs_line.iloc[-5] - 1) * 100

        monthly_change = 0
        if len(rs_line) >= 20:
            monthly_change = (rs_line.iloc[-1] / rs_line.iloc[-20] - 1) * 100

        return {
            'daily': daily_change,
            'weekly': weekly_change,
            'monthly': monthly_change
        }

    def _calculate_rs_trend(self, rs_line: pd.Series) -> Dict[str, Any]:
        """计算RS趋势"""
        if len(rs_line) < self.rs_ma_period:
            return {'direction': 'Unknown', 'strength': 0}

        # 计算RS均线
        rs_ma = rs_line.rolling(self.rs_ma_period).mean()
        current_rs = rs_line.iloc[-1]
        current_ma = rs_ma.iloc[-1]

        # 判断趋势方向
        if current_rs > current_ma * 1.02:
            direction = 'Up'
            strength = min(1.0, (current_rs / current_ma - 1) * 10)
        elif current_rs < current_ma * 0.98:
            direction = 'Down'
            strength = min(1.0, (1 - current_rs / current_ma) * 10)
        else:
            direction = 'Sideways'
            strength = 0.5

        # 计算趋势斜率
        if len(rs_line) >= 10:
            slope = (rs_line.iloc[-1] - rs_line.iloc[-10]) / 10
        else:
            slope = 0

        return {
            'direction': direction,
            'strength': strength,
            'slope': slope,
            'ma_value': current_ma
        }

    def _calculate_rs_momentum(self, rs_line: pd.Series) -> Dict[str, Any]:
        """计算RS动量"""
        if len(rs_line) < 10:
            return {'value': 0, 'is_positive': False}

        # 使用ROC（Rate of Change）计算动量
        roc_period = 10
        roc = (rs_line.iloc[-1] / rs_line.iloc[-roc_period] - 1) * 100

        # 判断动量方向
        is_positive = roc > 0

        # 判断动量强度
        if abs(roc) > 5:
            strength = 'Strong'
        elif abs(roc) > 2:
            strength = 'Moderate'
        else:
            strength = 'Weak'

        return {
            'value': roc,
            'is_positive': is_positive,
            'strength': strength
        }

    def _determine_rs_status(self, rs_line: pd.Series, rs_trend: Dict, rs_momentum: Dict) -> str:
        """判断相对强弱状态"""
        current_rs = rs_line.iloc[-1] if len(rs_line) > 0 else 100

        # 状态判断逻辑
        if current_rs > 105 and rs_trend['direction'] == 'Up' and rs_momentum['is_positive']:
            return 'Strong'  # 强势：RS高于105且上升趋势
        elif current_rs < 95 and rs_trend['direction'] == 'Down' and not rs_momentum['is_positive']:
            return 'Weak'  # 弱势：RS低于95且下降趋势
        elif rs_trend['direction'] == 'Up' and rs_momentum['is_positive']:
            return 'Improving'  # 改善中：趋势向上且动量为正
        elif rs_trend['direction'] == 'Down' and not rs_momentum['is_positive']:
            return 'Deteriorating'  # 恶化中：趋势向下且动量为负
        else:
            return 'Neutral'  # 中性

    def _generate_rs_recommendation(self, rs_status: str, rs_trend: Dict) -> str:
        """生成RS交易建议"""
        recommendations = {
            'Strong': '股票表现强势，可考虑做多',
            'Improving': '股票正在走强，关注做多机会',
            'Neutral': '股票与大盘同步，观望为主',
            'Deteriorating': '股票正在走弱，谨慎操作',
            'Weak': '股票表现弱势，避免做多或考虑做空'
        }
        return recommendations.get(rs_status, '无法判断')

    def calculate_rs_ranking(self, stocks_data: Dict[str, pd.DataFrame],
                            benchmark_data: pd.DataFrame) -> List[Dict]:
        """
        计算多只股票的RS排名

        Args:
            stocks_data: 多只股票数据 {symbol: data}
            benchmark_data: 基准指数数据

        Returns:
            按RS排名的股票列表
        """
        rs_results = []

        for symbol, stock_data in stocks_data.items():
            rs_result = self.calculate_rs(stock_data, benchmark_data)
            if 'error' not in rs_result:
                rs_results.append({
                    'symbol': symbol,
                    'rs_current': rs_result['rs_current'],
                    'rs_status': rs_result['rs_status'],
                    'rs_momentum': rs_result['rs_momentum']['value'],
                    'recommendation': rs_result['recommendation']
                })

        # 按RS值排序
        rs_results.sort(key=lambda x: x['rs_current'], reverse=True)

        # 添加排名
        for i, result in enumerate(rs_results):
            result['rank'] = i + 1

        return rs_results


class WyckoffBacktester:
    """威科夫策略回测系统 - 验证策略有效性"""

    def __init__(self, initial_capital: float = 100000, risk_per_trade: float = 0.02):
        """
        初始化回测系统

        Args:
            initial_capital: 初始资金
            risk_per_trade: 每笔交易风险比例
        """
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.trades = []
        self.equity_curve = []

    def backtest_strategy(self, data: pd.DataFrame, signals: List[Dict],
                         strategy_name: str = 'Wyckoff') -> Dict[str, Any]:
        """
        回测威科夫策略

        Args:
            data: 历史数据
            signals: 交易信号列表
            strategy_name: 策略名称

        Returns:
            回测结果统计
        """
        if data is None or len(data) < 60:
            return {'error': '数据不足'}

        if not signals:
            return {'error': '无交易信号'}

        data = prepare_wyckoff_data(data)

        # 初始化回测状态
        capital = self.initial_capital
        position = 0
        position_price = 0
        trades = []
        equity_curve = [{'date': data.index[0], 'equity': capital}]

        # 将信号列表预处理为哈希表，避免每日O(K)线性扫描
        signal_dict = self._build_signal_dict(signals)

        # 遍历数据执行回测
        for i in range(60, len(data)):
            current_date = data.index[i]
            current_price = data['Close'].iloc[i]

            # O(1)信号查询
            signal = signal_dict.get(pd.Timestamp(current_date).normalize())

            if signal:
                if signal['action'] == 'BUY' and position == 0:
                    # 开仓做多
                    shares = self._calculate_position_size(capital, current_price, signal.get('stop_loss'))
                    if shares > 0:
                        position = shares
                        position_price = current_price
                        capital -= shares * current_price
                        trades.append({
                            'entry_date': current_date,
                            'entry_price': current_price,
                            'shares': shares,
                            'type': 'LONG',
                            'signal': signal
                        })

                elif signal['action'] == 'SELL' and position > 0:
                    # 平仓
                    capital += position * current_price
                    profit = (current_price - position_price) * position
                    profit_pct = (current_price / position_price - 1) * 100

                    trades[-1].update({
                        'exit_date': current_date,
                        'exit_price': current_price,
                        'profit': profit,
                        'profit_pct': profit_pct,
                        'holding_days': (current_date - trades[-1]['entry_date']).days
                    })

                    position = 0
                    position_price = 0

            # 更新权益曲线
            equity = capital + position * current_price
            equity_curve.append({'date': current_date, 'equity': equity})

        # 如果还有持仓，以最后价格平仓
        if position > 0:
            final_price = data['Close'].iloc[-1]
            capital += position * final_price
            profit = (final_price - position_price) * position
            profit_pct = (final_price / position_price - 1) * 100

            trades[-1].update({
                'exit_date': data.index[-1],
                'exit_price': final_price,
                'profit': profit,
                'profit_pct': profit_pct,
                'holding_days': (data.index[-1] - trades[-1]['entry_date']).days
            })

        # 计算回测统计
        self.trades = trades
        self.equity_curve = equity_curve

        return self._calculate_backtest_statistics(trades, equity_curve, strategy_name)

    def _build_signal_dict(self, signals: List[Dict]) -> Dict[pd.Timestamp, Dict]:
        """将信号列表转换为按日期索引的哈希表，查询复杂度从O(K)降为O(1)。"""
        signal_dict = {}
        for signal in signals:
            if 'date' not in signal:
                continue
            try:
                normalized_date = pd.Timestamp(signal['date']).normalize()
            except Exception:
                continue
            # 同日多信号时保留最后一个，通常后生成的信号优先级更高
            signal_dict[normalized_date] = signal
        return signal_dict

    def _find_signal_for_date(self, signals: List[Dict], date) -> Optional[Dict]:
        """兼容旧接口：查找指定日期的信号。新回测主流程已改用哈希表。"""
        normalized_date = pd.Timestamp(date).normalize()
        return self._build_signal_dict(signals).get(normalized_date)

    def _calculate_position_size(self, capital: float, price: float, stop_loss: Optional[float] = None) -> int:
        """计算仓位大小"""
        if stop_loss and stop_loss > 0:
            # 基于风险计算仓位
            risk_amount = capital * self.risk_per_trade
            risk_per_share = abs(price - stop_loss)
            if risk_per_share > 0:
                shares = int(risk_amount / risk_per_share)
            else:
                shares = int(capital * 0.95 / price)
        else:
            # 默认使用95%资金
            shares = int(capital * 0.95 / price)

        # 确保至少100股（A股最小交易单位）
        return max(100, (shares // 100) * 100)

    def _calculate_backtest_statistics(self, trades: List[Dict], equity_curve: List[Dict],
                                      strategy_name: str) -> Dict[str, Any]:
        """计算回测统计指标"""
        if not trades:
            return {'error': '无成交记录'}

        # 过滤已完成的交易
        completed_trades = [t for t in trades if 'exit_date' in t]

        if not completed_trades:
            return {'error': '无已完成交易'}

        # 基本统计
        total_trades = len(completed_trades)
        winning_trades = len([t for t in completed_trades if t['profit'] > 0])
        losing_trades = len([t for t in completed_trades if t['profit'] <= 0])

        # 盈亏统计
        profits = [t['profit'] for t in completed_trades if t['profit'] > 0]
        losses = [t['profit'] for t in completed_trades if t['profit'] <= 0]

        total_profit = sum(profits) if profits else 0
        total_loss = sum(losses) if losses else 0
        net_profit = total_profit + total_loss

        # 胜率和盈亏比
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
        avg_profit = total_profit / winning_trades if winning_trades > 0 else 0
        avg_loss = abs(total_loss / losing_trades) if losing_trades > 0 else 0
        profit_factor = total_profit / abs(total_loss) if total_loss != 0 else float('inf')

        # 最大回撤
        max_drawdown = self._calculate_max_drawdown(equity_curve)

        # 持仓时间
        holding_days = [t['holding_days'] for t in completed_trades if 'holding_days' in t]
        avg_holding_days = sum(holding_days) / len(holding_days) if holding_days else 0

        # 夏普比率（简化版）
        returns = self._calculate_returns(equity_curve)
        sharpe_ratio = self._calculate_sharpe_ratio(returns)

        return {
            'strategy_name': strategy_name,
            'initial_capital': self.initial_capital,
            'final_capital': equity_curve[-1]['equity'] if equity_curve else self.initial_capital,
            'total_return': (equity_curve[-1]['equity'] / self.initial_capital - 1) * 100 if equity_curve else 0,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'net_profit': net_profit,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'avg_holding_days': avg_holding_days,
            'sharpe_ratio': sharpe_ratio,
            'trades': completed_trades,
            'equity_curve': equity_curve
        }

    def _calculate_max_drawdown(self, equity_curve: List[Dict]) -> float:
        """计算最大回撤"""
        if len(equity_curve) < 2:
            return 0.0

        equities = [point['equity'] for point in equity_curve]
        peak = equities[0]
        max_dd = 0.0

        for equity in equities:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_returns(self, equity_curve: List[Dict]) -> List[float]:
        """计算收益率序列"""
        if len(equity_curve) < 2:
            return []

        equities = [point['equity'] for point in equity_curve]
        returns = []

        for i in range(1, len(equities)):
            daily_return = (equities[i] / equities[i-1] - 1)
            returns.append(daily_return)

        return returns

    def _calculate_sharpe_ratio(self, returns: List[float], risk_free_rate: float = 0.03) -> float:
        """计算夏普比率"""
        if not returns:
            return 0.0

        import numpy as np
        returns_array = np.array(returns)
        excess_returns = returns_array - risk_free_rate / 252  # 日化无风险利率

        if excess_returns.std() == 0:
            return 0.0

        sharpe = excess_returns.mean() / excess_returns.std() * np.sqrt(252)
        return sharpe

    def generate_report(self, backtest_result: Dict) -> str:
        """生成回测报告"""
        if 'error' in backtest_result:
            return f"回测错误: {backtest_result['error']}"

        report = f"""
{'='*60}
威科夫策略回测报告
{'='*60}

策略名称: {backtest_result['strategy_name']}
回测周期: {backtest_result['trades'][0]['entry_date']} - {backtest_result['trades'][-1]['exit_date']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【资金统计】
初始资金: ¥{backtest_result['initial_capital']:,.2f}
最终资金: ¥{backtest_result['final_capital']:,.2f}
总收益率: {backtest_result['total_return']:.2f}%
净利润:   ¥{backtest_result['net_profit']:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【交易统计】
总交易次数: {backtest_result['total_trades']}
盈利次数:   {backtest_result['winning_trades']}
亏损次数:   {backtest_result['losing_trades']}
胜率:       {backtest_result['win_rate']:.2f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【盈亏分析】
总盈利:   ¥{backtest_result['total_profit']:,.2f}
总亏损:   ¥{backtest_result['total_loss']:,.2f}
盈亏比:   {backtest_result['profit_factor']:.2f}
平均盈利: ¥{backtest_result['avg_profit']:,.2f}
平均亏损: ¥{backtest_result['avg_loss']:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【风险指标】
最大回撤:   {backtest_result['max_drawdown']:.2f}%
夏普比率:   {backtest_result['sharpe_ratio']:.2f}
平均持仓天数: {backtest_result['avg_holding_days']:.1f}天

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【交易明细】
"""
        # 添加交易明细
        for i, trade in enumerate(backtest_result['trades'][:10], 1):  # 只显示前10笔
            report += f"""
交易{i}:
  入场: {trade['entry_date']} @ ¥{trade['entry_price']:.2f}
  出场: {trade['exit_date']} @ ¥{trade['exit_price']:.2f}
  盈亏: ¥{trade['profit']:,.2f} ({trade['profit_pct']:.2f}%)
  持仓: {trade['holding_days']}天
"""

        if len(backtest_result['trades']) > 10:
            report += f"\n... 还有{len(backtest_result['trades'])-10}笔交易未显示"

        report += f"""

{'='*60}
报告生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*60}
"""

        return report

    def plot_equity_curve(self, backtest_result: Dict, save_path: Optional[str] = None):
        """绘制权益曲线"""
        if 'error' in backtest_result:
            print(f"无法绘制: {backtest_result['error']}")
            return

        import matplotlib.pyplot as plt

        equity_curve = backtest_result['equity_curve']
        dates = [point['date'] for point in equity_curve]
        equities = [point['equity'] for point in equity_curve]

        plt.figure(figsize=(12, 6))
        plt.plot(dates, equities, label='权益曲线', color='blue')
        plt.axhline(y=self.initial_capital, color='gray', linestyle='--', label='初始资金')

        plt.title(f"威科夫策略回测 - {backtest_result['strategy_name']}")
        plt.xlabel('日期')
        plt.ylabel('资金 (¥)')
        plt.legend()
        plt.grid(True, alpha=0.3)

        # 标注关键点
        plt.annotate(f"最终: ¥{equities[-1]:,.0f}",
                    xy=(dates[-1], equities[-1]),
                    xytext=(10, 10), textcoords='offset points')

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"图表已保存: {save_path}")

        plt.show()
