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
    SosModel, SowModel, LpsModel, LpsyModel, TradingRangeModel,
    JocModel, FtiModel
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
        phase_result = self.phase_identifier.identify(events)

        # 集成孟洪涛核心证据分析
        evidence_analysis = self.analyze_phase_a_evidence()

        # 将证据分析结果添加到 phase_result 中
        phase_result['core_evidence'] = evidence_analysis

        # 如果有证据分析，更新阶段描述
        if 'error' not in evidence_analysis:
            if evidence_analysis['strength'] == 'strong':
                phase_result['confidence'] = max(phase_result.get('confidence', 0), 80)
            elif evidence_analysis['strength'] == 'weak':
                phase_result['confidence'] = max(phase_result.get('confidence', 0), 50)
            elif evidence_analysis['strength'] == 'none':
                # 如果没有核心证据，降低置信度
                if 'Accumulation' in phase_result.get('phase', ''):
                    phase_result['confidence'] = min(phase_result.get('confidence', 50), 30)

        return phase_result

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

    # ============================================================
    # 孟洪涛核心证据检测（Core Evidence Detection）
    # ============================================================

    def detect_climax_panic_selling(self, lookback_days: int = 60) -> Dict:
        """
        检测恐慌性抛售（Selling Climax, SC）

        孟洪涛标准：
        1. 价格创近期新低（60天内最低）
        2. 成交量显著放大（>1.5倍前20日均值）
        3. 通常是垂直下跌或跳水式下跌

        Returns:
            Dict: {
                "detected": bool,
                "date": str (检测日期),
                "price": float (最低价格),
                "volume_ratio": float (成交量倍数),
                "confidence": float (0-100)
            }
        """
        try:
            recent_data = self.data.tail(lookback_days)
            min_idx = recent_data['Low'].idxmin()
            min_price = recent_data['Low'].min()
            min_vol = recent_data.loc[min_idx, 'Volume']

            # 计算前期平均成交量
            pre_data = self.data.loc[self.data.index < min_idx]
            if len(pre_data) < 20:
                return {"detected": False, "reason": "Insufficient data before low"}

            avg_vol_before = pre_data['Volume'].tail(20).mean()
            vol_ratio = min_vol / avg_vol_before if avg_vol_before > 0 else 0

            # 判断是否为恐慌性抛售
            is_climax = vol_ratio > 1.5

            # 计算置信度（基于成交量放大倍数）
            confidence = min(100, (vol_ratio - 1.0) / 2.0 * 100) if is_climax else 0

            return {
                "detected": is_climax,
                "date": min_idx.strftime("%Y-%m-%d") if is_climax else None,
                "price": float(min_price) if is_climax else None,
                "volume_ratio": float(vol_ratio),
                "confidence": float(confidence)
            }

        except Exception as e:
            logger.exception(f"SC检测失败: {e}")
            return {"detected": False, "error": str(e)}

    def detect_preliminary_support(self, lookback_days: int = 60) -> Dict:
        """
        检测初步支撑（Preliminary Support, PS）

        孟洪涛标准：
        1. 在恐慌性抛售（SC）后出现
        2. 反弹幅度>10%（说明有强劲需求接盘）
        3. 成交量配合（不一定放量，但要有持续性）

        Returns:
            Dict: {
                "detected": bool,
                "sc_low": float (恐慌低点),
                "ps_high": float (反弹高点),
                "rebound_pct": float (反弹百分比),
                "confidence": float (0-100)
            }
        """
        try:
            recent_data = self.data.tail(lookback_days)
            min_idx = recent_data['Low'].idxmin()
            sc_low = recent_data['Low'].min()

            # 检查SC之后的反弹
            after_sc = self.data.loc[self.data.index > min_idx]
            if len(after_sc) == 0:
                return {"detected": False, "reason": "Insufficient data after SC"}

            ps_high = after_sc['High'].max()
            ps_idx = after_sc['High'].idxmax()

            # 计算反弹幅度
            rebound_pct = (ps_high - sc_low) / sc_low * 100

            # 判断是否为初步支撑（反弹>8%，降低阈值以增加检测灵敏度）
            is_ps = rebound_pct > 8

            # 置信度基于反弹幅度
            confidence = min(100, (rebound_pct - 5) / 2.0 * 10) if is_ps else 0

            return {
                "detected": is_ps,
                "sc_date": min_idx.strftime("%Y-%m-%d"),
                "sc_low": float(sc_low),
                "ps_date": ps_idx.strftime("%Y-%m-%d"),
                "ps_high": float(ps_high),
                "rebound_pct": float(rebound_pct),
                "confidence": float(confidence)
            }

        except Exception as e:
            logger.exception(f"PS检测失败: {e}")
            return {"detected": False, "error": str(e)}

    def detect_stopping_of_transient(self, lookback_days: int = 20) -> Dict:
        """
        检测停止行为（Stopping of Transient, SOT）

        孟洪涛标准：努力无结果（Effort without Result）
        1. 成交量显著放大（>1.3倍50日均量）
        2. 价格下跌幅度很小（实体<当日的30%）
        3. 说明供应被需求吸收，不再能压低价格

        Returns:
            Dict: {
                "detected": bool,
                "date": str (检测日期),
                "volume_ratio": float (成交量倍数),
                "body_ratio": float (实体占当日振幅比例),
                "confidence": float (0-100)
            }
        """
        try:
            recent_data = self.data.tail(lookback_days)
            avg_vol = self.data['Volume'].tail(50).mean()

            for idx in range(len(recent_data) - 5, len(recent_data)):
                row = recent_data.iloc[idx]
                body = abs(row['Close'] - row['Open'])
                range_size = row['High'] - row['Low']

                if range_size == 0:
                    continue

                vol_ratio = row['Volume'] / avg_vol if avg_vol > 0 else 0
                body_ratio = body / range_size

                # SOT判断：放量 + 小实体
                is_sot = vol_ratio > 1.3 and body_ratio < 0.3

                if is_sot:
                    confidence = min(100, vol_ratio * 40)
                    return {
                        "detected": True,
                        "date": row.name.strftime("%Y-%m-%d"),
                        "volume_ratio": float(vol_ratio),
                        "body_ratio": float(body_ratio),
                        "close": float(row['Close']),
                        "volume": float(row['Volume']),
                        "confidence": float(confidence)
                    }

            return {"detected": False, "reason": "No SOT pattern found"}

        except Exception as e:
            logger.exception(f"SOT检测失败: {e}")
            return {"detected": False, "error": str(e)}

    def detect_spring_menhongtao(self, lookback_days: int = 10) -> Dict:
        """
        检测弹簧（Spring）- 孟洪涛5滤网严格标准

        孟洪涛标准：
        1. 下影线刺破支撑位（至少2%误差范围）
        2. 收盘价回到支撑位之上
        3. 下影线长度>1.5倍实体长度
        4. 成交量放大（>1.2倍50日均量）
        5. 必须有充分的底部准备（因）

        Returns:
            Dict: {
                "detected": bool,
                "date": str (检测日期),
                "low": float (最低价),
                "close": float (收盘价),
                "lower_wick": float (下影线长度),
                "volume_ratio": float (成交量倍数),
                "confidence": float (0-100),
                "filters_passed": int (通过的滤网数量)
            }
        """
        try:
            # 确定支撑位（最近60天的最低点）
            support_level = self.data.tail(60)['Low'].min()
            support_ref = support_level * 0.98  # 允许2%误差

            recent_data = self.data.tail(lookback_days)
            avg_vol = self.data['Volume'].tail(50).mean()

            for idx in range(len(recent_data)):
                row = recent_data.iloc[idx]
                lower_wick = min(row['Close'], row['Open']) - row['Low']
                body_size = abs(row['Close'] - row['Open'])
                vol_expansion = row['Volume'] / avg_vol if avg_vol > 0 else 0

                # 5滤网检测
                filters_passed = 0

                # 滤网1：刺破支撑位
                filter1 = row['Low'] < support_ref
                if filter1:
                    filters_passed += 1

                # 滤网2：收盘回到支撑位之上
                filter2 = row['Close'] > support_ref
                if filter2:
                    filters_passed += 1

                # 滤网3：下影线>1.5倍实体
                filter3 = lower_wick > body_size * 1.5
                if filter3:
                    filters_passed += 1

                # 滤网4：成交量放大
                filter4 = vol_expansion > 1.2
                if filter4:
                    filters_passed += 1

                # 滤网5：有底部准备（通过检测SC和PS）
                # 这个需要额外的上下文，暂时作为通过条件
                filters_passed += 1

                # Spring判定：至少通过4/5滤网
                is_spring = filters_passed >= 4

                if is_spring:
                    confidence = (filters_passed / 5.0) * 100
                    return {
                        "detected": True,
                        "date": row.name.strftime("%Y-%m-%d"),
                        "low": float(row['Low']),
                        "close": float(row['Close']),
                        "lower_wick": float(lower_wick),
                        "body_size": float(body_size),
                        "volume_ratio": float(vol_expansion),
                        "support_level": float(support_level),
                        "filters_passed": filters_passed,
                        "confidence": float(confidence)
                    }

            return {
                "detected": False,
                "reason": "No qualified Spring pattern found",
                "filters_passed": 0
            }

        except Exception as e:
            logger.exception(f"Spring检测失败: {e}")
            return {"detected": False, "error": str(e)}

    def analyze_phase_a_evidence(self) -> Dict:
        """
        综合分析 Phase A 的核心证据

        孟洪涛方法：Phase A 不能只看价格位置，必须检查核心证据

        Returns:
            Dict: {
                "phase_a_confirmed": bool,
                "strength": str ("strong" | "weak" | "none"),
                "evidence": {
                    "sc": {...},
                    "ps": {...},
                    "sot": {...},
                    "spring": {...}
                },
                "evidence_count": int,
                "total_checks": 4
            }
        """
        try:
            # 检测4个核心证据
            sc_result = self.detect_climax_panic_selling()
            ps_result = self.detect_preliminary_support()
            sot_result = self.detect_stopping_of_transient()
            spring_result = self.detect_spring_menhongtao()

            evidence_count = sum([
                sc_result.get("detected", False),
                ps_result.get("detected", False),
                sot_result.get("detected", False),
                spring_result.get("detected", False)
            ])

            # 判断 Phase A 强度
            if evidence_count >= 3:
                strength = "strong"
                phase_a_confirmed = True
            elif evidence_count >= 2:
                strength = "weak"
                phase_a_confirmed = True
            else:
                strength = "none"
                phase_a_confirmed = False

            return {
                "phase_a_confirmed": phase_a_confirmed,
                "strength": strength,
                "evidence_count": evidence_count,
                "total_checks": 4,
                "evidence": {
                    "sc": sc_result,
                    "ps": ps_result,
                    "sot": sot_result,
                    "spring": spring_result
                }
            }

        except Exception as e:
            logger.exception(f"Phase A证据分析失败: {e}")
            return {
                "phase_a_confirmed": False,
                "strength": "none",
                "error": str(e)
            }
