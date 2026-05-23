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
    def is_accumulation(phase: Any) -> bool:
        """判断是否为吸筹阶段"""
        p_str = phase.value if hasattr(phase, 'value') else str(phase)
        return bool(re.search(r'\bAccumulation\b', p_str, re.I)) or '建仓' in p_str

    @staticmethod
    def is_distribution(phase: Any) -> bool:
        """判断是否为派发阶段"""
        p_str = phase.value if hasattr(phase, 'value') else str(phase)
        return bool(re.search(r'\bDistribution\b', p_str, re.I)) or '出货' in p_str

    @staticmethod
    def is_markup(phase: Any) -> bool:
        """判断是否为上涨阶段"""
        p_str = phase.value if hasattr(phase, 'value') else str(phase)
        return bool(re.search(r'\bMarkup\b', p_str, re.I)) or '上涨' in p_str

    @staticmethod
    def is_markdown(phase: Any) -> bool:
        """判断是否为下跌阶段"""
        p_str = phase.value if hasattr(phase, 'value') else str(phase)
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


def normalize_choch_direction(direction: Any) -> Optional[str]:
    """将 CHoCH direction 统一为 bullish / bearish（兼容 up/down 等别名）。"""
    if direction is None:
        return None
    d = str(direction).lower()
    if d in ('up', 'bullish', 'long'):
        return 'bullish'
    if d in ('down', 'bearish', 'short'):
        return 'bearish'
    return None


def is_bullish_choch(direction: Any) -> bool:
    return normalize_choch_direction(direction) == 'bullish'


def is_bearish_choch(direction: Any) -> bool:
    return normalize_choch_direction(direction) == 'bearish'


def continuous_price_confirmation(
    df: pd.DataFrame,
    days: int,
    phase_label: str = '',
    *,
    require_volume: bool = False,
) -> bool:
    """阶段感知的连续价格确认（D→E：吸筹需连涨、派发需连跌；可选量能同向确认）。"""
    if df is None or len(df) < days + 1:
        return False
    try:
        tail = df.tail(days + 1)
        changes = tail['Close'].pct_change().dropna()
        if len(changes) == 0:
            return False
        positive_ratio = (changes > 0).sum() / len(changes)
        negative_ratio = (changes < 0).sum() / len(changes)
        price_ok = False
        if PhaseAdapter.is_accumulation(phase_label) or PhaseAdapter.is_markup(phase_label):
            price_ok = positive_ratio >= 0.8 and negative_ratio <= 0.25
        elif PhaseAdapter.is_distribution(phase_label) or PhaseAdapter.is_markdown(phase_label):
            price_ok = negative_ratio >= 0.8 and positive_ratio <= 0.25
        else:
            price_ok = positive_ratio >= 0.8 or negative_ratio >= 0.8

        if not price_ok:
            return False
        if not require_volume or 'Volume' not in tail.columns:
            return True

        vol = tail['Volume'].iloc[1:]
        up_mask = changes > 0
        down_mask = changes < 0
        up_vol = float(vol[up_mask].mean()) if up_mask.any() else 0.0
        down_vol = float(vol[down_mask].mean()) if down_mask.any() else 0.0
        if PhaseAdapter.is_accumulation(phase_label) or PhaseAdapter.is_markup(phase_label):
            if down_vol <= 0:
                up_vols = vol[up_mask]
                if len(up_vols) >= 2:
                    return float(up_vols.iloc[-1]) >= float(up_vols.iloc[0]) * 0.85
                return len(up_vols) > 0
            return up_vol >= down_vol * 0.85
        if PhaseAdapter.is_distribution(phase_label) or PhaseAdapter.is_markdown(phase_label):
            if up_vol <= 0:
                down_vols = vol[down_mask]
                if len(down_vols) >= 2:
                    return float(down_vols.iloc[-1]) >= float(down_vols.iloc[0]) * 0.85
                return len(down_vols) > 0
            return down_vol >= up_vol * 0.85
        return True
    except Exception:
        return False


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
                logger.error(f"Type conversion failed for string '{value}': {e}")
                raise ValueError(f"无法将字符串 '{value}' 转换为 Timestamp: {e}")

        logger.error(f"Unsupported conversion type: {type(value).__name__}")
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

    @staticmethod
    def parse_date_naive(value: Any) -> Optional[pd.Timestamp]:
        """
        将日期值统一转换为 tz-naive pd.Timestamp（用于日期比较）

        代码中存在多个 _parse_date 的重复实现，此方法统一替换：
        - pattern_detector.py:_parse_date
        - event_arbitrator.py:_parse_date
        - sos_sow_analyzer.py:_parse_date
        - sequence_validator.py:_to_ts
        """
        from typing import Optional
        if value is None:
            return None
        try:
            ts = pd.to_datetime(value)
            if isinstance(ts, pd.DatetimeIndex):
                ts = ts[0]
            # 统一转为 tz-naive 避免时区比较错误
            if hasattr(ts, 'tz') and ts.tz is not None:
                return ts.tz_localize(None)
            return ts
        except (ValueError, TypeError, Exception):
            return None
