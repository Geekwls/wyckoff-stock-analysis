#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析器 - Facade (库层)
Wyckoff Analyzer - Facade for Orchestrator and Detectors

这是纯库层代码，不依赖任何应用层代码。
"""

import pandas as pd
import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

# 库层内部导入
from .config.settings import WyckoffConfig, WyckoffThresholds
from .core.enums import MarketEnvironment, WyckoffPhase
from .core.cache_service import CacheService
from .core.orchestrator import WyckoffOrchestrator
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

    这是纯库层代码，可以安全地从任何应用层导入使用。
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
        """清理资源"""
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
    def identify_phase(self):
        """识别威科夫阶段"""
        return self.pattern_detector.identify_phase()

    def detect_trading_range(self):
        """检测交易区间"""
        return self.pattern_detector.detect_trading_range()

    def _get_baseline_index_symbol(self) -> str:
        """获取基准指数代码"""
        from .core.symbol_resolver import SymbolResolver, MarketType
        info = SymbolResolver().resolve(self.symbol)
        if info.market == MarketType.A_SHARE:
            code = info.normalized.split('.')[-1]
            return "sh.000001" if code.startswith('6') else "sz.399001"
        return "SPY"

    def _analyze_market_environment(self) -> Dict:
        """分析市场环境"""
        # 这里为了演示，暂时调用编排器的占位逻辑
        return {"environment": MarketEnvironment.UNKNOWN}

    def calculate_cause_effect(self) -> Dict:
        """计算因果效应"""
        if not self.pattern_detector:
            return {}
        tr = self.pattern_detector.detect_trading_range()
        if not tr.get('is_consolidation'):
            return {}
        size = tr['high'] - tr['low']
        return {
            'cause_size': round(size, 2),
            'targets': {
                'target_1': round(tr['high'] + size * 0.618, 2),
                'target_2': round(tr['high'] + size, 2),
                'target_3': round(tr['high'] + size * 1.618, 2),
            }
        }


def batch_scan(symbols: List[str], period: str = "1y",
               scan_mode: str = "quick", config: WyckoffConfig = None,
               **kwargs) -> Dict[str, Any]:
    """
    批量扫描股票（便捷函数）

    Args:
        symbols: 股票代码列表，如 ["AAPL", "MSFT", "GOOGL"]
        period: 数据周期，默认 "1y"
        scan_mode: 扫描模式
            - "quick": 快速扫描（并行，返回摘要）✅ 当前支持
            - "deep"/"accumulation"/"distribution"/"lps"/"lpsy": 深度筛选（待适配新版接口）
        config: WyckoffConfig配置
        **kwargs: 额外参数
            - max_workers: 最大并行线程数（quick模式，默认自动检测）
            - show_progress: 是否显示进度（默认True）

    Returns:
        扫描结果字典:
        {
            "results": List[Dict],      # 扫描结果列表
            "summary": Dict,             # 统计摘要
            "top_picks": List[Dict],     # 顶级机会（TOP 10）
            "failed": List[str],         # 失败的股票
            "scan_mode": str             # 扫描模式
        }

    Examples:
        >>> # 快速扫描多只股票
        >>> result = batch_scan(["AAPL", "MSFT", "GOOGL"])
        >>> print(f"扫描完成: {result['summary']['total_scanned']} 只股票")
        >>> print(f"发现信号: {result['summary']['signal_count']} 个")
        >>>
        >>> # 查看顶级机会
        >>> for pick in result['top_picks']:
        ...     print(f"{pick['symbol']}: {pick['phase']} (评分: {pick.get('weighted_score', pick.get('strength'))})")

    Note:
        - 需要安装 tqdm 库以显示进度条
        - 并行扫描可显著提升效率（建议 4-8 线程）
        - 不同市场可能需要不同的数据周期（A股建议 2y）
    """
    from .services.screener_service import ScreenerService

    screener = ScreenerService(config)
    return screener.batch_scan(symbols, period, scan_mode, **kwargs)
