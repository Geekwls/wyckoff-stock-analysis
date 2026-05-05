import logging
import pandas as pd
from typing import Dict, Any, Optional
from .data_fetcher import WyckoffDataFetcher
from .pattern_detector import WyckoffPatternDetector
from .recommendation_engine import RecommendationEngine
from .report_generator import WyckoffReportGenerator
from ..config.settings import WyckoffConfig
from ..exceptions import WyckoffError

logger = logging.getLogger(__name__)

class WyckoffOrchestrator:
    """
    威科夫分析编排器 (P2 #1)
    负责驱动整个分析生命周期
    """

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.data_fetcher = WyckoffDataFetcher(self.config)
        self.rec_engine = RecommendationEngine(self.config)

    def run_analysis(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """
        运行完整分析流程
        """
        try:
            # 1. 数据获取
            resolved_symbol, data = self.data_fetcher.fetch_data(symbol, period)
            
            # 2. 形态检测
            detector = WyckoffPatternDetector(data, self.config)
            patterns = self._collect_patterns(detector)
            phase_info = detector.identify_phase()
            patterns.update(phase_info)

            # 3. 市场环境
            market_env = self._analyze_market_env(resolved_symbol, period)

            # 4. 建议引擎
            quality = self.rec_engine.calculate_signal_quality(data, patterns, market_env)
            
            # 因果计算 (临时放在这里，未来可独立)
            targets = self._calculate_targets(detector)
            
            trading_plan = self.rec_engine.generate_trading_plan(data, patterns, targets)
            risk_advice = self.rec_engine.generate_risk_advice(quality, trading_plan)

            # 5. 返回结果包
            return {
                "symbol": resolved_symbol,
                "data": data,
                "patterns": patterns,
                "market_env": market_env,
                "quality": quality,
                "trading_plan": trading_plan,
                "risk_advice": risk_advice
            }

        except WyckoffError:
            raise
        except Exception as e:
            logger.exception(f"分析执行异常: {symbol}")
            raise

    def _collect_patterns(self, detector: WyckoffPatternDetector) -> Dict[str, Any]:
        return {
            "joc": detector.detect_joc_menhongtao(),
            "fti": detector.detect_fti(),
            "spring": detector.detect_spring_menhongtao(),
            "upthrust": detector.detect_upthrust(),
            "sos": detector.detect_sos(),
            "sow": detector.detect_sow(),
            "lps": detector.detect_lps(),
            "lpsy": detector.detect_lpsy()
        }

    def _analyze_market_env(self, symbol: str, period: str) -> Any:
        # 简化版大盘分析 (未来从 WyckoffAnalyzer 彻底迁移)
        return MarketEnvironment.UNKNOWN

    def _calculate_targets(self, detector: WyckoffPatternDetector) -> Dict[str, Any]:
        # 因果目标计算 (基于水平准备时长)
        tr = detector.detect_trading_range()
        if tr.get('is_consolidation'):
            duration = tr.get('consolidation_duration_days', 40)
            # 估算波动率
            recent_data = detector.data.tail(20)
            atr = (recent_data['High'] - recent_data['Low']).mean()
            potential = duration * atr * 0.25 # 修正系数
            
            return {
                "target_1": round(tr['high'] + potential * 0.618, 2),
                "target_2": round(tr['high'] + potential, 2),
                "target_3": round(tr['high'] + potential * 1.618, 2)
            }
        return {}
