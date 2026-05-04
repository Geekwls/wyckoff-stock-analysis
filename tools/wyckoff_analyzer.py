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
from .core.cache import LRUCache

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

    def __init__(self, symbol: str, period: str = "1y", config: WyckoffConfig = None):
        self.symbol = symbol
        self.period = period
        self.config = config or WyckoffConfig()
        self.thresholds = WyckoffThresholds()
        self._analysis_cache = LRUCache(max_size=256, ttl_seconds=3600)
        
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

    def fetch_data(self) -> pd.DataFrame:
        """获取数据并初始化所有探测器"""
        self.symbol, self.data = self.orchestrator.data_fetcher.fetch_data(self.symbol, self.period)
        if self.data is not None:
            self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)
            self.law_analyzer = WyckoffLawAnalyzer(self.data, self.config, self.pattern_detector)
            self.mtf_analyzer = MultiTimeframeAnalyzer(self.data, self.pattern_detector)
            self.rs_analyzer = RelativeStrengthAnalyzer(self.data, self.symbol)
        return self.data

    def generate_report(self) -> str:
        """生成文本报告"""
        return WyckoffReportGenerator(self).generate_report()

    def generate_json(self) -> str:
        """生成 JSON 报告"""
        return WyckoffReportGenerator(self).generate_json()

    # ----------------------------------------------------------
    # 代理旧方法 (为了兼容性)
    # ----------------------------------------------------------
    def identify_phase(self): return self.pattern_detector.identify_phase()
    def detect_trading_range(self): return self.pattern_detector.detect_trading_range()
    
    def _get_baseline_index_symbol(self) -> str:
        from .core.symbol_resolver import SymbolResolver, MarketType
        info = SymbolResolver().resolve(self.symbol)
        if info.market == MarketType.A_SHARE:
            code = info.normalized.split('.')[-1]
            return "sh.000001" if code.startswith('6') else "sz.399001"
        return "SPY"

    def _analyze_market_environment(self) -> Dict:
        # 这里为了演示，暂时调用编排器的占位逻辑
        return {"environment": MarketEnvironment.UNKNOWN}

    def calculate_cause_effect(self) -> Dict:
        if not self.pattern_detector: return {}
        tr = self.pattern_detector.detect_trading_range()
        if not tr.get('is_consolidation'): return {}
        size = tr['high'] - tr['low']
        return {
            'cause_size': round(size, 2),
            'targets': {
                'target_1': round(tr['high'] + size * 0.618, 2),
                'target_2': round(tr['high'] + size, 2),
                'target_3': round(tr['high'] + size * 1.618, 2),
            }
        }
