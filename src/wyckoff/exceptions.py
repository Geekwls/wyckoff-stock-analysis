#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析系统异常层次结构 (P0 重构版)

分类原则：
1. DataError: 数据获取、网络、IO、字段缺失等基础设施问题。
2. CalculationError: 数学计算、算法逻辑、状态机更新等内部计算问题。
3. PatternNotFoundError: 明确的“无信号”结果，非错误，用于业务逻辑区分。
4. ConfigurationError: 参数配置、环境设置问题。
"""

from .core.enums import ErrorCode
from typing import Optional

class WyckoffError(Exception):
    """威科夫分析基础异常"""
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.SYSTEM_UNKNOWN, retriable: bool = False):
        self.error_code = error_code
        self.retriable = retriable
        super().__init__(message)

# ============================================================
# 1. 数据层异常 (Data Errors)
# ============================================================

class DataError(WyckoffError):
    """数据获取或完整性错误 (网络、限流、字段缺失)"""
    def __init__(self, message: str, symbol: str = None, retriable: bool = False):
        code = ErrorCode.DATA_SOURCE_UNAVAILABLE if retriable else ErrorCode.DATA_FETCH_FAILED
        self.symbol = symbol
        super().__init__(message, error_code=code, retriable=retriable)

class DataFetchError(DataError):
    """数据获取失败 (网络/API错误)"""
    def __init__(self, symbol: str, reason: str, retriable: bool = False):
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"获取 {symbol} 数据失败: {reason}", symbol=symbol, retriable=retriable)

class InsufficientDataError(DataError):
    """数据样本不足"""
    def __init__(self, symbol: str, required: int, actual: int):
        self.symbol = symbol
        self.required = required
        self.actual = actual
        super().__init__(f"{symbol} 数据不足: 需要{required}天，实际{actual}天", symbol=symbol)

class MissingFieldError(DataError):
    """必要数据字段缺失"""
    def __init__(self, field: str, symbol: str = None):
        self.field = field
        super().__init__(f"必要字段缺失: {field}", symbol=symbol)

# ============================================================
# 2. 计算层异常 (Calculation Errors)
# ============================================================

class CalculationError(WyckoffError):
    """数学计算或算法逻辑错误"""
    def __init__(self, component: str, detail: str):
        self.component = component
        self.detail = detail
        super().__init__(f"计算异常 [{component}]: {detail}", error_code=ErrorCode.SYSTEM_UNKNOWN)

class StateEngineError(CalculationError):
    """状态机更新或贝叶斯滤波错误"""
    def __init__(self, detail: str):
        super().__init__("StateEngine", detail)

# ============================================================
# 3. 业务逻辑异常 (Business Logic)
# ============================================================

class AnalysisError(WyckoffError):
    """分析过程错误（基类）"""
    pass

class PatternDetectionError(AnalysisError):
    """形态检测过程中的逻辑错误"""
    def __init__(self, pattern_type: str, detail: str):
        self.pattern_type = pattern_type
        self.detail = detail
        super().__init__(f"形态检测逻辑错误 [{pattern_type}]: {detail}", ErrorCode.PATTERN_LOGIC_ERROR)

class PatternNotFoundError(AnalysisError):
    """未检测到目标形态 (非错误，属于正常业务结果)"""
    def __init__(self, pattern_type: str, reason: str = "未满足检测条件"):
        self.pattern_type = pattern_type
        self.reason = reason
        message = f"未检测到 {pattern_type}: {reason}"
        super().__init__(message, error_code=ErrorCode.PATTERN_NOT_FOUND)

class PhaseIdentificationError(AnalysisError):
    """阶段识别逻辑错误"""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"阶段识别逻辑失败: {detail}", ErrorCode.PHASE_IDENTIFICATION_ERROR)

class LawAnalysisError(AnalysisError):
    """威科夫法则分析错误"""
    def __init__(self, law_type: str, detail: str):
        self.law_type = law_type
        self.detail = detail
        super().__init__(f"法则分析逻辑错误 [{law_type}]: {detail}")

# ============================================================
# 4. 系统与配置异常 (System & Config)
# ============================================================

class ConfigurationError(WyckoffError):
    """配置参数错误"""
    def __init__(self, param: str, reason: str):
        self.param = param
        self.reason = reason
        super().__init__(f"配置错误 [{param}]: {reason}", error_code=ErrorCode.SYSTEM_CONFIG_ERROR)

class CacheError(WyckoffError):
    """缓存读写错误"""
    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"缓存错误 [{key}]: {reason}", error_code=ErrorCode.SYSTEM_CACHE_ERROR)

class SerializationError(WyckoffError):
    """数据序列化/反序列化错误"""
    def __init__(self, model: str, detail: str):
        self.model = model
        self.detail = detail
        super().__init__(f"序列化失败 [{model}]: {detail}")
