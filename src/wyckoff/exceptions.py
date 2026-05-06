#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析系统异常层次结构
"""

from .core.enums import ErrorCode

class WyckoffError(Exception):
    """威科夫分析基础异常"""
    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.SYSTEM_UNKNOWN):
        self.error_code = error_code
        super().__init__(message)

class DataFetchError(WyckoffError):
    """数据获取失败"""
    def __init__(self, symbol: str, reason: str, error_code: ErrorCode = ErrorCode.DATA_FETCH_FAILED):
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"获取 {symbol} 数据失败: {reason}", error_code)

class InsufficientDataError(WyckoffError):
    """数据不足"""
    def __init__(self, symbol: str, required: int, actual: int):
        self.symbol = symbol
        self.required = required
        self.actual = actual
        super().__init__(f"{symbol} 数据不足: 需要{required}天，实际{actual}天", ErrorCode.DATA_INSUFFICIENT_SAMPLES)

class AnalysisError(WyckoffError):
    """分析过程错误（基类）"""
    pass

class PatternDetectionError(AnalysisError):
    """形态检测错误"""
    def __init__(self, pattern_type: str, detail: str):
        self.pattern_type = pattern_type
        self.detail = detail
        super().__init__(f"形态检测失败 [{pattern_type}]: {detail}", ErrorCode.PATTERN_LOGIC_ERROR)

class PhaseIdentificationError(AnalysisError):
    """阶段识别错误"""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"阶段识别失败: {detail}")

class LawAnalysisError(AnalysisError):
    """威科夫法则分析错误"""
    def __init__(self, law_type: str, detail: str):
        self.law_type = law_type
        self.detail = detail
        super().__init__(f"法则分析失败 [{law_type}]: {detail}")

class ConfigurationError(WyckoffError):
    """配置错误"""
    def __init__(self, param: str, reason: str):
        self.param = param
        self.reason = reason
        super().__init__(f"配置错误 [{param}]: {reason}")

class CacheError(WyckoffError):
    """缓存错误"""
    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"缓存错误 [{key}]: {reason}")

class SerializationError(WyckoffError):
    """序列化错误"""
    def __init__(self, model: str, detail: str):
        self.model = model
        self.detail = detail
        super().__init__(f"序列化失败 [{model}]: {detail}")
