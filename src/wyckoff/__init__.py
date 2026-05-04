#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析库 - 公共 API 导出
Wyckoff Analysis Library - Public API Exports

这是纯库层，提供威科夫分析的公共 API。
应用层（CLI/MCP/其他）应仅从此处导入。
"""

# 核心分析器
from .facade import WyckoffAnalyzer, batch_scan

# 配置
from .config.settings import WyckoffConfig, WyckoffThresholds

# 异常
from .exceptions import *

# Schema
from .schemas import *

# 版本信息
__version__ = "4.1.0"
__author__ = "Wyckoff Analysis Team"

# 公共 API 导出
__all__ = [
    # 核心分析器
    "WyckoffAnalyzer",
    "batch_scan",

    # 配置
    "WyckoffConfig",
    "WyckoffThresholds",

    # 异常
    "WyckoffError",
    "DataFetchError",
    "AnalysisError",
    "ValidationError",

    # Schema
    "WyckoffResultModel",
    "ErrorResponseModel",
]
