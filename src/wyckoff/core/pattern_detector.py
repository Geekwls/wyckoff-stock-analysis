import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from .detectors.trading_range_detector import TradingRangeDetector
from .detectors.classic_pattern_detector import ClassicPatternDetector
from .detectors.strength_weakness_detector import StrengthWeaknessDetector
from .detectors.phase_identifier import PhaseIdentifier
from .meng_pattern_enhancer import MengPatternEnhancer
from ..config.settings import WyckoffConfig, WyckoffThresholds
from ..schemas import (
    ClimaxModel, WyckoffEventModel, SpringModel, UpthrustModel,
    SosModel, SowModel, LpsModel, LpsyModel
)
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
        self.phase_identifier = PhaseIdentifier(data, config, self.thresholds)

        # 初始化孟洪涛增强检测器
        self.meng_enhancer = MengPatternEnhancer(data, config)

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

    def _collect_all_events(self) -> Dict[str, Any]:
        """收集所有威科夫事件供阶段识别使用"""
        climax_res = self.detect_climax()
        ar_res = self.detect_automatic_reaction(climax_res)
        st_res = self.detect_secondary_test(climax_res, ar_res)
        
        spring_res = self.detect_spring()
        upthrust_res = self.detect_upthrust()
        
        sos_res = self.detect_sos()
        sow_res = self.detect_sow()
        
        tr_res = self.detect_trading_range()
        lps_res = self.detect_lps(sos_res)
        lpsy_res = self.detect_lpsy(sow_res)
        joc_res = self.detect_joc()
        fti_res = self.detect_fti()

        # 统一使用强类型模型封装
        events = {
            'trading_range': TradingRangeModel(**tr_res),
            'climax': ClimaxModel(**climax_res),
            'automatic_reaction': WyckoffEventModel(**ar_res) if ar_res.get('detected') else WyckoffEventModel(detected=False),
            'secondary_test': WyckoffEventModel(**st_res) if st_res.get('detected') else WyckoffEventModel(detected=False),
            'spring_upthrust': None,
            'sos_sow': None,
            'lps_lpsy': {
                'lps': LpsModel(**lps_res),
                'lpsy': LpsyModel(**lpsy_res)
            },
            'joc': JocModel(**joc_res) if joc_res.get('detected') else None,
            'fti': FtiModel(**fti_res) if fti_res.get('detected') else None
        }
        
        if spring_res.get('detected'):
            events['spring_upthrust'] = {'_type': 'spring', 'data': SpringModel(**spring_res)}
        elif upthrust_res.get('detected'):
            events['spring_upthrust'] = {'_type': 'upthrust', 'data': UpthrustModel(**upthrust_res)}

        if sos_res.get('detected'):
            events['sos_sow'] = {'_type': 'sos', 'data': SosModel(**sos_res)}
        elif sow_res.get('detected'):
            events['sos_sow'] = {'_type': 'sow', 'data': SosModel(**sow_res)} 
            
        return events

    def detect_lps(self, sos_result: Dict = None) -> Dict:
        """检测 LPS (Last Point of Support)"""
        return self.sw_detector.detect_lps()

    def detect_lpsy(self, sow_result: Dict = None) -> Dict:
        """检测 LPSY (Last Point of Supply)"""
        return self.sw_detector.detect_lpsy()

    # --- 孟洪涛增强检测方法 ---

    def detect_spring_menhongtao(self) -> Dict:
        """
        孟洪涛Spring（震仓）增强检测

        基于孟洪涛《新威科夫操盘法》的5重过滤标准：
        1. 跌破幅度：1-3%（2%最佳）
        2. 收回时间：1-3天（根据ATR动态调整）
        3. 收回确认：收盘价站稳支撑位上方
        4. 成交量：收回时 > 跌破时
        5. 收盘位置：日内高位70%以上

        Returns:
            Dict: 包含置信度评分（0-100分）的检测结果
        """
        try:
            return self.meng_enhancer.detect_spring_enhanced()
        except Exception as e:
            logger.exception(f"孟洪涛Spring检测失败: {e}")
            # 回退到经典检测方法
            logger.warning("回退到经典Spring检测方法")
            return self.detect_spring()

    def detect_joc_menhongtao(self) -> Dict:
        """
        孟洪涛JOC（跃过小溪）增强检测

        基于孟洪涛《新威科夫操盘法》的严格标准：
        1. 突破确认：长阳线突破（涨幅>3%）
        2. 突破量能：成交量>1.5倍均量
        3. 收盘位置：日内高位75%以上
        4. 回测确认：缩量回落不破阻力位

        Returns:
            Dict: 包含置信度评分（0-100分）的检测结果
        """
        try:
            return self.meng_enhancer.detect_joc_enhanced()
        except Exception as e:
            logger.exception(f"孟洪涛JOC检测失败: {e}")
            # 回退到经典检测方法
            logger.warning("回退到经典JOC检测方法")
            return self.detect_joc()

    def detect_vsa_menhongtao(self) -> Dict:
        """
        孟洪涛VSA（Volume Spread Analysis）微观分析

        检测：
        - No Supply（无供应）：绝佳买入点
        - No Demand（无需求）：绝佳做空点
        - Stopping Volume（停止行为）：可能筑底

        Returns:
            Dict: VSA信号检测结果
        """
        try:
            return self.meng_enhancer.detect_vsa_signals()
        except Exception as e:
            logger.exception(f"VSA检测失败: {e}")
            return {
                "no_supply": {"detected": False, "error": str(e)},
                "no_demand": {"detected": False, "error": str(e)},
                "stopping_vol": {"detected": False, "error": str(e)}
            }
