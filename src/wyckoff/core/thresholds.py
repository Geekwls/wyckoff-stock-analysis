#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态阈值自适应系统
"""
import logging
import pandas as pd
from typing import Dict, Any
from dataclasses import dataclass

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
# 威科夫理论标准：Spring必须在1-3天内收回支撑位
# 失败Spring：价格3+天未收回 → 真下跌开始
MAX_RECOVERY_DAYS_STANDARD = 3      # 统一标准：3天（所有波动率体制）
MIN_RECOVERY_DAYS_STANDARD = 1      # 最小收回天数


@dataclass(frozen=True)
class VolatilityThresholds:
    """波动率体制阈值配置"""
    spring_breakdown_max: float
    joc_body_ratio: float
    joc_upper_shadow_ratio: float
    joc_volume_ratio: float
    lps_volume_ratio: float
    upthrust_breakout_max: float
    vsa_volume_cutoff: float


# 不同波动率体制的阈值配置
VOLATILITY_THRESHOLDS = {
    "low": VolatilityThresholds(
        spring_breakdown_max=2.5,
        joc_body_ratio=0.04,
        joc_upper_shadow_ratio=0.3,
        joc_volume_ratio=1.8,
        lps_volume_ratio=1.5,
        upthrust_breakout_max=2.0,
        vsa_volume_cutoff=0.7
    ),
    "medium": VolatilityThresholds(
        spring_breakdown_max=3.0,
        joc_body_ratio=0.03,
        joc_upper_shadow_ratio=0.35,
        joc_volume_ratio=1.5,
        lps_volume_ratio=1.3,
        upthrust_breakout_max=3.0,
        vsa_volume_cutoff=0.8
    ),
    "high": VolatilityThresholds(
        spring_breakdown_max=5.0,
        joc_body_ratio=0.02,
        joc_upper_shadow_ratio=0.4,
        joc_volume_ratio=1.2,
        lps_volume_ratio=1.2,
        upthrust_breakout_max=5.0,
        vsa_volume_cutoff=0.9
    )
}


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
        # 获取对应体制的阈值配置
        thresholds = VOLATILITY_THRESHOLDS.get(self.volatility_regime, VOLATILITY_THRESHOLDS["medium"])

        # 应用阈值配置
        self.SPRING_BREAKDOWN_MAX = thresholds.spring_breakdown_max
        self.SPRING_RECOVERY_DAYS_MIN = MIN_RECOVERY_DAYS_STANDARD
        self.SPRING_RECOVERY_DAYS_MAX = MAX_RECOVERY_DAYS_STANDARD
        self.JOC_BODY_RATIO = thresholds.joc_body_ratio
        self.JOC_UPPER_SHADOW_RATIO = thresholds.joc_upper_shadow_ratio
        self.JOC_VOLUME_RATIO = thresholds.joc_volume_ratio
        self.LPS_VOLUME_RATIO = thresholds.lps_volume_ratio
        self.UPTHRUST_BREAKOUT_MAX = thresholds.upthrust_breakout_max
        self.VSA_VOLUME_CUTOFF = thresholds.vsa_volume_cutoff

        # 孟洪涛增强器专用阈值（不随波动率体制变化）
        self._set_meng_thresholds()

    def _set_meng_thresholds(self):
        """设置孟洪涛增强器专用阈值"""
        self.MENG_SPRING_BREAKDOWN_MIN = 1.0
        self.MENG_SPRING_BREAKDOWN_MAX = 3.0
        self.MENG_SPRING_RECOVERY_CLOSE_POS = 0.7
        self.MENG_SPRING_VOL_RATIO = 1.0
        self.MENG_VSA_BODY_RATIO = 0.3
        self.MENG_VSA_VOL_RATIO = 0.6
        self.MENG_VSA_CLOSE_POS = 0.5
        self.MENG_STOPPING_VOL_RATIO = 1.5
        self.MENG_STOPPING_BODY_RATIO = 0.3
        self.MENG_STOPPING_SHADOW_RATIO = 0.3

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