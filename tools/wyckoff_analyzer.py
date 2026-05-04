#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析器 - Facade (P2 Refactored)
Wyckoff Analyzer - Facade for Orchestrator and Detectors
"""

import pandas as pd
import logging
import os
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

# 基础组件
from .config.settings import WyckoffConfig, WyckoffThresholds
from .core.enums import MarketEnvironment, WyckoffPhase
from .core.cache_service import CacheService

# 编排层 (P2)
from .core.orchestrator import WyckoffOrchestrator

# 探测组件 (Facade 会持有的引用，供旧 API 使用)
from .core.pattern_detector import WyckoffPatternDetector
from .core.law_analyzer import WyckoffLawAnalyzer
from .core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from .core.relative_strength_analyzer import RelativeStrengthAnalyzer
from .core.report_generator import WyckoffReportGenerator

logger = logging.getLogger(__name__)

class WyckoffAnalyzer:
    """
    威科夫分析器 (Facade)
    
    在 P2 重构中，我们将控制流和决策逻辑移交给了 WyckoffOrchestrator 和 RecommendationEngine。
    此类作为统一入口保持向下兼容。
    """

    def __init__(
        self,
        symbol: str,
        period: str = "1y",
        config: WyckoffConfig = None,
        cache_service: Optional[CacheService] = None,
    ):
        self.symbol = symbol
        self.period = period
        self.config = config or WyckoffConfig()
        self.thresholds = WyckoffThresholds()
        self.cache_service = cache_service or CacheService.get_instance()
        self._analysis_cache = self.cache_service.get_legacy_lru_adapter(
            namespace="analysis",
            max_size=256,
            ttl_seconds=3600,
        )
        
        # 核心编排器
        self.orchestrator = WyckoffOrchestrator(self.config)
        
        # 运行时数据与探测器 (fetch_data 后初始化)
        self.data = None
        self.pattern_detector = None
        self.law_analyzer = None
        self.mtf_analyzer = None
        self.rs_analyzer = None
        
        self._index_analyzer_cache: Optional['WyckoffAnalyzer'] = None

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self._analysis_cache.invalidate()
        if hasattr(self.orchestrator.data_fetcher, 'logout_baostock'):
            self.orchestrator.data_fetcher.logout_baostock()

Use `wyckoff.facade` instead.
"""

from wyckoff.facade import WyckoffAnalyzer, batch_scan
from wyckoff.config.settings import WyckoffConfig

__all__ = ["WyckoffAnalyzer", "WyckoffConfig", "batch_scan"]
