#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标计算工具 (Technical Indicators Calculator)

提供统一的技术指标计算接口，避免代码重复。
"""

import pandas as pd
import numpy as np
from typing import Optional, Union


class TechnicalIndicators:
    """
    技术指标计算工具类

    提供常用的技术指标计算方法，避免代码重复。
    """

    @staticmethod
    def sma(series: pd.Series, period: int, min_periods: Optional[int] = None) -> pd.Series:
        """
        简单移动平均 (Simple Moving Average)

        Args:
            series: 价格或成交量序列
            period: 周期
            min_periods: 最小计算周期（默认为 period）

        Returns:
            移动平均序列
        """
        if min_periods is None:
            min_periods = 1 if period >= 20 else period
        return series.rolling(window=period, min_periods=min_periods).mean()

    @staticmethod
    def ema(series: pd.Series, period: int, min_periods: Optional[int] = None) -> pd.Series:
        """
        指数移动平均 (Exponential Moving Average)

        Args:
            series: 价格或成交量序列
            period: 周期
            min_periods: 最小计算周期

        Returns:
            指数移动平均序列
        """
        if min_periods is None:
            min_periods = 1
        return series.ewm(span=period, min_periods=min_periods, adjust=False).mean()

    @staticmethod
    def volume_ma(df: pd.DataFrame, period: int = 20, min_periods: Optional[int] = None) -> pd.Series:
        """
        成交量移动平均

        Args:
            df: 包含 Volume 列的 DataFrame
            period: 周期（默认20）
            min_periods: 最小计算周期

        Returns:
            成交量移动平均序列

        Note:
            如果 Volume_MA{period} 列已存在，直接返回该列
            否则计算并返回新的移动平均
        """
        volume_col = f'Volume_MA{period}'

        # 如果已经计算过，直接返回
        if volume_col in df.columns:
            return df[volume_col]

        # 否则计算
        return TechnicalIndicators.sma(df['Volume'], period, min_periods)

    @staticmethod
    def price_ma(df: pd.DataFrame, period: int, price_col: str = 'Close', min_periods: Optional[int] = None) -> pd.Series:
        """
        价格移动平均

        Args:
            df: 包含价格列的 DataFrame
            period: 周期
            price_col: 价格列名（默认 Close）
            min_periods: 最小计算周期

        Returns:
            价格移动平均序列
        """
        return TechnicalIndicators.sma(df[price_col], period, min_periods)

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14, min_periods: Optional[int] = None) -> pd.Series:
        """
        平均真实波幅 (Average True Range)

        Args:
            df: 包含 High, Low, Close 列的 DataFrame
            period: 周期（默认14）
            min_periods: 最小计算周期

        Returns:
            ATR 序列
        """
        if min_periods is None:
            min_periods = 1

        high = pd.to_numeric(df['High'], errors='coerce')
        low = pd.to_numeric(df['Low'], errors='coerce')
        close_prev = pd.to_numeric(df['Close'], errors='coerce').shift(1)

        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=min_periods).mean()

        return pd.Series(atr, index=df.index, name='ATR')

    @staticmethod
    def rsi(df: pd.DataFrame, period: int = 14, price_col: str = 'Close') -> pd.Series:
        """
        相对强弱指数 (Relative Strength Index)

        Args:
            df: 包含价格列的 DataFrame
            period: 周期（默认14）
            price_col: 价格列名（默认 Close）

        Returns:
            RSI 序列
        """
        delta = df[price_col].diff()
        gain = (delta.where(delta > 0, 0))
        loss = (-delta.where(delta < 0, 0))

        # 使用 Wilder's Smoothing
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, float('nan'))
        rsi = 100 - (100 / (1 + rs.fillna(0)))

        return pd.Series(rsi, index=df.index, name='RSI')

    @staticmethod
    def rolling_max(df: pd.DataFrame, column: str, period: int, min_periods: Optional[int] = None) -> pd.Series:
        """
        滚动最大值

        Args:
            df: DataFrame
            column: 列名
            period: 周期
            min_periods: 最小计算周期

        Returns:
            滚动最大值序列
        """
        if min_periods is None:
            min_periods = 1
        return df[column].rolling(window=period, min_periods=min_periods).max()

    @staticmethod
    def rolling_min(df: pd.DataFrame, column: str, period: int, min_periods: Optional[int] = None) -> pd.Series:
        """
        滚动最小值

        Args:
            df: DataFrame
            column: 列名
            period: 周期
            min_periods: 最小计算周期

        Returns:
            滚动最小值序列
        """
        if min_periods is None:
            min_periods = 1
        return df[column].rolling(window=period, min_periods=min_periods).min()

    @staticmethod
    def bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0, price_col: str = 'Close') -> dict:
        """
        布林带 (Bollinger Bands)

        Args:
            df: DataFrame
            period: 周期（默认20）
            std_dev: 标准差倍数（默认2）
            price_col: 价格列名（默认 Close）

        Returns:
            包含 upper, middle, lower 的字典
        """
        middle = TechnicalIndicators.sma(df[price_col], period)
        std = df[price_col].rolling(window=period).std()
        upper = middle + std * std_dev
        lower = middle - std * std_dev

        return {
            'upper': upper,
            'middle': middle,
            'lower': lower
        }

    @staticmethod
    def get_volume_ratio(df: pd.DataFrame, current_volume: Optional[float] = None, period: int = 20) -> pd.Series:
        """
        计算成交量比率（当前成交量 / 平均成交量）

        Args:
            df: 包含 Volume 列的 DataFrame
            current_volume: 当前成交量（如果为 None，使用 df 的最后一行）
            period: 均线周期（默认20）

        Returns:
            成交量比率序列
        """
        vol_ma = TechnicalIndicators.volume_ma(df, period)
        return df['Volume'] / vol_ma.replace(0, 1)


# 便捷函数别名
def SMA(series: pd.Series, period: int, min_periods: Optional[int] = None) -> pd.Series:
    """简单移动平均便捷函数"""
    return TechnicalIndicators.sma(series, period, min_periods)


def EMA(series: pd.Series, period: int, min_periods: Optional[int] = None) -> pd.Series:
    """指数移动平均便捷函数"""
    return TechnicalIndicators.ema(series, period, min_periods)


def ATR(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR 便捷函数"""
    return TechnicalIndicators.atr(df, period)


def RSI(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI 便捷函数"""
    return TechnicalIndicators.rsi(df, period)


def VolumeMA(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """成交量移动平均便捷函数"""
    return TechnicalIndicators.volume_ma(df, period)
