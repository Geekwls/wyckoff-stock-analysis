from enum import Enum

class ErrorCode(str, Enum):
    """标准化错误码"""
    DATA_FETCH_ERROR = "DATA_FETCH_ERROR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    ANALYSIS_ERROR = "ANALYSIS_ERROR"
    PATTERN_DETECTION_ERROR = "PATTERN_DETECTION_ERROR"
    PHASE_IDENTIFICATION_ERROR = "PHASE_IDENTIFICATION_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"

class WyckoffPhase(str, Enum):
    """威科夫阶段枚举"""
    PHASE_A = "Phase A"
    PHASE_B = "Phase B"
    PHASE_C = "Phase C"
    PHASE_D = "Phase D"
    PHASE_E = "Phase E"
    UNKNOWN = "Unknown"

class MarketEnvironment(str, Enum):
    """市场环境量化枚举"""
    STRONG_BULL = "Strong Bull"
    BULL = "Bull"
    WEAK_BULL = "Weak Bull"
    RANGE_BOUND = "Range Bound"
    BEAR = "Bear"
    STRONG_BEAR = "Strong Bear"
    UNKNOWN = "Unknown"

class MarketSide(str, Enum):
    """市场侧倾向"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

class SignalType(str, Enum):
    """信号类型枚举"""
    SPRING = "spring"
    UPTHRUST = "upthrust"
    SOS = "sos"
    SOW = "sow"
    LPS = "lps"
    LPSY = "lpsy"
    CLIMAX = "climax"
    AR = "automatic_reaction"
    ST = "secondary_test"
    JOC = "joc"
    FTI = "fti"
