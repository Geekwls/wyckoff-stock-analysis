import pandas as pd
import datetime
import re
import logging
import numpy as np
from typing import Dict, List, Optional, Union, Any
from .enums import WyckoffPhase, MarketSide

logger = logging.getLogger(__name__)

class PhaseAdapter:
    """负责解析和分类阶段（支持 Enum 和 String，实现双轨期兼容）"""
    
    @staticmethod
    def is_accumulation(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return bool(re.search(r'\bAccumulation\b', p_str)) or '建仓' in p_str

    @staticmethod
    def is_distribution(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return bool(re.search(r'\bDistribution\b', p_str)) or '出货' in p_str

    @staticmethod
    def is_markup(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return bool(re.search(r'\bMarkup\b', p_str)) or '上涨' in p_str

    @staticmethod
    def is_markdown(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return bool(re.search(r'\bMarkdown\b', p_str)) or '下跌' in p_str

    @staticmethod
    def is_phase_c(phase: Union[str, WyckoffPhase]) -> bool:
        """判断是否为 Phase C"""
        p_str = str(phase)
        return 'Phase C' in p_str or isinstance(phase, WyckoffPhase) and phase == WyckoffPhase.PHASE_C

    @staticmethod
    def is_phase_d(phase: Union[str, WyckoffPhase]) -> bool:
        """判断是否为 Phase D"""
        p_str = str(phase)
        return 'Phase D' in p_str or isinstance(phase, WyckoffPhase) and phase == WyckoffPhase.PHASE_D

    @staticmethod
    def is_late_stage(phase: Union[str, WyckoffPhase]) -> bool:
        """判断是否为可入场/后期阶段 (C/D)"""
        return PhaseAdapter.is_phase_c(phase) or PhaseAdapter.is_phase_d(phase)

    @staticmethod
    def get_market_side(phase: Union[str, WyckoffPhase]) -> str:
        """返回买方(bullish)或卖方(bearish)市场侧"""
        # 优先级：Accumulation/Markup 为 Bullish
        if PhaseAdapter.is_accumulation(phase) or PhaseAdapter.is_markup(phase):
            return MarketSide.BULLISH.value
        # Distribution/Markdown 为 Bearish
        if PhaseAdapter.is_distribution(phase) or PhaseAdapter.is_markdown(phase):
            return MarketSide.BEARISH.value
        
        return MarketSide.NEUTRAL.value

# 为了兼容性，保留 PhaseClassifier 别名
PhaseClassifier = PhaseAdapter


class TypeConverter:
    """
    统一的类型转换工具类

    解决代码中类型检查分散的问题，提供统一的类型转换接口。
    支持处理 pd.Timestamp、str、datetime 等类型的转换。
    """

    @staticmethod
    def to_timestamp(value: Any) -> Optional[pd.Timestamp]:
        """
        将各种日期类型转换为 pd.Timestamp

        Args:
            value: 可以是 pd.Timestamp, str, datetime.datetime 等类型

        Returns:
            pd.Timestamp 或 None（转换失败时）

        Examples:
            >>> TypeConverter.to_timestamp('2024-01-01')
            Timestamp('2024-01-01 00:00:00')
            >>> TypeConverter.to_timestamp(pd.Timestamp('2024-01-01'))
            Timestamp('2024-01-01 00:00:00')
        """
        if value is None:
            return None

        # 已经是 Timestamp，直接返回
        if isinstance(value, pd.Timestamp):
            return value

        # 字符串类型
        if isinstance(value, str):
            try:
                return pd.Timestamp(value)
            except (ValueError, TypeError) as e:
                raise ValueError(f"无法将字符串 '{value}' 转换为 Timestamp: {e}")

        # datetime.datetime 对象
        if isinstance(value, datetime.datetime):
            return pd.Timestamp(value)

        # datetime.date 对象
        if isinstance(value, datetime.date):
            return pd.Timestamp(value)

        # numpy.datetime64 对象
        if isinstance(value, (np.datetime64, np.generic)) or hasattr(value, 'date'):
            try:
                return pd.Timestamp(value)
            except Exception:
                pass

        # 其他类型，尝试转换为字符串后再转换
        try:
            return pd.Timestamp(str(value))
        except (ValueError, TypeError) as e:
            raise ValueError(f"无法将类型 {type(value).__name__} 转换为 Timestamp: {e}")

    @staticmethod
    def is_date_like(value: Any) -> bool:
        """
        检查值是否为日期类型（pd.Timestamp, str, datetime 等）

        Args:
            value: 要检查的值

        Returns:
            是否为日期类型

        Examples:
            >>> TypeConverter.is_date_like('2024-01-01')
            True
            >>> TypeConverter.is_date_like(pd.Timestamp('2024-01-01'))
            True
            >>> TypeConverter.is_date_like(123)
            False
        """
        if value is None:
            return False
        return isinstance(value, (pd.Timestamp, str, datetime.datetime, datetime.date, np.datetime64))

    @staticmethod
    def safe_to_timestamp(value: Any, default: Any = None) -> Optional[pd.Timestamp]:
        """
        安全地将值转换为 Timestamp，失败时返回默认值

        Args:
            value: 要转换的值
            default: 转换失败时的默认值

        Returns:
            pd.Timestamp 或默认值

        Examples:
            >>> TypeConverter.safe_to_timestamp('2024-01-01')
            Timestamp('2024-01-01 00:00:00')
            >>> TypeConverter.safe_to_timestamp('invalid', default=None)
            None
        """
        try:
            return TypeConverter.to_timestamp(value)
        except (ValueError, TypeError) as e:
            logger.debug(f"safe_to_timestamp: 转换失败 [value={value}, type={type(value).__name__}]: {e}")
            return default
