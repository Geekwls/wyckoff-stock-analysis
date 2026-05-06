from enum import Enum

class ErrorCode(str, Enum):
    """标准化错误码（统一错误码定义）"""

    # 数据层错误 (DATA_*)
    DATA_FETCH_FAILED = "DATA_FETCH_FAILED"
    DATA_SYMBOL_NOT_FOUND = "DATA_SYMBOL_NOT_FOUND"
    DATA_INSUFFICIENT_SAMPLES = "DATA_INSUFFICIENT_SAMPLES"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"

    # 形态识别错误 (PATTERN_*)
    PATTERN_NOT_FOUND = "PATTERN_NOT_FOUND"
    PATTERN_AMBIGUOUS = "PATTERN_AMBIGUOUS"
    PATTERN_LOGIC_ERROR = "PATTERN_LOGIC_ERROR"

    # 系统层错误 (SYSTEM_*)
    SYSTEM_CONFIG_ERROR = "SYSTEM_CONFIG_ERROR"
    SYSTEM_CACHE_ERROR = "SYSTEM_CACHE_ERROR"
    SYSTEM_TIMEOUT = "SYSTEM_TIMEOUT"
    SYSTEM_UNKNOWN = "SYSTEM_UNKNOWN"

    # 鉴权/权限 (AUTH_*)
    AUTH_INVALID_API_KEY = "AUTH_INVALID_API_KEY"
    AUTH_QUOTA_EXCEEDED = "AUTH_QUOTA_EXCEEDED"

    # 兼容性别名（保持向后兼容）
    DATA_FETCH_ERROR = "DATA_FETCH_FAILED"  # 别名，指向 DATA_FETCH_FAILED
    INSUFFICIENT_DATA = "DATA_INSUFFICIENT_SAMPLES"  # 别名
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    ANALYSIS_ERROR = "ANALYSIS_ERROR"
    PATTERN_DETECTION_ERROR = "PATTERN_LOGIC_ERROR"  # 别名
    PHASE_IDENTIFICATION_ERROR = "PHASE_IDENTIFICATION_ERROR"
    CONFIGURATION_ERROR = "SYSTEM_CONFIG_ERROR"  # 别名
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
