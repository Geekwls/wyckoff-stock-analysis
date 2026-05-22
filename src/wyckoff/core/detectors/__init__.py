"""
威科夫形态检测器模块

包含各种形态检测器：
- BaseDetector: 基础检测器类
- StrengthWeaknessDetector: 强弱势信号检测器 (SOS/SOW/LPS/LPSY)
- ClassicPatternDetector: 经典威科夫形态检测器 (JOC/FTI/UTAD等)
- MengReversalDetector: 孟洪涛反转形态检测器
- MengTrendDetector: 孟洪涛趋势形态检测器
- MengVSADetector: 孟洪涛VSA检测器
- TradingRangeDetector: 交易区间检测器
- ChannelDetector: 通道检测器
- TrendDetector: 趋势检测器
- VSADetector: VSA检测器
- PhaseIdentifier: 阶段识别器
- ReversalDetector: 反转检测器
- PSDetector: 初次支撑检测器
- PSYDetector: 初次供应检测器
"""

from .base_detector import BaseDetector, USE_VECTORIZED
from .strength_weakness_detector import StrengthWeaknessDetector
from .classic_pattern_detector import ClassicPatternDetector
from .meng_reversal_detector import MengReversalDetector
from .meng_trend_detector import MengTrendDetector
from .meng_vsa_detector import MengVsaDetector
from .trading_range_detector import TradingRangeDetector
from .channel_detector import ChannelDetector
from .trend_detector import TrendDetector
from .vsa_detector import VsaDetector
from .phase_identifier import PhaseIdentifier
from .reversal_detector import ReversalDetector
from .ps_detector import PsDetector
from .psy_detector import PsyDetector

__all__ = [
    'BaseDetector',
    'USE_VECTORIZED',
    'StrengthWeaknessDetector',
    'ClassicPatternDetector',
    'MengReversalDetector',
    'MengTrendDetector',
    'MengVsaDetector',
    'TradingRangeDetector',
    'ChannelDetector',
    'TrendDetector',
    'VsaDetector',
    'PhaseIdentifier',
    'ReversalDetector',
    'PsDetector',
    'PsyDetector'
]