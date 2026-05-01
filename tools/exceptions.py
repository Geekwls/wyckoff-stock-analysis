#!/usr/bin/env python3
# -*- coding: utf-8 -*-

class WyckoffError(Exception):
    """威科夫分析基础异常"""
    pass

class DataFetchError(WyckoffError):
    """数据获取失败"""
    def __init__(self, symbol: str, reason: str):
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"获取 {symbol} 数据失败: {reason}")

class InsufficientDataError(WyckoffError):
    """数据不足"""
    def __init__(self, symbol: str, required: int, actual: int):
        self.required = required
        self.actual = actual
        super().__init__(f"{symbol} 数据不足: 需要{required}天，实际{actual}天")

class AnalysisError(WyckoffError):
    """分析过程错误"""
    pass
