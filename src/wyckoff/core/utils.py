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
        if isinstance(phase, WyckoffPhase):
            # 虽然 WyckoffPhase 目前只有 A-E，但保留对 Enum 的类型检查以备扩展
            return False 
        p_str = str(phase)
        return bool(re.search(r'\bAccumulation\b', p_str, re.I)) or '建仓' in p_str

    @staticmethod
    def is_distribution(phase: Union[str, WyckoffPhase]) -> bool:
        if isinstance(phase, WyckoffPhase):
            return False
        p_str = str(phase)
        return bool(re.search(r'\bDistribution\b', p_str, re.I)) or '出货' in p_str

    @staticmethod
    def is_markup(phase: Union[str, WyckoffPhase]) -> bool:
        if isinstance(phase, WyckoffPhase):
            return False
        p_str = str(phase)
        return bool(re.search(r'\bMarkup\b', p_str, re.I)) or '上涨' in p_str

    @staticmethod
    def is_markdown(phase: Union[str, WyckoffPhase]) -> bool:
        if isinstance(phase, WyckoffPhase):
            return False
        p_str = str(phase)
        return bool(re.search(r'\bMarkdown\b', p_str, re.I)) or '下跌' in p_str

    @staticmethod
    def is_phase_c(phase: Union[str, WyckoffPhase]) -> bool:
        """判断是否为 Phase C"""
        if isinstance(phase, WyckoffPhase):
            return phase == WyckoffPhase.PHASE_C
        return 'Phase C' in str(phase)

    @staticmethod
    def is_phase_d(phase: Union[str, WyckoffPhase]) -> bool:
        """判断是否为 Phase D"""
        if isinstance(phase, WyckoffPhase):
            return phase == WyckoffPhase.PHASE_D
        return 'Phase D' in str(phase)

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
            value: 可以是 pd.Timestamp, str, datetime.datetime, np.datetime64 等类型

        Returns:
            pd.Timestamp 或 None（转换失败时）
        """
        if value is None:
            return None

        # 已经是 Timestamp，直接返回并进行时区归一化
        if isinstance(value, pd.Timestamp):
            return value if value.tz is not None else value.tz_localize('UTC')

        # 处理 datetime 对象
        if isinstance(value, (datetime.datetime, datetime.date)):
            ts = pd.Timestamp(value)
            return ts if ts.tz is not None else ts.tz_localize('UTC')

        # 处理 numpy 标量或 datetime64
        if isinstance(value, (np.datetime64, np.generic)) or hasattr(value, 'date'):
            try:
                ts = pd.Timestamp(value)
                return ts if ts.tz is None else ts.tz_convert('UTC')
            except (ValueError, TypeError):
                pass

        # 字符串类型：使用更健壮的 pd.to_datetime
        if isinstance(value, str):
            if not value.strip():
                return None
            try:
                ts = pd.to_datetime(value)
                if isinstance(ts, pd.DatetimeIndex): # 某些情况可能返回 Index
                    ts = ts[0]
                return ts if ts.tz is not None else ts.tz_localize('UTC')
            except Exception as e:
                raise ValueError(f"无法将字符串 '{value}' 转换为 Timestamp: {e}")

        raise ValueError(f"不支持的转换类型: {type(value).__name__}")

    @staticmethod
    def is_date_like(value: Any) -> bool:
        """
        检查值是否可能为日期类型

        Args:
            value: 要检查的值

        Returns:
            是否可能为日期类型
        """
        if value is None:
            return False
        if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date, np.datetime64)):
            return True
        if isinstance(value, str):
            # 简单的启发式检查：包含数字且长度合理
            return len(value) >= 8 and any(c.isdigit() for c in value) and any(c in value for c in '-/: ')
        return False

    @staticmethod
    def safe_to_timestamp(value: Any, default: Any = None) -> Optional[pd.Timestamp]:
        """
        安全地将值转换为 Timestamp，失败时返回默认值
        """
        try:
            return TypeConverter.to_timestamp(value)
        except (ValueError, TypeError, Exception) as e:
            logger.debug(f"safe_to_timestamp: 转换失败 [value={value}, type={type(value).__name__}]: {e}")
            return default
