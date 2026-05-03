import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from .detectors.trading_range_detector import TradingRangeDetector
from .detectors.classic_pattern_detector import ClassicPatternDetector
from .detectors.strength_weakness_detector import StrengthWeaknessDetector
from .detectors.phase_identifier import PhaseIdentifier
from ..config.settings import WyckoffConfig, WyckoffThresholds
import logging

logger = logging.getLogger(__name__)

class WyckoffPatternDetector:
    """威科夫形态检测器 (Facade/Delegate)
    重构说明: 已将具体检测逻辑拆分至 detectors/ 目录下的子类中，以解决 God Object 问题。
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, analysis_cache):
        self.data = data
        self.config = config
        self.thresholds = WyckoffThresholds()
        self._analysis_cache = analysis_cache
        
        # 初始化专门的检测器
        self.range_detector = TradingRangeDetector(data, config)
        self.classic_detector = ClassicPatternDetector(data, config, self.thresholds, analysis_cache)
        self.sw_detector = StrengthWeaknessDetector(data, config, self.thresholds)
        self.phase_identifier = PhaseIdentifier(data, config)

    # --- 代理方法 (Delegated Methods) ---

    def detect_trading_range(self, window: int = 60) -> Dict:
        return self.range_detector.detect(window)

    def detect_climax(self) -> Dict:
        return self.classic_detector.detect_climax()

    def detect_automatic_reaction(self, climax_res: Dict) -> Dict:
        return self.classic_detector.detect_automatic_reaction(climax_res)

    def detect_secondary_test(self, climax_res: Dict, ar_res: Dict) -> Dict:
        return self.classic_detector.detect_secondary_test(climax_res, ar_res)

    def detect_spring(self, lookback: int = None) -> Dict:
        return self.classic_detector.detect_spring(lookback)

    def detect_upthrust(self, lookback: int = None) -> Dict:
        return self.classic_detector.detect_upthrust(lookback)

    def detect_sos(self, window: int = 40) -> Dict:
        return self.sw_detector.detect_sos(window)

    def detect_sow(self, window: int = 40) -> Dict:
        return self.sw_detector.detect_sow(window)

    def detect_sos_variants(self) -> Dict:
        return self.sw_detector.detect_sos_variants()

    def detect_sow_variants(self) -> Dict:
        return self.sw_detector.detect_sow_variants()

    def detect_joc(self, lookback: int = 90) -> Dict:
        return self.classic_detector.detect_joc(lookback)

    def detect_fti(self, lookback: int = 90) -> Dict:
        return self.classic_detector.detect_fti(lookback)

    def detect_vsa_signals(self, lookback: int = 20) -> Dict:
        return self.classic_detector.detect_vsa_signals(lookback)

    def detect_divergence(self, window: int = 30) -> Dict:
        return self.classic_detector.detect_divergence(window)

    def identify_phase(self) -> Dict:
        # 收集事件后识别
        events = self._collect_all_events()
        return self.phase_identifier.identify(events)

    # --- 私有辅助方法 (保持原有逻辑或重构) ---

    def _collect_all_events(self) -> Dict:
        """收集所有威科夫事件供阶段识别使用"""
        events = {
            'climax': self.detect_climax(),
            'automatic_reaction': None,
            'secondary_test': None,
            'spring_upthrust': None,
            'sos_sow': None,
            'lps_lpsy': None
        }
        
        if events['climax']['detected']:
            events['automatic_reaction'] = self.detect_automatic_reaction(events['climax'])
            if events['automatic_reaction'] and events['automatic_reaction']['detected']:
                events['secondary_test'] = self.detect_secondary_test(
                    events['climax'], 
                    events['automatic_reaction']
                )
        
        # 基础形态
        spring_res = self.detect_spring()
        upthrust_res = self.detect_upthrust()
        if spring_res.get('detected'):
            events['spring_upthrust'] = {**spring_res, '_type': 'spring'}
        elif upthrust_res.get('detected'):
            events['spring_upthrust'] = {**upthrust_res, '_type': 'upthrust'}

        # SOS/SOW 
        sos_res = self.detect_sos()
        sow_res = self.detect_sow()
        if sos_res.get('detected'):
            events['sos_sow'] = {**sos_res, '_type': 'sos'}
        elif sow_res.get('detected'):
            events['sos_sow'] = {**sow_res, '_type': 'sow'}

        # LPS/LPSY
        events['lps_lpsy'] = {
            'lps': self.detect_lps(sos_res),
            'lpsy': self.detect_lpsy(sow_res)
        }
            
        return events

    def detect_lps(self, sos_result: Dict = None) -> Dict:
        """检测 LPS (Last Point of Support)"""
        return self.sw_detector.detect_lps()

    def detect_lpsy(self, sow_result: Dict = None) -> Dict:
        """检测 LPSY (Last Point of Supply)"""
        return self.sw_detector.detect_lpsy()
