import pandas as pd
import logging
from typing import Dict, Optional, Tuple, List, Any, Union, cast
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig, WyckoffThresholds
from ..enums import WyckoffPhase
from ..utils import PhaseAdapter

logger = logging.getLogger(__name__)

# Named constants for magic numbers
CLIMAX_CONFIDENCE_THRESHOLD = 0.85
WEAK_SIGNAL_CONFIDENCE = 0.5
PHASE_A_COMPLETENESS_PENALTY = {
    'extreme': 0.3,    # Only Climax, extremely incomplete
    'severe': 0.5,     # Climax + AR or ST
    'moderate': 0.7    # Other incomplete cases
}
STRUCTURAL_INTEGRITY_FACTORS = {
    1: 0.4,   # Only 1-2 pillars remaining
    2: 0.6,   # 2 pillars
    3: 0.85,  # 3 pillars
    4: 1.0    # Complete structure
}
VOLUME_RATIO_THRESHOLDS = {
    'extremely_low': 0.4,
    'low': 0.7,
    'normal': 0.8,
    'high': 1.2
}
PRICE_TOLERANCE_PCT = 0.02    # 2% tolerance for weak signal detection
WEAK_PRICE_TOLERANCE_PCT = 0.03  # 3% tolerance for weak ST detection
CONFIDENCE_ADJUSTMENT = {
    'strong_markup_with_warning': 0.65,
    'strong_markup_bc_warning': 0.60,
    'strong_markup_sc_warning': 0.55,
    'distribution_a_pending': 0.70,
    'accumulation_a_pending': 0.70,
    'trending_bc_warning': 0.50,
    'trending_sc_warning': 0.50
}
LOOKBACK_DAYS = 120
MIN_DATA_POINTS = 3
SPRING_WINDOW_DAYS = 30
VOLUME_MA_WINDOW = 20
ANALYSIS_WINDOW_DAYS = 40

class PhaseIdentifier(BaseDetector):
    """负责识别威科夫阶段和评分"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def _get_event(self, events: Any, name: str) -> Any:
        """从 dict 或 Pydantic Model 稳健地获取子事件对象"""
        if isinstance(events, dict):
            return events.get(name)
        return getattr(events, name, None)

    def identify(self, raw_events) -> Dict:
        """主识别流程 — raw_events 现在是 EventsModel 或向后兼容的 Dict"""
        if self.data is None:
            return {'phase': 'Unknown', 'confidence': 0.0, 'phase_enum': WyckoffPhase.UNKNOWN}

        # 若传入 EventsModel，直接使用；否则保持历史兼容路径
        from ...schemas import EventsModel as _EM
        if isinstance(raw_events, _EM):
            events = raw_events
        else:
            events = self.filter_relevant_events(raw_events)

        phase_str, phase_enum, confidence, phase_description = self._determine_phase_from_events(events)
        if phase_enum == WyckoffPhase.UNKNOWN:
            phase_str, phase_enum, confidence, phase_description = self._fallback_logic(events)
        
        #  评分修正：如果 Phase A 结构不完整，大幅扣减置信度
        if phase_enum != WyckoffPhase.UNKNOWN:
            completeness_factor = self._calculate_structural_integrity(events, phase_enum)
            confidence *= completeness_factor

        # 新增：Phase A结构不完整时的额外惩罚
        if phase_enum == WyckoffPhase.PHASE_A:
            has_complete_structure = self._check_phase_a_completeness(events)
            structure_status = self._get_phase_a_structure_status(events)

            if not has_complete_structure:
                score = structure_status.get("completeness_score", 0)
                penalty_factor = self._get_phase_a_penalty_factor(score)
                original_confidence = confidence
                confidence *= penalty_factor

                penalty_pct = int((1 - penalty_factor) * 100)
                logger.info(f"[Phase A结构不完整] 置信度从{original_confidence:.2f}降低至{confidence:.2f} (惩罚{penalty_pct}%)")

            # 将结构状态添加到返回结果中
            phase_a_structure_info = {
                "completeness_score": structure_status.get("completeness_score", 0),
                "missing_elements": structure_status.get("missing_elements", []),
                "warnings": structure_status.get("warnings", [])
            }
        else:
            phase_a_structure_info = None

        ma_conf = self._check_ma_confirmation(phase_enum)
        vol_conf = self._check_volume_confirmation(phase_enum)
        
        weights = self.thresholds.SCORING.phase_weights
        final_conf = (
            confidence * weights.get('confidence', 0.5) + 
            ma_conf * weights.get('ma', 0.3) + 
            vol_conf * weights.get('vol', 0.2)
        )
        seq_score = self.calculate_sequence_score(events, phase_enum)
        final_conf *= seq_score.get('adjustment_factor', 1.0)

        # 增加量价质量传递验证 (P2 #2.3)
        quality_factor = self._analyze_phase_a_evidence(events)
        final_conf *= quality_factor

        #  修复矛盾二：增加相位一致性互斥校验
        phase_str, phase_enum, final_conf = self._check_logical_consistency(events, phase_str, phase_enum, final_conf)

        result = {
            'phase': phase_str,
            'phase_enum': phase_enum,
            'confidence': round(min(final_conf, 1.0), 2),
            'ma_confidence': round(ma_conf, 2),
            'vol_confidence': round(vol_conf, 2),
            'sequence_score': seq_score,
            'quality_factor': round(quality_factor, 2)
        }
        if phase_description:
            result['phase_description'] = phase_description

        # 添加Phase A结构状态信息
        if phase_a_structure_info:
            result['phase_a_structure'] = phase_a_structure_info

        return result

    def _analyze_phase_a_evidence(self, events: Dict) -> float:
        """
        验证 Phase A 的量价质量传递 (P2 #2.3)
        """
        score = 1.0
        climax = self._get_event(events, 'climax')
        st = self._get_event(events, 'secondary_test')

        if not (self._safe_check_detected(climax) and self._safe_check_detected(st)):
            return score

        try:
            sc_vol = self._safe_get_event_attribute(climax, 'volume')
            st_date = self._safe_get_event_attribute(st, 'date')
            st_vol = self.data.loc[st_date, 'Volume']

            vol_ratio = st_vol / sc_vol
            # 如果 ST 成交量显著小于 SC，说明供应萎缩，增加置信度
            if vol_ratio < VOLUME_RATIO_THRESHOLDS['extremely_low']:
                score += 0.15
            elif vol_ratio > VOLUME_RATIO_THRESHOLDS['normal']:
                score -= 0.15
        except Exception:
            pass
        return score

    def _check_phase_a_completeness(self, events: Dict) -> bool:
        """
        检查Phase A结构完整性

        威科夫理论要求：Phase A 必须包含完整的 PS → SC/BC → AR → ST 序列
        只有Climax没有AR/ST = 可能只是暂时的停顿，不是真正的Phase A
        """
        climax = self._get_event(events, 'climax')
        ar = self._get_event(events, 'automatic_reaction')
        st = self._get_event(events, 'secondary_test')
        ps = self._get_event(events, 'preliminary_support')

        has_climax = self._safe_check_detected(climax)
        has_ar = self._safe_check_detected(ar)
        has_st = self._safe_check_detected(st)
        has_ps = self._safe_check_detected(ps)

        # 威科夫理论：Phase A 至少需要 Climax + (AR 或 ST)
        has_complete_structure = has_climax and (has_ar or has_st)

        # 记录详细的缺失警告
        if has_climax and not has_complete_structure:
            missing = []
            if not has_ar:
                missing.append("AR(自动反弹/回落)")
            if not has_st:
                missing.append("ST(二次测试)")

            logger.warning(
                f"[Phase A结构不完整] 检测到Climax但缺少 {', '.join(missing)}。"
                f"根据威科夫理论，这可能只是趋势中的暂时停顿，而非真正的Phase A开始。"
                f"等待 {', '.join(missing)} 出现后再确认Phase A。"
            )

        return has_complete_structure

    def _get_phase_a_structure_status(self, events: Dict) -> Dict:
        """
        获取Phase A结构状态的详细信息

        Returns:
            包含结构完整性状态和警告信息的字典
        """
        climax = self._get_event(events, 'climax')
        ar = self._get_event(events, 'automatic_reaction')
        st = self._get_event(events, 'secondary_test')
        ps = self._get_event(events, 'preliminary_support')

        has_climax = self._safe_check_detected(climax)
        has_ar = self._safe_check_detected(ar)
        has_st = self._safe_check_detected(st)
        has_ps = self._safe_check_detected(ps)

        status = {
            "has_preliminary_support": has_ps,
            "has_climax": has_climax,
            "has_automatic_reaction": has_ar,
            "has_secondary_test": has_st,
            "is_complete": has_climax and (has_ar or has_st),
            "completeness_score": 0,
            "missing_elements": [],
            "warnings": []
        }

        # 计算完整性得分（满分4分）
        score = sum([
            has_ps,
            has_climax,
            has_ar,
            has_st
        ])
        status["completeness_score"] = score

        # 记录缺失元素
        required_elements = {
            'has_preliminary_support': 'PS',
            'has_climax': 'Climax',
            'has_automatic_reaction': 'AR',
            'has_secondary_test': 'ST'
        }

        for key, element_name in required_elements.items():
            if not status[key]:
                status["missing_elements"].append(element_name)

        # 生成警告信息
        if has_climax and not (has_ar or has_st):
            status["warnings"].append(
                "⚠️ 威科夫理论警告：仅有Climax无AR/ST，可能只是趋势中暂时停顿"
            )
        if score == 1 and has_climax:
            status["warnings"].append(
                "⚠️ 威科夫理论警告：Phase A结构极不完整（1/4），不建议作为交易依据"
            )

        return status

    def _determine_phase_from_events(self, events: Dict) -> Tuple[str, WyckoffPhase, float, Optional[str]]:
        """从事件序列中判定阶段 - 优化版（方案B）"""

        #  方案B优化：首先检查是否为"BC强但AR/ST缺失"的模糊结构
        ambiguous_phase = self._check_ambiguous_phase_structure(events)
        if ambiguous_phase:
            return self._phase_tuple(ambiguous_phase)

        flags = self._extract_phase_signal_flags(events)

        # Phase 9 (B1/B3)：JOC/FTI 突破期判定优先于 Phase B 主动检测
        breakout_phase = self._detect_breakout_phase_d(events, flags)
        if breakout_phase:
            return self._phase_tuple(breakout_phase)

        # Phase C+ 决断信号须在 Phase B 之前（B3：Upthrust+SOW 无 FTI 不应被 Phase B 覆盖）
        phase_c_plus = self._detect_phase_c_plus_signals(events, flags)
        if phase_c_plus:
            return self._phase_tuple(phase_c_plus)

        #  Phase B 主动检测逻辑（须在 JOC/FTI 之后，避免覆盖 Phase D）
        phase_b_result = self._detect_phase_b_active(events)
        if phase_b_result:
            return self._phase_tuple(phase_b_result)

        is_spring = flags['is_spring']
        is_upthrust = flags['is_upthrust']

        climax = getattr(events, 'climax', None)
        ar = getattr(events, 'automatic_reaction', None)
        st = getattr(events, 'secondary_test', None)

        if is_spring:
            return self._phase_tuple(('Accumulation Phase C (积累期震仓)', WyckoffPhase.PHASE_C, 0.70))
        if is_upthrust:
            return self._phase_tuple(('Distribution Phase C (派发期诱多)', WyckoffPhase.PHASE_C, 0.70))

        if climax and climax.detected and ar and ar.detected:
            if climax.type == 'selling_climax':
                return self._phase_tuple(('Accumulation Phase A (恐慌抛售停止)', WyckoffPhase.PHASE_A, 0.75))
            return self._phase_tuple(('Distribution Phase A (买入高潮停止)', WyckoffPhase.PHASE_A, 0.75))

        if climax and climax.detected and st and st.detected:
            if climax.type == 'selling_climax':
                return self._phase_tuple(('Accumulation Phase B (积累期测试)', WyckoffPhase.PHASE_B, 0.60))
            return self._phase_tuple(('Distribution Phase B (派发期测试)', WyckoffPhase.PHASE_B, 0.60))

        return self._phase_tuple(('Unknown', WyckoffPhase.UNKNOWN, 0.30))

    @staticmethod
    def _phase_tuple(result: Tuple[str, WyckoffPhase, float, Optional[str]] | Tuple[str, WyckoffPhase, float]) -> Tuple[str, WyckoffPhase, float, Optional[str]]:
        if len(result) == 4:
            return result
        phase, enum, conf = result
        return phase, enum, conf, None

    def _extract_phase_signal_flags(self, events: Dict) -> Dict[str, bool]:
        """从 EventsModel 提取 Spring/Upthrust/SOS/SOW/JOC/FTI 检测标志。"""
        from ...schemas import DualEventModel as _DEM
        su_info = getattr(events, 'spring_upthrust', None)
        ss_info = getattr(events, 'sos_sow', None)
        joc = getattr(events, 'joc', None)
        fti = getattr(events, 'fti', None)
        return {
            'is_spring': (
                isinstance(su_info, _DEM) and su_info.type_ == 'spring'
                and getattr(su_info.data, 'detected', False)
            ),
            'is_upthrust': (
                isinstance(su_info, _DEM) and su_info.type_ == 'upthrust'
                and getattr(su_info.data, 'detected', False)
            ),
            'is_sos': (
                isinstance(ss_info, _DEM) and ss_info.type_ == 'sos'
                and getattr(ss_info.data, 'detected', False)
            ),
            'is_sow': (
                isinstance(ss_info, _DEM) and ss_info.type_ == 'sow'
                and getattr(ss_info.data, 'detected', False)
            ),
            'is_joc': bool(joc and getattr(joc, 'detected', False)),
            'is_fti': bool(fti and getattr(fti, 'detected', False)),
        }

    def _is_accumulation_joc_context(self, events: Dict, flags: Dict[str, bool]) -> bool:
        """派发/BC/SOW 语境下向上突破不应归类为吸筹 JOC → Phase D。"""
        climax = getattr(events, 'climax', None)
        if climax and getattr(climax, 'detected', False):
            if getattr(climax, 'type', None) == 'buying_climax':
                return False
        if flags.get('is_sow'):
            return False
        joc = getattr(events, 'joc', None)
        if joc is not None:
            if getattr(joc, 'joc_overload_warning', False):
                return False
            reason = getattr(joc, 'reason', None)
            if reason in ('joc_volume_overload_buying_climax', 'suppressed_by_overbought_climax'):
                return False
        return True

    def _detect_breakout_phase_d(
        self, events: Dict, flags: Dict[str, bool]
    ) -> Optional[Tuple[str, WyckoffPhase, float]]:
        """
        孟氏突破期（Phase D）判定：吸筹须 JOC，派发须 FTI。
        须在 Phase B 主动检测之前调用（Phase 9 / B1、B3）。
        """
        if flags.get('is_joc'):
            if not self._is_accumulation_joc_context(events, flags):
                return None
            joc = getattr(events, 'joc', None)
            conf = 0.85
            if getattr(joc, 'test_detected', False) and getattr(joc, 'test_score', 0) >= 60:
                conf = 0.90
            return self._maybe_upgrade_to_phase_e(
                'Accumulation Phase D (积累期突破)', WyckoffPhase.PHASE_D, conf
            )

        if flags.get('is_fti'):
            fti = getattr(events, 'fti', None)
            conf = 0.85
            if getattr(fti, 'test_detected', False):
                conf = 0.90
            return self._maybe_upgrade_to_phase_e(
                'Distribution Phase D (派发期跌破)', WyckoffPhase.PHASE_D, conf
            )

        return None

    def _maybe_upgrade_to_phase_e(
        self, phase_d_label: str, phase_enum: WyckoffPhase, confidence: float
    ) -> Tuple[str, WyckoffPhase, float]:
        """Phase 11: JOC/FTI Phase D 在连续同向确认后升级 Phase E。"""
        from ..utils import continuous_price_confirmation
        if self.data is None:
            return phase_d_label, phase_enum, confidence
        if not continuous_price_confirmation(self.data, 3, phase_d_label, require_volume=True):
            return phase_d_label, phase_enum, confidence
        if 'Accumulation' in phase_d_label:
            return 'Accumulation Phase E (Markup推进)', WyckoffPhase.PHASE_E, min(confidence + 0.05, 0.95)
        if 'Distribution' in phase_d_label:
            return 'Distribution Phase E (Markdown推进)', WyckoffPhase.PHASE_E, min(confidence + 0.05, 0.95)
        return phase_d_label.replace('Phase D', 'Phase E'), WyckoffPhase.PHASE_E, min(confidence + 0.05, 0.95)

    def _detect_phase_c_plus_signals(
        self, events: Dict, flags: Dict[str, bool]
    ) -> Optional[Tuple[str, WyckoffPhase, float]]:
        """Spring+SOS / Upthrust+SOW / 孤立 SOW(SOS) 决断性组合，突破确认前最高 Phase C+。"""
        climax = getattr(events, 'climax', None)
        climax_type = getattr(climax, 'type', None) if climax and getattr(climax, 'detected', False) else None

        if flags.get('is_spring') and flags.get('is_sos'):
            return 'Accumulation Phase C+ (SOS出现待JOC确认)', WyckoffPhase.PHASE_C, 0.75
        if flags.get('is_upthrust') and flags.get('is_sow'):
            return 'Distribution Phase C+ (SOW出现待FTI确认)', WyckoffPhase.PHASE_C, 0.75

        # Phase 14: 孤立 SOW/SOS 对称升级 C+（须匹配派发/吸筹 climax 语境）
        if flags.get('is_sow') and not flags.get('is_fti') and climax_type == 'buying_climax':
            return 'Distribution Phase C+ (SOW出现待FTI确认)', WyckoffPhase.PHASE_C, 0.72
        if flags.get('is_sos') and not flags.get('is_joc') and climax_type == 'selling_climax':
            return 'Accumulation Phase C+ (SOS出现待JOC确认)', WyckoffPhase.PHASE_C, 0.72

        return None

    def _detect_phase_b_active(self, events: Dict) -> Optional[Tuple[str, WyckoffPhase, float, Optional[str]]]:
        """
        Phase B 主动检测逻辑 — 量化吸收校验重构版 (Wave 3)

        1. 数据切片与首尾剔除：提取 TR 持续天数 L（默认 60）对应的最近 L 根 K 线，截取中间 90% 数据中间集，防范 SC/Spring 等极端噪点污染波段统计。
        2. 波幅收敛校验 (Volatility Contraction)：前半段与后半段 Spread 均值之比，阈值 < 0.85。
        3. 量能非对称校验 (Volume Asymmetry)：通过 Weis Wave 生成器统计上涨与下跌波段总成交量之比，吸筹阈值 > 1.2，派发阈值 < 0.8。
        4. 综合吸收得分 (Accumulation Score / Distribution Score) 对置信度进行额外奖励或惩罚调降。
        """
        # 1. 提取 TR 切片数据并计算吸收得分
        tr_info = getattr(events, 'trading_range', None)
        L = 60
        if tr_info is not None:
            if hasattr(tr_info, 'duration_days'):
                L = getattr(tr_info, 'duration_days', 60)
            elif isinstance(tr_info, dict):
                L = tr_info.get('duration_days', tr_info.get('consolidation_duration_days', 60))
        if not L or pd.isna(L) or L <= 0:
            L = 60
        
        L = min(L, len(self.data))
        
        spread_ratio = 1.0
        v_up, v_down = 0.0, 0.0
        waves_generated = False
        
        if L >= 10:
            tr_df = self.data.tail(L)
            start_idx = int(0.05 * L)
            end_idx = int(0.95 * L)
            if end_idx - start_idx >= 4:
                middle_df = tr_df.iloc[start_idx:end_idx]
            else:
                middle_df = tr_df
            
            mid_len = len(middle_df)
            half = mid_len // 2
            if half >= 2:
                former_df = middle_df.iloc[:half]
                latter_df = middle_df.iloc[half:]
                
                spread_former = ((former_df['High'] - former_df['Low']) / former_df['Close'] * 100).mean()
                spread_latter = ((latter_df['High'] - latter_df['Low']) / latter_df['Close'] * 100).mean()
                
                if spread_former > 0 and not pd.isna(spread_former) and not pd.isna(spread_latter):
                    spread_ratio = spread_latter / spread_former
                    
            try:
                from ..weis_wave import WeisWaveGenerator
                generator = WeisWaveGenerator(middle_df, atr_multiplier=2.0)
                waves = generator.generate()
                v_up = sum(w.volume for w in waves if w.direction == 'up')
                v_down = sum(w.volume for w in waves if w.direction == 'down')
                waves_generated = True
            except Exception as e:
                logger.warning(f"Failed to generate Weis Waves on middle_df: {e}")
        
        # 计算得分
        acc_score = 0.0
        dist_score = 0.0
        
        if spread_ratio < 0.85:
            acc_score += 0.3
            dist_score += 0.3
            
        if waves_generated:
            if v_down > 0:
                vol_ratio_val = v_up / v_down
                if vol_ratio_val > 1.2:
                    acc_score += 0.4
            elif v_up > 0:
                acc_score += 0.4
                
            if v_up > 0:
                dist_vol_ratio_val = v_up / v_down if v_down > 0 else 999.0
                if dist_vol_ratio_val < 0.8:
                    dist_score += 0.4
            elif v_down > 0:
                dist_score += 0.4

        # 获取关键事件
        lps_events = getattr(events, 'lps_list', []) or []
        ut_events = getattr(events, 'ut_list', []) or []
        climax = getattr(events, 'climax', None)
        ar = getattr(events, 'automatic_reaction', None)
        st = getattr(events, 'secondary_test', None)

        # 检查是否有基础结构（Climax + AR；Phase B 还须 ST 或 ≥2 次区间测试）
        has_climax = self._safe_check_detected(climax)
        has_ar = self._safe_check_detected(ar)

        if not (has_climax and has_ar):
            return None

        # 统计 LPS 和 UT 数量
        lps_count = sum(1 for e in lps_events if self._safe_check_detected(e)) if lps_events else 0
        ut_count = sum(1 for e in ut_events if self._safe_check_detected(e)) if ut_events else 0

        # Phase B 判定：至少有 2 次支撑测试或多次震荡
        total_tests = lps_count + ut_count
        has_st = self._safe_check_detected(st)

        if not has_st and total_tests < 2:
            return None

        # 新增：检查 VSA 枯竭信号
        vsa_signals = getattr(events, 'vsa_signals', None) or {}
        has_no_supply = (vsa_signals.get('is_no_supply', False) if isinstance(vsa_signals, dict)
                         else getattr(vsa_signals, 'is_no_supply', False))
        has_no_demand = (vsa_signals.get('is_no_demand', False) if isinstance(vsa_signals, dict)
                         else getattr(vsa_signals, 'is_no_demand', False))

        ret_val = None
        # VSA 枯竭 + TR 中 = Phase B 强信号
        if (has_no_supply or has_no_demand) and total_tests >= 1:
            climax_type = getattr(climax, 'type', 'selling_climax') if has_climax else 'selling_climax'
            if climax_type == 'selling_climax':
                ret_val = (
                    'Accumulation Phase B (VSA供应枯竭测试)',
                    WyckoffPhase.PHASE_B,
                    0.70
                )
            else:
                ret_val = (
                    'Distribution Phase B (VSA无需求测试)',
                    WyckoffPhase.PHASE_B,
                    0.70
                )

        elif total_tests >= 2 or has_st:
            # 检查是否在 TR 中震荡
            tr_info = getattr(events, 'trading_range', None)
            in_tr = (tr_info.is_consolidation if hasattr(tr_info, 'is_consolidation')
                     else (tr_info.get('is_consolidation', False) if isinstance(tr_info, dict) else False))

            if in_tr or total_tests >= 2:
                climax_type = getattr(climax, 'type', 'selling_climax') if has_climax else 'selling_climax'

                if climax_type == 'selling_climax':
                    ret_val = (
                        'Accumulation Phase B (积累区震荡测试)',
                        WyckoffPhase.PHASE_B,
                        0.65 + min(total_tests * 0.05, 0.15)  # 测试次数越多置信度越高
                    )
                else:
                    ret_val = (
                        'Distribution Phase B (派发区震荡测试)',
                        WyckoffPhase.PHASE_B,
                        0.65 + min(total_tests * 0.05, 0.15)
                    )

        if ret_val is None:
            return None

        phase_label, phase_enum, conf = ret_val
        phase_note: Optional[str] = None
        climax_type = getattr(climax, 'type', 'selling_climax') if has_climax else 'selling_climax'

        # 应用量化吸收得分的置信度奖励与惩罚调降（文案写入 phase_description，不覆盖 phase 标签）
        if climax_type == 'selling_climax':
            score = acc_score
            if score >= 0.6:
                conf = min(0.90, conf + 0.15)
                phase_note = f"[经典威科夫吸筹特征确认] 筹码吸收极度强劲：波幅在整理期间显著收敛了 {max(0, int((1 - spread_ratio) * 100))}%"
                if waves_generated:
                    if v_down > 0:
                        phase_note += f"，且上涨波段的累积努力压倒下跌波段达 {max(0, int((v_up / v_down - 1) * 100))}%"
                    else:
                        phase_note += "，且上涨波段的累积努力完全压倒下跌波段"
                phase_note += "。"
            elif score < 0.3:
                conf = 0.50
                phase_note = f"[警告] 非吸收性无方向宽幅震荡整理 (波幅收敛比: {spread_ratio:.2f})，置信度降至 0.50。"
        else:  # buying_climax
            score = dist_score
            if score >= 0.6:
                conf = min(0.90, conf + 0.15)
                phase_note = f"[经典威科夫派发特征确认] 筹码派发特征明显：波幅在整理期间显著收敛了 {max(0, int((1 - spread_ratio) * 100))}%"
                if waves_generated:
                    if v_up > 0:
                        phase_note += f"，且下跌波段的累积派发努力压倒上涨波段达 {max(0, int((v_down / v_up - 1) * 100))}%"
                    else:
                        phase_note += "，且下跌波段的累积派发努力完全压倒上涨波段"
                phase_note += "。"
            elif score < 0.3:
                conf = 0.50
                phase_note = f"[警告] 非筹码派发性宽幅震荡整理 (波幅收敛比: {spread_ratio:.2f})，置信度降至 0.50。"

        return (phase_label, phase_enum, conf, phase_note)

    def _check_ambiguous_phase_structure(self, events: Dict) -> Optional[Tuple[str, WyckoffPhase, float]]:
        """
        🔧 方案B核心功能：识别和标记模糊结构

        处理"BC强但AR/ST缺失"的情况，给出更精确的阶段标签
        """
        climax = getattr(events, 'climax', None)
        has_strong_climax, climax_type, climax_confidence = self._get_climax_info(climax)

        # 方案B增强：设置BC强度阈值（只处理高置信度BC）
        if not has_strong_climax or climax_confidence < CLIMAX_CONFIDENCE_THRESHOLD:
            return None  # BC不够强或不存在，不是模糊结构

        # 安全地检查AR/ST
        ar = getattr(events, 'automatic_reaction', None)
        st = getattr(events, 'secondary_test', None)

        has_ar = self._safe_check_detected(ar)
        has_st = self._safe_check_detected(st)

        # 方案B核心：BC强但AR/ST缺失
        if not (has_ar or has_st):
            logger.info(f"[方案B] 检测到模糊结构: {climax_type} (置信度: {climax_confidence:.2f}), 缺失AR/ST确认")

            # 动态灵敏度调整：尝试检测"准AR"和"准ST"
            weak_ar = self._detect_weak_automatic_reaction(events, climax)
            weak_st = self._detect_weak_secondary_test(events, climax)

            trend_context = self._get_market_trend_context()
            return self._determine_ambiguous_phase(climax_type, weak_ar, weak_st, trend_context)

        return None  # 不是模糊结构

    def _safe_check_detected(self, event) -> bool:
        """安全地检查事件是否被检测到"""
        if event is None:
            return False

        if hasattr(event, 'detected'):
            return bool(event.detected)
        elif isinstance(event, dict):
            return bool(event.get('detected', False))

        return False

    def _safe_get_event_attribute(self, event, attr_name: str, default=None):
        """安全地获取事件属性 (兼容 Pydantic Model 和 dict)"""
        if event is None:
            return default
        return getattr(event, attr_name, event.get(attr_name, default) if isinstance(event, dict) else default)

    def _normalize_date(self, date) -> Optional[pd.Timestamp]:
        """
        统一时间戳处理为 pd.Timestamp 类型

        解决问题：事件中的date字段可能是多种类型
        - pd.Timestamp (来自 df.index)
        - str (字符串)
        - datetime.date
        - numpy.datetime64

        Args:
            date: 各种格式的日期

        Returns:
            统一的 pd.Timestamp，如果输入为None则返回None
        """
        if date is None:
            return None
        if isinstance(date, pd.Timestamp):
            return date
        try:
            return cast(pd.Timestamp, pd.Timestamp(date))
        except Exception as e:
            logger.debug(f"Failed to normalize date {date}: {e}")
            return None

    def _get_phase_a_penalty_factor(self, completeness_score: int) -> float:
        """根据Phase A完整性得分计算惩罚因子"""
        if completeness_score == 1:
            return PHASE_A_COMPLETENESS_PENALTY['extreme']
        elif completeness_score == 2:
            return PHASE_A_COMPLETENESS_PENALTY['severe']
        else:
            return PHASE_A_COMPLETENESS_PENALTY['moderate']

    def _get_climax_info(self, climax) -> Tuple[bool, Optional[str], float]:
        """
        安全地提取Climax信息

        Returns:
            (has_strong_climax, climax_type, climax_confidence)
        """
        if not climax:
            return False, None, 0.0

        has_strong_climax = False
        climax_type = None
        climax_confidence = 0.0

        # EventsModel 路径: 优先属性访问
        has_strong_climax = bool(getattr(climax, 'detected', climax.get('detected', False) if isinstance(climax, dict) else False))
        climax_type = self._safe_get_event_attribute(climax, 'type')
        climax_confidence = self._safe_get_event_attribute(climax, 'confidence', WEAK_SIGNAL_CONFIDENCE)

        return has_strong_climax, climax_type, climax_confidence

    def _get_market_trend_context(self) -> Dict[str, Any]:
        """获取当前市场趋势上下文信息"""
        current_price = self.data['Close'].iloc[-1]
        ma20 = self.data['MA20'].iloc[-1] if 'MA20' in self.data.columns else current_price
        ma50 = self.data['MA50'].iloc[-1] if 'MA50' in self.data.columns else current_price
        ma200 = self.data['MA200'].iloc[-1] if 'MA200' in self.data.columns else current_price

        return {
            'current_price': current_price,
            'ma20': ma20,
            'ma50': ma50,
            'ma200': ma200,
            'is_bullish_alignment': current_price > ma20 > ma50 > ma200,
            'is_bearish_alignment': current_price < ma20 < ma50,
            'is_above_ma200': current_price > ma200
        }

    def _determine_ambiguous_phase(self, climax_type: str, weak_ar: bool, weak_st: bool, trend_context: Dict) -> Optional[Tuple[str, WyckoffPhase, float]]:
        """
        根据Climax类型和市场趋势确定模糊阶段

        Returns:
            (phase_str, phase_enum, confidence) or None
        """
        if trend_context['is_bullish_alignment']:
            return self._handle_bullish_trend_ambiguous_phase(climax_type, weak_ar, weak_st)
        elif trend_context['is_bearish_alignment']:
            return self._handle_bearish_trend_ambiguous_phase(climax_type)
        else:
            return self._handle_neutral_trend_ambiguous_phase(climax_type)

    def _handle_bullish_trend_ambiguous_phase(self, climax_type: str, weak_ar: bool, weak_st: bool) -> Tuple[str, WyckoffPhase, float]:
        """处理多头趋势下的模糊阶段"""
        if climax_type == 'buying_climax':
            if weak_ar or weak_st:
                logger.info("[方案B] 判定为: Markup Phase E (上涨末期，潜在派发初期)")
                return ('Markup Phase E (上涨末期，潜在派发初期)', WyckoffPhase.PHASE_E,
                       CONFIDENCE_ADJUSTMENT['strong_markup_with_warning'])
            else:
                logger.info("[方案B] 判定为: Markup Phase E (强势上涨，伴有买入高潮警示)")
                return ('Markup Phase E (强势上涨，伴有买入高潮警示)', WyckoffPhase.PHASE_E,
                       CONFIDENCE_ADJUSTMENT['strong_markup_bc_warning'])
        else:  # selling_climax
            logger.info("[方案B] 判定为: Markup Phase E (强势上涨，但出现恐慌性抛售)")
            return ('Markup Phase E (强势上涨，但出现恐慌性抛售)', WyckoffPhase.PHASE_E,
                   CONFIDENCE_ADJUSTMENT['strong_markup_sc_warning'])

    def _handle_bearish_trend_ambiguous_phase(self, climax_type: str) -> Tuple[str, WyckoffPhase, float]:
        """处理空头趋势下的模糊阶段"""
        if climax_type == 'buying_climax':
            logger.info("[方案B] 判定为: Distribution Phase A (买入高潮，等待回落确认)")
            return ('Distribution Phase A (买入高潮，等待回落确认)', WyckoffPhase.PHASE_A,
                   CONFIDENCE_ADJUSTMENT['distribution_a_pending'])
        else:  # selling_climax
            logger.info("[方案B] 判定为: Accumulation Phase A (恐慌抛售，等待反弹确认)")
            return ('Accumulation Phase A (恐慌抛售，等待反弹确认)', WyckoffPhase.PHASE_A,
                   CONFIDENCE_ADJUSTMENT['accumulation_a_pending'])

    def _handle_neutral_trend_ambiguous_phase(self, climax_type: str) -> Tuple[str, WyckoffPhase, float]:
        """处理震荡趋势下的模糊阶段"""
        if climax_type == 'buying_climax':
            logger.info("[方案B] 判定为: Trending with BC Warning (趋势推进中，买入高潮警示)")
            return ('Trending with BC Warning (趋势推进中，买入高潮警示)', WyckoffPhase.UNKNOWN,
                   CONFIDENCE_ADJUSTMENT['trending_bc_warning'])
        else:
            logger.info("[方案B] 判定为: Trending with SC Warning (趋势整理中，恐慌抛售警示)")
            return ('Trending with SC Warning (趋势整理中，恐慌抛售警示)', WyckoffPhase.UNKNOWN,
                   CONFIDENCE_ADJUSTMENT['trending_sc_warning'])

    def _detect_weak_automatic_reaction(self, events: Dict, climax) -> bool:
        """
        🔧 动态灵敏度调整：检测"准AR"信号

        放宽AR检测条件，寻找"微弱的价格反应"
        """
        climax_date = self._safe_get_event_attribute(climax, 'date')
        if not climax_date:
            return False

        try:
            df_after = self.data[self.data.index > climax_date].head(SPRING_WINDOW_DAYS)
            if len(df_after) < MIN_DATA_POINTS:
                return False

            climax_price = self._safe_get_event_attribute(climax, 'price')
            if not climax_price:
                return False

            climax_type = self._safe_get_event_attribute(climax, 'type')

            if climax_type == 'buying_climax':
                return self._check_weak_ar_after_buying_climax(df_after, climax_price)
            else:  # selling_climax
                return self._check_weak_ar_after_selling_climax(df_after, climax_price)

        except Exception as e:
            logger.debug(f"Weak AR detection failed: {e}")
            return False

    def _check_weak_ar_after_buying_climax(self, df_after: pd.DataFrame, bc_price: float) -> bool:
        """检查买入高潮后的微弱回落"""
        high_after_bc = df_after['High'].iloc[0:5].max()
        # 准AR条件：价格没有创新高，显示上涨动力衰竭
        return high_after_bc < bc_price * (1 + PRICE_TOLERANCE_PCT)

    def _check_weak_ar_after_selling_climax(self, df_after: pd.DataFrame, sc_price: float) -> bool:
        """检查卖出高潮后的微弱反弹"""
        low_after_sc = df_after['Low'].iloc[0:5].min()
        # 准AR条件：价格没有创新低，显示抛压减轻
        return low_after_sc > sc_price * (1 - PRICE_TOLERANCE_PCT)

    def _detect_weak_secondary_test(self, events: Dict, climax) -> bool:
        """
        🔧 动态灵敏度调整：检测"准ST"信号

        放宽ST检测条件，寻找"量能萎缩的价格测试"
        """
        climax_date = self._safe_get_event_attribute(climax, 'date')
        climax_price = self._safe_get_event_attribute(climax, 'price')
        climax_volume = self._safe_get_event_attribute(climax, 'volume')

        if not (climax_date and climax_price):
            return False

        try:
            df_after = self.data[self.data.index > climax_date].head(SPRING_WINDOW_DAYS)
            if len(df_after) < MIN_DATA_POINTS + 2:  # Need at least 5 data points
                return False

            climax_type = self._safe_get_event_attribute(climax, 'type')

            if climax_type == 'buying_climax':
                return self._check_weak_st_after_buying_climax(df_after, climax_price)
            else:  # selling_climax
                return self._check_weak_st_after_selling_climax(df_after, climax_price)

        except Exception as e:
            logger.debug(f"Weak ST detection failed: {e}")
            return False

    def _check_weak_st_after_buying_climax(self, df_after: pd.DataFrame, bc_high: float) -> bool:
        """检查买入高潮后的准ST信号"""
        recent_highs = df_after['High'].tail(10)

        # 准ST条件1：价格接近BC高点（容差放宽到3%）
        price_test = (recent_highs >= bc_high * (1 - WEAK_PRICE_TOLERANCE_PCT)).any()

        # 准ST条件2：量能显著萎缩
        volume_ma = self._get_volume_ma(df_after)
        vol_shrinkage = (df_after['Volume'].tail(5) < volume_ma * VOLUME_RATIO_THRESHOLDS['normal']).any()

        return price_test or vol_shrinkage

    def _check_weak_st_after_selling_climax(self, df_after: pd.DataFrame, sc_low: float) -> bool:
        """检查卖出高潮后的准ST信号"""
        recent_lows = df_after['Low'].tail(10)

        # 准ST条件1：价格接近SC低点（容差放宽到3%）
        price_test = (recent_lows <= sc_low * (1 + WEAK_PRICE_TOLERANCE_PCT)).any()

        # 准ST条件2：量能显著萎缩
        volume_ma = self._get_volume_ma(df_after)
        vol_shrinkage = (df_after['Volume'].tail(5) < volume_ma * VOLUME_RATIO_THRESHOLDS['normal']).any()

        return price_test or vol_shrinkage

    def _get_volume_ma(self, df: pd.DataFrame) -> float:
        """获取量能移动平均值"""
        if 'Volume_MA20' in self.data.columns:
            return self.data['Volume_MA20'].iloc[-1]
        else:
            return df['Volume'].mean()

    def _fallback_logic(self, events: Dict = None) -> Tuple[str, WyckoffPhase, float]:
        """基于均线排布的降级判定逻辑"""
        current = self.data['Close'].iloc[-1]
        
        def get_ma(period):
            if self._indicator_cache:
                try:
                    return self._indicator_cache.get(f'MA{period}').iloc[-1]
                except Exception:
                    pass
            col = f'MA{period}'
            if col in self.data.columns:
                return self.data[col].iloc[-1]
            return self.data['Close'].rolling(window=period).mean().iloc[-1]

        ma20 = get_ma(20)
        ma50 = get_ma(50)
        ma200 = get_ma(200)
        
        #  新增：利用交易区间内的吸收特征提前判定再积累
        if events:
            tr = self._get_event(events, 'trading_range') or {}
            absorption = (getattr(tr, 'absorption_detected', False) if tr and hasattr(tr, 'absorption_detected')
                          else (tr.get('absorption_detected', False) if isinstance(tr, dict) else False))
            if absorption:
                if current > ma200:
                    return "Reaccumulation Phase C/D (再积累确认，供应已被吸收)", WyckoffPhase.PHASE_D, 0.75
        
        if current > ma20 > ma50 > ma200: 
            return "Markup Phase E (强势上涨)", WyckoffPhase.PHASE_E, 0.6
        if current < ma20 < ma50 < ma200: 
            return "Markdown Phase E (强势下跌)", WyckoffPhase.PHASE_E, 0.6
            
        return "Trending (趋势中)", WyckoffPhase.UNKNOWN, 0.4

    def _check_ma_confirmation(self, phase: Union[str, WyckoffPhase]) -> float:
        """检查均线确认"""
        current = self.data['Close'].iloc[-1]
        ma200 = self.data['MA200'].iloc[-1] if 'MA200' in self.data.columns else current
        if PhaseAdapter.is_accumulation(phase) or PhaseAdapter.is_markup(phase): 
            return 0.8 if current > ma200 else 0.4
        if PhaseAdapter.is_distribution(phase) or PhaseAdapter.is_markdown(phase): 
            return 0.8 if current < ma200 else 0.4
        return 0.5

    def _check_volume_confirmation(self, phase: Union[str, WyckoffPhase]) -> float:
        """检查成交量确认 (Effort vs Result) - 引入波段累积量能分析"""
        df = self.data.tail(40)  # 扩大观察窗口以包含完整的波段
        if len(df) < 5:
            return 0.5

        up_days = df[df['Close'] > df['Close'].shift(1)]
        dn_days = df[df['Close'] < df['Close'].shift(1)]
        
        up_v_mean = up_days['Volume'].mean() if not up_days.empty else 0
        dn_v_mean = dn_days['Volume'].mean() if not dn_days.empty else 0
        ratio = up_v_mean / dn_v_mean if dn_v_mean > 0 else 1.0
        
        # 波段累积量能：计算上行波段和下行波段的总量能
        up_v_sum = up_days['Volume'].sum()
        dn_v_sum = dn_days['Volume'].sum()
        sum_ratio = up_v_sum / dn_v_sum if dn_v_sum > 0 else 1.0

        if PhaseAdapter.is_accumulation(phase):
            # 吸筹期：下行波段量能萎缩，上行波段量能放大
            return 0.9 if sum_ratio > 1.2 else (0.7 if sum_ratio > 0.8 else 0.4)
        if PhaseAdapter.is_distribution(phase):
            # 派发期：上行波段量能萎缩，下行波段量能放大
            return 0.9 if sum_ratio < 0.8 else (0.7 if sum_ratio < 1.2 else 0.4)
        if PhaseAdapter.is_markup(phase): 
            return 0.9 if ratio > 1.2 else 0.5
        if PhaseAdapter.is_markdown(phase): 
            return 0.9 if ratio < 0.8 else 0.5
            
        return 0.5

    def filter_relevant_events(self, events: Dict, lookback_days: int = 120) -> Dict:
        """
        🔧 修复信号穿越问题：过滤掉时间跨度过大的“过期”证据
        对于当前阶段识别，只考虑最近 120 个交易日内的信号。
        """
        filtered = {}
        for key, event in events.items():
            if not event:
                continue

            date = None
            # 安全地获取日期信息
            if isinstance(event, dict):
                date = event.get('date')
                if not date and 'data' in event:
                    data = event.get('data', {})
                    if isinstance(data, dict):
                        date = data.get('date')
                    elif hasattr(data, 'date'):
                        date = data.date
            elif hasattr(event, 'date'):
                date = event.date
            elif hasattr(event, 'get'):
                # 可能是具有get方法的对象（如某些包装类）
                try:
                    date = event.get('date')
                except AttributeError:
                    pass

            if date:
                age = self._get_signal_age_days(date)
                # 如果信号超过 120 天，视为“历史因果”，不再作为当前相位证据
                if age < lookback_days:
                    filtered[key] = event
                else:
                    logger.debug(f"Filtered out historical signal {key} from {date} (age: {age} days)")
            else:
                filtered[key] = event
        return filtered

    def _calculate_structural_integrity(self, events: Dict, phase: WyckoffPhase) -> float:
        """
        计算结构完整性因子 (Phase A 四大支柱：PS → SC/BC → AR → ST)
        """
        climax = self._get_event(events, 'climax')
        ar = self._get_event(events, 'automatic_reaction')
        st = self._get_event(events, 'secondary_test')
        ps_event = self._get_event(events, 'preliminary_support')
        ps_detected = False
        if ps_event:
            ps_detected = self._safe_check_detected(ps_event)

        count = 0
        if climax and (isinstance(climax, dict) and climax.get('detected') or getattr(climax, 'detected', False)):
            count += 1
        if ar and (isinstance(ar, dict) and ar.get('detected') or getattr(ar, 'detected', False)):
            count += 1
        if st and (isinstance(st, dict) and st.get('detected') or getattr(st, 'detected', False)):
            count += 1
        if ps_detected:
            count += 1

        # 如果 4 个支柱只剩 1-2 个，置信度打折
        if count <= 1:
            return 0.4
        if count == 2:
            return 0.6
        if count == 3:
            return 0.85
        return 1.0

    def calculate_sequence_score(self, events: Dict, phase: Union[str, WyckoffPhase]) -> Dict:
        """计算事件序列完整性得分"""
        count = 0
        from ...schemas import DualEventModel as _DEMC
        checks = ['climax', 'automatic_reaction', 'secondary_test', 'spring_upthrust', 'sos_sow']
        for c in checks:
            event = self._get_event(events, c)
            if event:
                if isinstance(event, _DEMC):
                    if getattr(event.data, 'detected', False):
                        count += 1
                elif hasattr(event, 'detected') and event.detected:
                    count += 1
            
        completeness = (count / len(checks)) * 100
        factor = 1.0 if completeness >= 80 else 0.8 if completeness >= 60 else 0.6
        return {
            'completeness': completeness, 
            'adjustment_factor': factor, 
            'rating': 'S' if completeness >= 80 else 'B' if completeness >= 60 else 'C'
        }

    def _check_logical_consistency(self, events: Dict, phase_str: str, phase_enum: WyckoffPhase, confidence: float) -> Tuple[str, WyckoffPhase, float]:
        """
        🔧 修复矛盾二：执行相位逻辑互斥检查
        
        威科夫逻辑准则：
        1. 如果检测到 LPS (最后支撑) 或 JOC (跳跃小溪)，说明当前处于上涨推进 (Markup) 或 再积累 (Reaccumulation)。
           即使日线有 SOW 或 FTI 信号，也不能判定为 Distribution (派发)。
        2. 如果价格创出新高且出现 LPS，强制修正相位为 Markup 或 Accumulation Phase D/E。
        """
        # 获取具体的检测标志
        is_lps = False
        lps_event = self._get_event(events, 'lps')
        if lps_event:
            is_lps = lps_event.get('detected') if isinstance(lps_event, dict) else getattr(lps_event, 'detected', False)

        is_joc = False
        joc_event = self._get_event(events, 'joc')
        if joc_event:
            is_joc = joc_event.get('detected') if isinstance(joc_event, dict) else getattr(joc_event, 'detected', False)
            
        is_distribution = (
            PhaseAdapter.is_distribution(phase_enum)
            or PhaseAdapter.is_markdown(phase_enum)
            or PhaseAdapter.is_distribution(phase_str)
            or PhaseAdapter.is_markdown(phase_str)
        )
        
        current_price = self.data['Close'].iloc[-1]
        ma200 = self.data['MA200'].iloc[-1] if 'MA200' in self.data.columns else current_price
        
        # 规则 1：LPS 与 Distribution 互斥 — Phase D 须 JOC 确认
        if is_lps and is_distribution:
            if is_joc:
                if current_price > ma200:
                    return 'Markup (趋势上涨中继)', WyckoffPhase.PHASE_E, 0.75
                return 'Accumulation Phase D (积累期突破中)', WyckoffPhase.PHASE_D, 0.70
            return 'Accumulation Phase C+ (LPS出现待JOC确认)', WyckoffPhase.PHASE_C, 0.65
                
        # 规则 2：JOC 证伪派发 A
        if is_joc and 'Phase A' in phase_str and 'Distribution' in phase_str:
            # 价格已跳跃小溪，不是买入高潮停止，而是强力推进
            return 'Markup Phase E (强势超买推进)', WyckoffPhase.PHASE_E, 0.80
            
        return phase_str, phase_enum, confidence
