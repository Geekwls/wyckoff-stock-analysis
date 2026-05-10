#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态阈值自适应系统
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ============================================================
# 命名常量：波动率体制边界
# ============================================================
ATR_PCT_LOW_MEDIUM_BOUNDARY = 1.0   # ATR% < 1.0% → 低波动
ATR_PCT_MEDIUM_HIGH_BOUNDARY = 2.5  # ATR% ≥ 2.5% → 高波动
DEFAULT_MEDIUM_ATR_PCT = 1.5        # 默认中等波动率
VOLUME_CONFIRMATION_STRONG = 2.0     # 强势成交量确认倍数
VOLUME_CONFIRMATION_MODERATE = 1.5   # 中等成交量确认倍数
SPRING_BREAKDOWN_MIN_PCT = 1.0      # Spring最小跌破百分比
SPRING_BREAKDOWN_MAX_PCT = 3.0      # Spring最大跌破百分比
JOC_MIN_BREAKOUT_PCT = 3.0          # JOC最小突破百分比
JOC_MIN_VOLUME_RATIO = 1.5          # JOC最小量比
JOC_MIN_CLOSE_POSITION = 0.75       # JOC最低收盘位置
SOT_VOLUME_THRESHOLD = 1.3          # SOT量比阈值
SOT_BODY_RATIO_THRESHOLD = 0.3      # SOT实体占比阈值
MAX_RECOVERY_DAYS_LOW_VOL = 5       # 低波动最大收回天数
MAX_RECOVERY_DAYS_MEDIUM_VOL = 3    # 中波动最大收回天数
MAX_RECOVERY_DAYS_HIGH_VOL = 2      # 高波动最大收回天数


class VolatilityRegime:
    """波动率体制"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AdaptiveThresholds:
    """
    动态阈值系统

    根据股票的ATR百分比自动调整检测阈值，适应不同波动率的市场环境。
    """

    def __init__(self, atr_pct: float):
        """
        初始化动态阈值系统

        Args:
            atr_pct: ATR百分比（ATR / 当前价格 * 100）
        """
        self.atr_pct = atr_pct
        self.volatility_regime = self._classify_volatility_regime()

        # 根据波动率体制设置阈值
        self._set_thresholds_by_regime()

    def _classify_volatility_regime(self) -> str:
        """
        分类波动率体制

        Args:
            atr_pct: ATR百分比

        Returns:
            波动率体制（low/medium/high）
        """
        if self.atr_pct < 1.0:
            return VolatilityRegime.LOW
        elif self.atr_pct < 2.5:
            return VolatilityRegime.MEDIUM
        else:
            return VolatilityRegime.HIGH

    def _set_thresholds_by_regime(self):
        """根据波动率体制设置阈值"""

        if self.volatility_regime == VolatilityRegime.LOW:
            # 低波动：严格阈值
            self.SPRING_BREAKDOWN_MAX = 2.5      # Spring最大跌破幅度
            self.SPRING_RECOVERY_DAYS_MIN = 1    # Spring最小收回天数
            self.SPRING_RECOVERY_DAYS_MAX = 3    # Spring最大收回天数
            self.JOC_BODY_RATIO = 0.04            # JOC实体比例（4%）
            self.JOC_UPPER_SHADOW_RATIO = 0.3    # JOC上影线比例
            self.JOC_VOLUME_RATIO = 1.8          # JOC量能比例
            self.LPS_VOLUME_RATIO = 1.5          # LPS量能比例
            self.UPTHRUST_BREAKOUT_MAX = 2.0     # Upthrust最大突破幅度
            self.VSA_VOLUME_CUTOFF = 0.7         # VSA量能 cutoff

        elif self.volatility_regime == VolatilityRegime.MEDIUM:
            # 中波动：标准阈值
            self.SPRING_BREAKDOWN_MAX = 3.0      # Spring最大跌破幅度
            self.SPRING_RECOVERY_DAYS_MIN = 1
            self.SPRING_RECOVERY_DAYS_MAX = 3
            self.JOC_BODY_RATIO = 0.03            # JOC实体比例（3%）
            self.JOC_UPPER_SHADOW_RATIO = 0.35   # JOC上影线比例
            self.JOC_VOLUME_RATIO = 1.5          # JOC量能比例
            self.LPS_VOLUME_RATIO = 1.3          # LPS量能比例
            self.UPTHRUST_BREAKOUT_MAX = 3.0     # Upthrust最大突破幅度
            self.VSA_VOLUME_CUTOFF = 0.8         # VSA量能 cutoff

        else:  # HIGH volatility
            # 高波动：宽松阈值
            self.SPRING_BREAKDOWN_MAX = 5.0      # Spring最大跌破幅度
            self.SPRING_RECOVERY_DAYS_MIN = 1
            self.SPRING_RECOVERY_DAYS_MAX = 4    # 允许更长的收回时间
            self.JOC_BODY_RATIO = 0.02            # JOC实体比例（2%）
            self.JOC_UPPER_SHADOW_RATIO = 0.4    # JOC上影线比例
            self.JOC_VOLUME_RATIO = 1.2          # JOC量能比例
            self.LPS_VOLUME_RATIO = 1.2          # LPS量能比例
            self.UPTHRUST_BREAKOUT_MAX = 5.0     # Upthrust最大突破幅度
            self.VSA_VOLUME_CUTOFF = 0.9         # VSA量能 cutoff

    def get_thresholds_dict(self) -> Dict[str, Any]:
        """
        获取所有阈值字典

        Returns:
            包含所有阈值的字典
        """
        return {
            'volatility_regime': self.volatility_regime,
            'atr_pct': round(self.atr_pct, 2),
            'spring': {
                'breakdown_max_pct': self.SPRING_BREAKDOWN_MAX,
                'recovery_days_min': self.SPRING_RECOVERY_DAYS_MIN,
                'recovery_days_max': self.SPRING_RECOVERY_DAYS_MAX,
            },
            'joc': {
                'body_ratio': self.JOC_BODY_RATIO,
                'upper_shadow_ratio': self.JOC_UPPER_SHADOW_RATIO,
                'volume_ratio': self.JOC_VOLUME_RATIO,
            },
            'lps': {
                'volume_ratio': self.LPS_VOLUME_RATIO,
            },
            'upthrust': {
                'breakout_max_pct': self.UPTHRUST_BREAKOUT_MAX,
            },
            'vsa': {
                'volume_cutoff': self.VSA_VOLUME_CUTOFF,
            }
        }

    def __repr__(self) -> str:
        return (f"AdaptiveThresholds(regime={self.volatility_regime}, "
                f"atr_pct={self.atr_pct:.2f}%)")


class ThresholdAdapterFactory:
    """
    阈值适配器工厂

    提供静态方法创建适配的阈值配置
    """

    @staticmethod
    def create_from_dataframe(df, atr_period: int = 14) -> AdaptiveThresholds:
        """
        从DataFrame创建自适应阈值

        Args:
            df: 包含OHLCV数据的DataFrame
            atr_period: ATR计算周期

        Returns:
            AdaptiveThresholds实例
        """
        if df is None or len(df) < atr_period:
            logger.warning("数据不足，使用中等波动率阈值")
            return AdaptiveThresholds(atr_pct=1.5)

        try:
            # 计算ATR
            high = df['High']
            low = df['Low']
            close = df['Close'].shift(1)

            tr = pd.concat([
                high - low,
                (high - close).abs(),
                (low - close).abs()
            ], axis=1).max(axis=1)

            atr = tr.rolling(window=atr_period, min_periods=1).mean().iloc[-1]

            # 计算ATR百分比
            current_price = df['Close'].iloc[-1]
            atr_pct = (atr / current_price) * 100 if current_price > 0 else 1.5

            return AdaptiveThresholds(atr_pct=atr_pct)

        except Exception as e:
            logger.error(f"计算ATR失败: {e}")
            return AdaptiveThresholds(atr_pct=1.5)

    @staticmethod
    def create_from_atr(atr: float, current_price: float) -> AdaptiveThresholds:
        """
        从ATR值创建自适应阈值

        Args:
            atr: ATR值
            current_price: 当前价格

        Returns:
            AdaptiveThresholds实例
        """
        if current_price <= 0:
            logger.warning("当前价格无效，使用中等波动率阈值")
            return AdaptiveThresholds(atr_pct=1.5)

        atr_pct = (atr / current_price) * 100
        return AdaptiveThresholds(atr_pct=atr_pct)

    @staticmethod
    def get_default_thresholds() -> Dict[str, Any]:
        """
        获取默认阈值配置（中等波动率）

        Returns:
            默认阈值字典
        """
        adaptive = AdaptiveThresholds(atr_pct=1.5)
        return adaptive.get_thresholds_dict()


# 导入pandas（在类定义后导入避免循环依赖）
import pandas as pd