import pandas as pd
import logging
from typing import Dict
from .detectors.base_detector import BaseDetector
from .detectors.meng_reversal_detector import MengReversalDetector
from .detectors.meng_trend_detector import MengTrendDetector
from .detectors.meng_vsa_detector import MengVsaDetector

logger = logging.getLogger(__name__)

class MengPatternEnhancer(BaseDetector):
    """
    孟洪涛新威科夫操盘法增强器 (Facade)
    基于《新威科夫操盘法》精华实现
    """
    def __init__(self, data: pd.DataFrame, config, thresholds=None, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds
        
        # 初始化子检测器
        self.reversal = MengReversalDetector(data, config, thresholds, self._indicator_cache)
        self.trend = MengTrendDetector(data, config, thresholds, self._indicator_cache)
        self.vsa = MengVsaDetector(data, config, thresholds, self._indicator_cache)

    def detect_spring_enhanced(self) -> Dict:
        return self.reversal.detect_spring_enhanced()

    def detect_joc_enhanced(self) -> Dict:
        return self.trend.detect_joc_enhanced()

    def detect_vsa_signals(self) -> Dict:
        return self.vsa.detect_vsa_signals()

    def detect_boring_zone(self, window: int = 14) -> Dict:
        return self.vsa.detect_boring_zone(window)

    def detect_dead_corner_breakout(self) -> Dict:
        return self.trend.detect_dead_corner_breakout(self.vsa)

    def detect_dead_corner_breakout_enhanced(self) -> Dict:
        return self.trend.detect_dead_corner_breakout_enhanced(self.vsa)
