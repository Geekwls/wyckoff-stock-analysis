import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple, List, Any
from .base_detector import BaseDetector, USE_VECTORIZED
from ...config.settings import WyckoffConfig, WyckoffThresholds
from ..utils import TypeConverter, PhaseAdapter
from ..indicator_cache import IndicatorCache
from .reversal_detector import ReversalDetector
from .trend_detector import TrendDetector
from .vsa_detector import VsaDetector

logger = logging.getLogger(__name__)

class ClassicPatternDetector(BaseDetector):
    """
    经典威科夫形态检测器的门面类 (Facade)
    负责协调反转、趋势和 VSA 子检测器
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, analysis_cache, bayesian_model=None, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds
        
        # 初始化子检测器
        self.reversal = ReversalDetector(data, config, thresholds, analysis_cache, bayesian_model, self._indicator_cache)
        self.trend = TrendDetector(data, config, thresholds, analysis_cache, bayesian_model, self._indicator_cache)
        self.vsa = VsaDetector(data, config, thresholds, self._indicator_cache)

    def update_analysis_context(self, phase: str):
        """同步更新所有子检测器的上下文"""
        super().update_analysis_context(phase)
        self.reversal.update_analysis_context(phase)
        self.trend.update_analysis_context(phase)
        self.vsa.update_analysis_context(phase)

    # 代理方法 (保持向后兼容)
    def detect_climax(self) -> Dict: return self.reversal.detect_climax()
    def detect_automatic_reaction(self, climax_res: Dict) -> Dict: return self.reversal.detect_automatic_reaction(climax_res)
    def detect_secondary_test(self, climax_res: Dict, ar_res: Dict) -> Dict: return self.reversal.detect_secondary_test(climax_res, ar_res)
    def detect_spring(self, lookback: int = None) -> Dict: return self.reversal.detect_spring(lookback)
    def detect_upthrust(self, lookback: int = None) -> Dict: return self.reversal.detect_upthrust(lookback)
    
    def detect_joc(self, lookback: int = 90) -> Dict: return self.trend.detect_joc(lookback)
    def detect_fti(self, lookback: int = 90) -> Dict: return self.trend.detect_fti(lookback)
    
    def detect_vsa_signals(self, lookback: int = 20) -> Dict: return self.vsa.detect_vsa_signals(lookback)
    def detect_divergence(self, window: int = 30) -> Dict: return self.vsa.detect_divergence(window)
    def detect_bag_holding(self) -> Dict: return self.vsa.detect_bag_holding()
    def detect_shakeout(self) -> Dict: return self.vsa.detect_shakeout(self.reversal)

    @staticmethod
    def validate_spring_with_phase(spring_result: Dict, phase_analysis: Dict) -> Dict:
        return ReversalDetector.validate_spring_with_phase(spring_result, phase_analysis)
