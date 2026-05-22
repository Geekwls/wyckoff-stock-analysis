#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段协调器 (Phase Coordinator)

负责协调威科夫阶段识别的复杂逻辑，包括事件收集、阶段验证等。
从 WyckoffPatternDetector 中提取出来，以解决 God Object 问题。
"""

import pandas as pd
from typing import Dict, List, Tuple, Any, Optional
from ..schemas import (
    ClimaxModel, WyckoffEventModel, SpringModel, UpthrustModel,
    SosModel, SowModel, LpsModel, LpsyModel, TradingRangeModel,
    JocModel, FtiModel, DualEventModel, EventsModel
)
from ..config.settings import WyckoffConfig
from .sequence_validator import SequenceValidator
from .event_arbitrator import EventArbitrator
from .breakout_analyzer import BreakoutAnalyzer
import logging
import functools

logger = logging.getLogger(__name__)



@functools.lru_cache(maxsize=32)
def _get_pydantic_fields(model_cls):
    """缓存 Pydantic v1/v2 版本检查结果，避免在热路径上重复检测"""
    if hasattr(model_cls, "model_fields"):
        return frozenset(model_cls.model_fields.keys())
    return frozenset(model_cls.__fields__.keys())

class PhaseCoordinator:
    """
    阶段协调器

    负责协调多个检测器来识别威科夫阶段，处理事件收集和验证逻辑。
    """

    def __init__(self, pattern_detector):
        """
        初始化阶段协调器

        Args:
            pattern_detector: WyckoffPatternDetector 实例，用于调用各个检测方法
        """
        self.detector = pattern_detector
        self.arbitrator = None  # 事件仲裁器，稍后初始化
        self.breakout_analyzer = None  # 突破分析器，稍后初始化

    def collect_all_events(self) -> Dict[str, Any]:
        """
        收集所有威科夫事件供阶段识别使用

        策略：
        1. 采用"延迟定性"策略，先收集所有物理特征
        2. 用已识别的事件边界更新交易区间（如派发期：BC高=TR上沿，AR低=TR下沿）
        3. 在所有事件收集完毕后，通过 validate_phase_consistency 进行逻辑验证和证伪

        Returns:
            包含所有检测到的事件的字典
        """
        #  P0-2修复步骤1：在每次分析开始时重置屏蔽状态，避免污染
        if hasattr(self.detector, 'sw_detector'):
            self.detector.sw_detector.reset_blocked_signals()

        # 1. 收集基础价格形态（不依赖全局阶段）
        #  P3修复：弃用旧的基于固定百分比的 detect_climax，全面拥抱动态 ATR 的 SC/BC
        sc_res = self.detector.detect_climax_panic_selling()
        bc_res = self.detector.detect_climax_buying()
        
        # 仲裁：如果同时检测到SC和BC（比如先暴涨后暴跌），取距离当前最近的一个作为主高潮
        if sc_res.get('detected') and bc_res.get('detected'):
            climax_res = sc_res if sc_res.get('date') > bc_res.get('date') else bc_res
        elif sc_res.get('detected'):
            climax_res = sc_res
        elif bc_res.get('detected'):
            climax_res = bc_res
        else:
            climax_res = {'detected': False}
        ar_res = self.detector.detect_automatic_reaction(climax_res)
        st_res = self.detector.detect_secondary_test(climax_res, ar_res)

        ps_res = self.detector.detect_preliminary_support()
        psy_res = self.detector.detect_preliminary_supply()

        spring_res = self.detector.detect_spring()
        upthrust_res = self.detector.detect_upthrust()

        boring_zone_res = self.detector.detect_boring_zone()
        choch_res = self.detector.detect_choch()

        # P1 修复：存储完整Phase A事件(PS→SC/BC→AR→ST)到detector
        phase_a_events = {
            'ps': ps_res,
            'psy': psy_res,
            'climax': climax_res,
            'ar': ar_res,
            'st': st_res
        }
        # 设置到所有子detector中
        for detector in self.detector.all_detectors:
            if hasattr(detector, 'set_phase_a_events'):
                detector.set_phase_a_events(phase_a_events)

        # 2. 初步阶段识别
        preliminary_phase = self._preliminary_phase_identification(
            climax_res, ar_res, st_res, spring_res, upthrust_res, ps_res, psy_res, choch_res
        )

        #  P0-2修复步骤2：初步阶段识别后立即屏蔽矛盾信号（从源头杜绝信号污染）
        if hasattr(self.detector, 'sw_detector'):
            if 'Distribution' in preliminary_phase:
                # 派发期的向上突破一律归为UT，禁用SOS检测
                self.detector.sw_detector.block_signal('sos')
                logger.info(f"[P0-2修复] 初步识别为{preliminary_phase}，屏蔽SOS检测")
            elif 'Accumulation' in preliminary_phase:
                # 吸筹期的向下突破应归类为Spring，禁用SOW检测
                self.detector.sw_detector.block_signal('sow')
                logger.info(f"[P0-2修复] 初步识别为{preliminary_phase}，屏蔽SOW检测")

        # 3. 用威科夫事件边界更新交易区间检测器
        # UTAD检测需要移到这里，以便在更新TR边界时使用
        utad_res = self.detector.detect_utad()

        self._update_trading_range_from_events(climax_res, ar_res, preliminary_phase, utad_res)

        # 统一更新子检测器的分析上下文
        self.detector._update_all_detectors_context(preliminary_phase)

        # 4. 收集趋势/强度信号（此时 TR 已使用已知边界）
        sos_res = self.detector.detect_sos()
        sow_res = self.detector.detect_sow()

        tr_res = self.detector.detect_trading_range()
        lps_res = self.detector.detect_lps(sos_res, spring_res, trading_range=tr_res)
        lpsy_res = self.detector.detect_lpsy(trading_range=tr_res)
        joc_res = self.detector.detect_joc()
        fti_res = self.detector.detect_fti()


        # 5.5. 运行事件仲裁（解决信号冲突）
        arbitration_raw = {
            'spring': spring_res,
            'upthrust': upthrust_res,
            'sos': sos_res,
            'sow': sow_res,
            'lps': lps_res,
            'lpsy': lpsy_res,
            'joc': joc_res,
            'fti': fti_res,
        }
        arbitration_result = self._arbitrate_events(arbitration_raw)

        #  新增：构建 LPS/UT 序列列表供 Phase B 检测使用
        lps_list = self._build_lps_sequence(arbitration_raw)
        ut_list = self._build_ut_sequence(arbitration_raw)

        # 6. 统一使用强类型模型封装
        # 安全地构造Pydantic模型：过滤掉dict中模型不存在的字段
        def _safe_model(model_cls, data: dict):
            # 兼容 Pydantic v1 和 v2（带缓存，避免热路径重复检测）
            valid_fields = _get_pydantic_fields(model_cls)
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return model_cls(**filtered)

        # 保存原始检测结果供 scoring 引擎使用
        raw_events_map = {
            'spring': spring_res,
            'upthrust': upthrust_res,
            'sos': sos_res,
            'sow': sow_res,
            'lps': lps_res,
            'lpsy': lpsy_res,
            'joc': joc_res,
            'fti': fti_res,
            'secondary_test': st_res,
            'automatic_reaction': ar_res,
            'preliminary_support': ps_res,
            'utad': utad_res,
        }
        # 5.6. 分析突破质量（在tr_res和trading_range创建后调用）
        trading_range_model = _safe_model(TradingRangeModel, tr_res)
        breakout_analysis = self.analyze_breakout_quality(tr_res)

        from ..schemas import DualEventModel, EventsModel, BoringZoneModel, BreakoutAnalysisModel, SequenceValidationModel
        
        events_dict = {
            'trading_range': trading_range_model,
            'lps_list': lps_list,
            'ut_list': ut_list,
            'climax': _safe_model(ClimaxModel, climax_res),
            'automatic_reaction': _safe_model(WyckoffEventModel, ar_res) if ar_res.get('detected') else WyckoffEventModel(detected=False),
            'secondary_test': _safe_model(WyckoffEventModel, st_res) if st_res.get('detected') else WyckoffEventModel(detected=False),
            'spring': _safe_model(SpringModel, spring_res),
            'upthrust': _safe_model(UpthrustModel, upthrust_res),
            'sos': _safe_model(SosModel, sos_res),
            'sow': _safe_model(SowModel, sow_res),
            'lps': _safe_model(LpsModel, lps_res),
            'lpsy': _safe_model(LpsyModel, lpsy_res),
            'joc': _safe_model(JocModel, joc_res) if joc_res.get('detected') else None,
            'fti': _safe_model(FtiModel, fti_res) if fti_res.get('detected') else None,
            'boring_zone': _safe_model(BoringZoneModel, boring_zone_res) if boring_zone_res and isinstance(boring_zone_res, dict) else None,
            'phase_revision_log': [],
            'arbitration_result': _safe_model(ArbitrationResult, arbitration_result) if arbitration_result and isinstance(arbitration_result, dict) else None,
            'breakout_analysis': _safe_model(BreakoutAnalysisModel, breakout_analysis) if breakout_analysis and isinstance(breakout_analysis, dict) else None,
            'preliminary_support': _safe_model(WyckoffEventModel, ps_res) if ps_res.get('detected') else WyckoffEventModel(detected=False),
            'preliminary_supply': _safe_model(WyckoffEventModel, psy_res) if psy_res.get('detected') else WyckoffEventModel(detected=False),
            'utad': _safe_model(WyckoffEventModel, utad_res) if utad_res.get('detected') else WyckoffEventModel(detected=False),
            'choch': _safe_model(WyckoffEventModel, choch_res) if choch_res.get('detected') else WyckoffEventModel(detected=False),
        }

        if spring_res.get('detected'):
            events_dict['spring_upthrust'] = DualEventModel(_type='spring', data=_safe_model(SpringModel, spring_res))
        elif upthrust_res.get('detected'):
            events_dict['spring_upthrust'] = DualEventModel(_type='upthrust', data=_safe_model(UpthrustModel, upthrust_res))

        if sos_res.get('detected'):
            events_dict['sos_sow'] = DualEventModel(_type='sos', data=_safe_model(SosModel, sos_res))
        elif sow_res.get('detected'):
            events_dict['sos_sow'] = DualEventModel(_type='sow', data=_safe_model(SowModel, sow_res))

        # lps_lpsy 字典已废弃，lps/lpsy 已单独存于 EventsModel.lps / .lpsy

        events_model = EventsModel(**events_dict)

        # 5. 运行事件序列验证（使用完整的 Pydantic 模型）
        from .sequence_validator import SequenceValidator
        from ..schemas import SequenceValidationModel
        seq_val_res = SequenceValidator(events_model, self.detector.data).validate_all()
        events_model.sequence_validation = _safe_model(SequenceValidationModel, seq_val_res)

        # 6.6. 应用 Phase 转换标准
        if preliminary_phase and 'Unknown' not in preliminary_phase:
            transitioned_phase, trans_confidence = self.transition_phase_with_criteria(preliminary_phase, events_model)
            if transitioned_phase != preliminary_phase:
                logger.info(
                    f"[Phase Transition] {preliminary_phase} → {transitioned_phase} "
                    f"(置信度: {trans_confidence:.2f})"
                )
                events_model.phase_revision_log.append(
                    f"[Phase Transition] {preliminary_phase} → {transitioned_phase} (置信度:{trans_confidence:.0%})"
                )
                preliminary_phase = transitioned_phase

        self.detector._update_all_detectors_context(preliminary_phase)

        # 7. 执行证伪验证
        final_phase, revision_logs = self.validate_phase_consistency(
            preliminary_phase, events_model, arbitration_result, breakout_analysis
        )
        events_model.phase_revision_log.extend(revision_logs)

        self.detector._update_all_detectors_context(final_phase)

        return events_model

    def _update_trading_range_from_events(self, climax_res: Dict, ar_res: Dict, phase: str, utad_res: Dict = None):
        """
        从威科夫事件更新交易区间边界

        派发期：TR上沿 = BC高点, TR下沿 = AR低点
        积累期：TR上沿 = AR高点, TR下沿 = SC低点
        UTAD增强：若检测到UTAD，使用UTAD突破位作为派发区上沿
        """
        tr_detector = self.detector.range_detector

        if 'Distribution' in phase:
            bc_high = climax_res.get('price') if climax_res.get('type') == 'buying_climax' else None
            ar_low = ar_res.get('price') if ar_res.get('detected') else None

            # 孟洪涛原则：UTAD 是派发区上沿的更准确参考
            if utad_res and utad_res.get('detected'):
                utad_high = utad_res.get('breakout_price')
                if utad_high:
                    bc_high = max(bc_high or 0, utad_high)
                    logger.info(f"[孟洪涛原则] UTAD检测到派发区上沿更新: {utad_high:.2f}")

            if bc_high and ar_low and bc_high > ar_low:
                tr_detector.update_from_phase_events(bc_high, ar_low, "BC-AR")
                return
        elif 'Accumulation' in phase:
            sc_low = climax_res.get('price') if climax_res.get('type') == 'selling_climax' else None
            ar_high = ar_res.get('price') if ar_res.get('detected') else None
            if sc_low and ar_high and ar_high > sc_low:
                tr_detector.update_from_phase_events(ar_high, sc_low, "SC-AR")

    def _detect_prior_trend(self) -> str:
        """识别前序趋势 (Markup / Markdown)"""
        df = self.detector.data
        if len(df) < 60: return 'neutral'
        
        # 使用 50/200 均线及价格斜率判断
        ma50 = df['Close'].rolling(50).mean().iloc[-1]
        ma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else df['Close'].rolling(100).mean().iloc[-1]
        
        if ma50 > ma200 * 1.05: return 'markup'
        if ma50 < ma200 * 0.95: return 'markdown'
        return 'neutral'

    def _preliminary_phase_identification(
        self,
        climax_res: Dict,
        ar_res: Dict,
        st_res: Dict,
        spring_res: Dict,
        upthrust_res: Dict,
        ps_res: Optional[Dict] = None,
        psy_res: Optional[Dict] = None,
        choch_res: Optional[Dict] = None
    ) -> str:
        """
        初步阶段识别：基于已收集的事件进行初步判断

        优化：增加 PS/SC 确认链条和 AR/ST 协同校验。
        Phase A 完整链条: PS → SC/BC → AR → ST
        """
        is_ps = ps_res.get('detected') if ps_res else False
        is_psy = psy_res.get('detected') if psy_res else False
        is_sc = climax_res.get('detected') and climax_res.get('type') == 'selling_climax'
        is_bc = climax_res.get('detected') and climax_res.get('type') == 'buying_climax'
        is_ar = ar_res.get('detected')
        is_st = st_res.get('detected')
        
        # P1: 再吸筹识别 (Re-accumulation Mode)
        prior_trend = self._detect_prior_trend()
        if prior_trend == 'markup':
            # 在上涨趋势中，即使没有明显的 SC，只要有回踩后的 AR 和 ST
            if not is_sc and is_ar and is_st:
                return 'Accumulation Phase A (Re-accumulation)'
        
        # 派发初步迹象：BC + AR + ST（至少BC+AR）
        phase = 'Unknown'
        if is_bc and is_ar and is_st:
            phase = 'Distribution Phase A'  # 置信度高：完整结构 BC+AR+ST
        elif is_bc and is_ar:
            phase = 'Distribution Phase A'  # 置信度中：BC+AR，ST 待确认
        # 孟洪涛原则：PSY + BC 也是强有力的派发信号
        elif is_psy and is_bc:
            phase = 'Distribution Phase A'  # 置信度中：PSY+BC，预警派发
        # 吸筹初步迹象：SC + AR（至少两者）才确认 Phase A 结构启动
        elif is_sc and is_ar and is_st:
            phase = 'Accumulation Phase A'  # 置信度高：完整结构 SC+AR+ST
        elif is_sc and is_ar:
            phase = 'Accumulation Phase A'  # 置信度中：SC+AR，ST 待确认
        # PS (初次支撑) + SC 确认吸筹结构启动（PS 存在时降低对 AR 的要求）
        elif is_ps and is_sc:
            phase = 'Accumulation Phase A'  # 置信度低：PS+SC，等待 AR 确认

        # 孟洪涛原则：Spring 是最重要形态（书中提及 136 次）
        # Spring 直接跳转到 Phase C，且给予最高置信度
        if spring_res.get('detected'):
            # 评估 Spring 质量：type_3_safe > type_2_neutral > type_1_dangerous
            spring_signals = spring_res.get('signals', [])
            latest_spring = spring_res.get('latest_spring', {})
            if isinstance(latest_spring, dict):
                spring_type = latest_spring.get('spring_type', 'type_2_neutral')
                if spring_type == 'type_3_safe':
                    return 'Accumulation Phase C'
                elif spring_type == 'type_2_neutral':
                    return 'Accumulation Phase C'
                else:
                    return 'Accumulation Phase B'
            return 'Accumulation Phase C'

        # Upthrust 阶段升级校验：严格区分 Phase B 普通阻力测试与 Phase C 决断性 UTAD/诱多
        if upthrust_res.get('detected'):
            latest_ut = upthrust_res.get('latest_upthrust')
            is_utad = False
            try:
                utad_check = self.detector.detect_utad()
                is_utad = utad_check.get('detected', False)
            except Exception:
                pass
            
            is_valid_ut = False
            if latest_ut:
                # 检查最新 upthrust 信号的有效性、回落效率与跟随性
                is_valid = latest_ut.get('is_valid', True)
                rejection_days = latest_ut.get('rejection_days', 99)
                ft_quality = latest_ut.get('follow_through_quality', 0.0)
                
                # 快速跌回且具有向下跟随性，或已被直接识别为 UTAD
                is_strong_rejection = rejection_days <= 3 and ft_quality >= 33.0
                if is_valid and (is_strong_rejection or is_utad):
                    is_valid_ut = True
            
            # 联合证据：伴随向下特征变异（CHoCH down）
            has_weakness_confirm = False
            if choch_res and choch_res.get('detected') and choch_res.get('direction') == 'down':
                has_weakness_confirm = True
            
            if is_valid_ut or has_weakness_confirm:
                return 'Distribution Phase C'
            else:
                # 不满足强证据链的普通上冲，仅归为 Phase B 普通阻力测试，防范交易指令逻辑越位
                return 'Distribution Phase B (Upthrust阻力测试)'

        # 孟洪涛：CHoCH 是阶段转换的终极确认 (P0)
        if choch_res and choch_res.get('detected'):
            direction = choch_res.get('direction')
            if direction == 'up':
                return 'Accumulation Phase A (CHoCH 确认特征变异)'
            else:
                return 'Distribution Phase A (CHoCH 确认特征变异)'

        # 长周期重构检查 (避免 2 年以上长跨度机械停留在 Phase A)
        if 'Phase A' in phase and hasattr(self.detector, 'data') and self.detector.data is not None and not self.detector.data.empty:
            df = self.detector.data
            
            # 安全处理不同类型的索引，防止强转崩溃
            import numpy as np
            idx_val = df.index[-1]
            if isinstance(idx_val, pd.Timestamp):
                last_date = idx_val
            elif isinstance(idx_val, (int, float, np.integer, np.floating)):
                last_date = pd.Timestamp.now()
            else:
                try:
                    last_date = pd.Timestamp(idx_val)
                except Exception:
                    last_date = pd.Timestamp.now()
            earliest_date = None
            for res in [psy_res, ps_res, climax_res]:
                if res and res.get('detected') and res.get('date'):
                    d = pd.Timestamp(res.get('date'))
                    if earliest_date is None or d < earliest_date: earliest_date = d
            if earliest_date:
                days_diff = (last_date - earliest_date).days
                bars_count = len(df[df.index >= earliest_date])
                if days_diff > 365 or bars_count > 100:
                    current_price = df['Close'].iloc[-1]
                    tr = self.detector.detect_trading_range()
                    tr_high = tr.get('high', 0) if isinstance(tr, dict) else getattr(tr, 'high', 0)
                    tr_low = tr.get('low', 0) if isinstance(tr, dict) else getattr(tr, 'low', 0)
                    if tr_high > tr_low:
                        pos_ratio = (current_price - tr_low) / (tr_high - tr_low)
                        if pos_ratio >= 0.7:
                            logger.info(f"[长周期重构] 箱体跨度{days_diff}天/K线{bars_count}根，高位蓄力，由{phase}升级为再吸筹突破过渡期")
                            return "Accumulation Phase C/D (Re-accumulation / JOC 蓄力)"
                        elif pos_ratio <= 0.3:
                            return "Distribution Phase C/D (高位派发破位前夕)"
                    return "Consolidation Phase B/C (长周期宽幅震荡过渡)"

        return phase


    def _replace_phase_type(self, phase: Optional[str], new_type: str) -> str:
        """替换阶段类型或阶段字母。

        根据 new_type 判断操作：
        - new_type='Phase X' → 替换 Phase 字母（保留前缀类型 Accumulation/Distribution）
        - new_type='Accumulation'/'Distribution' → 替换前缀类型（保留 Phase 字母）
        """
        if not phase or 'Phase' not in phase:
            return f"{new_type} Unknown"

        parts = phase.split()
        # 定位 'Phase' 关键词
        phase_idx = next((i for i, p in enumerate(parts) if p == 'Phase'), None)
        if phase_idx is None:
            return f"{new_type} Unknown"

        phase_type = parts[0]  # Accumulation / Distribution / Markup / Markdown / Trending
        phase_letter = parts[phase_idx + 1] if phase_idx + 1 < len(parts) else ''
        description = ' '.join(parts[phase_idx + 2:])  # 括号中的描述部分

        if new_type.startswith('Phase'):
            # 替换 Phase 字母：e.g. "Accumulation Phase A (desc)" → "Accumulation Phase C (desc)"
            result = f"{phase_type} {new_type}"
            if description:
                result += f" {description}"
            return result
        else:
            # 替换类型名：e.g. "Accumulation Phase A (desc)" → "Distribution Phase A (desc)"
            result = f"{new_type} Phase {phase_letter}"
            if description:
                result += f" {description}"
            return result

    def transition_phase_with_criteria(self, current_phase: str, events: 'EventsModel') -> Tuple[str, float]:
        """
        新增：使用量化标准进行Phase转换

        理论依据：孟洪涛《新威科夫操盘法》
        - Phase A→B：需要完整结构（SC/AR/ST）+ 20天震荡
        - Phase B→C：需要关键触发信号（Spring/Upthrust/SOS/SOW）
        - Phase C→D：需要确认信号（LPS/LPSY/JOC/FTI）
        - Phase D→E：需要3天确认

        Args:
            current_phase: 当前阶段
            events: 收集到的事件字典

        Returns:
            (新阶段, 置信度)
        """
        criteria = PhaseTransitionCriteria()
        phase_type = current_phase.split()[0] if 'Phase' in current_phase else current_phase

        # Phase A → B/C 转换
        if 'Phase A' in current_phase:
            return self._transition_from_phase_a(current_phase, events, criteria)

        # Phase B → C 转换
        elif 'Phase B' in current_phase:
            return self._transition_from_phase_b(current_phase, events, criteria)

        # Phase C → D 转换
        elif 'Phase C' in current_phase:
            return self._transition_from_phase_c(current_phase, events, criteria)

        # Phase D → E 转换
        elif 'Phase D' in current_phase:
            return self._transition_from_phase_d(current_phase, events, criteria)

        # 未知阶段，尝试识别
        else:
            return self._identify_initial_phase(events, criteria)

    def _transition_from_phase_a(self, current_phase: str, events: 'EventsModel', criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """从Phase A转换的逻辑"""
        # 检查是否有完整的Phase A结构
        has_complete_structure = self._has_complete_phase_a(events)
        if not has_complete_structure:
            return current_phase, 0.5

        # 计算震荡持续时间
        consolidation_days = self._calculate_consolidation_duration(events)
        if consolidation_days < criteria.A_TO_B_MIN_DAYS:
            return current_phase, 0.6

        # 检查Phase B→C的触发信号
        trigger = self._check_phase_triggers(events, criteria.B_TO_C_SIGNALS)
        if trigger:
            new_phase = self._replace_phase_type(current_phase, 'Phase C')
            return new_phase, 0.85

        # 没有触发信号，进入Phase B
        new_phase = self._replace_phase_type(current_phase, 'Phase B')
        return new_phase, 0.8

    def _transition_from_phase_b(self, current_phase: str, events: 'EventsModel', criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """从Phase B转换的逻辑"""
        # 检查Phase C触发信号
        trigger = self._check_phase_triggers(events, criteria.B_TO_C_SIGNALS)
        if trigger:
            new_phase = self._replace_phase_type(current_phase, 'Phase C')
            return new_phase, 0.85

        # 保持Phase B
        return current_phase, 0.7

    def _transition_from_phase_c(self, current_phase: str, events: 'EventsModel', criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """从Phase C转换的逻辑"""
        # 检查Phase D确认信号
        confirmations = self._check_phase_triggers(events, criteria.C_TO_D_SIGNALS)
        if confirmations:
            new_phase = self._replace_phase_type(current_phase, 'Phase D')
            return new_phase, 0.8

        # 保持Phase C
        return current_phase, 0.7

    def _transition_from_phase_d(self, current_phase: str, events: 'EventsModel', criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """从Phase D转换的逻辑"""
        # 检查是否有连续3天的确认
        if self._has_continuous_confirmation(criteria.D_TO_E_CONFIRMATION_DAYS):
            new_phase = self._replace_phase_type(current_phase, 'Phase E')
            return new_phase, 0.9

        # 保持Phase D
        return current_phase, 0.7

    def _identify_initial_phase(self, events: 'EventsModel', criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """识别初始阶段"""
        climax_res = events.climax
        spring_res = events.spring_upthrust

        # 检查Phase A
        if self._has_complete_phase_a(events):
            if climax_res and climax_res.type == 'selling_climax':
                return 'Accumulation Phase A', 0.7
            elif climax_res and climax_res.type == 'buying_climax':
                return 'Distribution Phase A', 0.7

        # 检查Spring/Upthrust直接进入Phase C
        if spring_res:
            if spring_res.type_ == 'spring':
                return 'Accumulation Phase C', 0.8
            elif spring_res.type_ == 'upthrust':
                return 'Distribution Phase C', 0.8

        return 'Unknown', 0.5


    def _has_complete_phase_a(self, events: 'EventsModel') -> bool:
        """检查是否有完整的Phase A结构（SC/AR + ST）"""
        has_climax = getattr(events.climax, 'detected', False) if events.climax else False
        has_ar = getattr(events.automatic_reaction, 'detected', False) if events.automatic_reaction else False
        has_st = getattr(events.secondary_test, 'detected', False) if events.secondary_test else False

        return has_climax and (has_ar or has_st)

    def _calculate_consolidation_duration(self, events: 'EventsModel') -> int:
        """计算震荡持续时间（从 ST 完成后开始计数）

        威科夫理论：震荡期应从 Phase A 结构完成后（SC/BC → AR → ST 序列结束）
        开始计算，而非包含 SC 之前的下跌段。这符合孟洪涛书中
        "Phase A 确认 → Phase B 震荡测试"的时序。
        """
        try:
            if hasattr(self.detector, 'data') and self.detector.data is not None:
                df = self.detector.data

                # 优先从 ST 日期开始计算
                st = getattr(events, 'secondary_test', None)
                st_date = getattr(st, 'date', None) if getattr(st, 'detected', False) else None
                if st_date is not None:
                    df_after_st = df[df.index >= pd.Timestamp(st_date)]
                    tr = self.detector.detect_trading_range()
                    if tr and 'low' in tr and 'high' in tr:
                        in_tr = df_after_st[
                            (df_after_st['Close'] >= tr['low']) &
                            (df_after_st['Close'] <= tr['high'])
                        ]
                        days = len(in_tr)
                        if days >= 5:
                            return days

                # 降级：从 AR 日期开始
                ar = getattr(events, 'automatic_reaction', None)
                ar_date = getattr(ar, 'date', None) if getattr(ar, 'detected', False) else None
                if ar_date is not None:
                    df_after_ar = df[df.index >= pd.Timestamp(ar_date)]
                    tr = self.detector.detect_trading_range()
                    if tr and 'low' in tr and 'high' in tr:
                        in_tr = df_after_ar[
                            (df_after_ar['Close'] >= tr['low']) &
                            (df_after_ar['Close'] <= tr['high'])
                        ]
                        days = len(in_tr)
                        if days >= 5:
                            return days

                # 兜底：全区间计数
                tr = self.detector.detect_trading_range()
                if tr and 'low' in tr and 'high' in tr:
                    in_tr = df[
                        (df['Close'] >= tr['low']) &
                        (df['Close'] <= tr['high'])
                    ]
                    return len(in_tr)
        except Exception as e:
            logger.debug(f"Failed to calculate consolidation duration: {e}")

        return 30

    def _check_phase_triggers(self, events: 'EventsModel', signals: List[Any]) -> bool:
        """检查是否触发了阶段转换信号"""
        for sig in signals:
            if isinstance(sig, str):
                event_name = sig
                expected_type = None
            elif isinstance(sig, dict):
                event_name = sig.get('event')
                expected_type = sig.get('type')
            else:
                continue

            if not event_name:
                continue

            event_obj = getattr(events, event_name, None)
            if not event_obj:
                continue

            # 处理 DualEventModel
            if isinstance(event_obj, DualEventModel):
                if expected_type:
                    if event_obj.type_ == expected_type and getattr(event_obj.data, 'detected', False):
                        return True
                else:
                    if getattr(event_obj.data, 'detected', False):
                        return True
                continue

            # 处理普通对象
            detected = getattr(event_obj, 'detected', False)
            if detected:
                if expected_type:
                    evt_type = getattr(event_obj, 'type', None)
                    if evt_type == expected_type:
                        return True
                else:
                    return True
        return False

    def _has_continuous_confirmation(self, days: int) -> bool:
        """检查是否有连续N天的同向确认"""
        try:
            if hasattr(self.detector, 'data') and self.detector.data is not None:
                df = self.detector.data.tail(days + 1)
                if len(df) < days + 1:
                    return False
                changes = df['Close'].pct_change().dropna()
                positive_ratio = (changes > 0).sum() / len(changes)
                negative_ratio = (changes < 0).sum() / len(changes)
                return positive_ratio >= 0.8 or negative_ratio >= 0.8
        except Exception as e:
            logger.debug(f"Confirmation check failed: {e}")
            pass

        return False

    def _arbitrate_events(self, raw_events: Dict) -> Optional['ArbitrationResult']:
        """
        对事件进行仲裁，解决信号冲突

        Args:
            raw_events: 原始事件字典

        Returns:
            仲裁结果，如果没有冲突则返回None
        """
        try:
            # 延迟初始化仲裁器
            if self.arbitrator is None and hasattr(self.detector, 'data'):
                from ..schemas import ArbitrationResult
                self.arbitrator = EventArbitrator(self.detector.data)

            if self.arbitrator is None:
                return None

            # 执行仲裁
            result = self.arbitrator.arbitrate(raw_events)

            # 如果有冲突，记录日志
            if result.has_conflict:
                logger.warning(
                    f"[事件仲裁] 检测到信号冲突:\n"
                    f"  冲突信号: {[s.signal_type for s in result.conflicting_signals]}\n"
                    f"  主导信号: {result.dominant_signal.signal_type if result.dominant_signal else '无'}\n"
                    f"  仲裁理由: {result.arbitration_reason}\n"
                    f"  建议阶段: {result.suggested_phase or '无'}"
                )

            return result

        except Exception as e:
            logger.error(f"[事件仲裁] 仲裁过程失败: {e}")
            return None

    def analyze_breakout_quality(self, trading_range: Dict) -> Optional[Dict]:
        """
        分析突破质量

        Args:
            trading_range: 交易区间信息

        Returns:
            突破分析结果，如果未突破则返回None
        """
        try:
            if not hasattr(self.detector, 'data'):
                return None

            # 延迟初始化突破分析器
            if self.breakout_analyzer is None:
                self.breakout_analyzer = BreakoutAnalyzer(self.detector.data)

            return self.breakout_analyzer.analyze_breakout(trading_range)

        except Exception as e:
            logger.error(f"[突破分析] 分析失败: {e}")
            return None

    def validate_phase_consistency(
        self,
        preliminary_phase: str,
        events: Dict,
        arbitration_result: Optional['ArbitrationResult'] = None,
        breakout_analysis: Optional[Dict] = None
    ) -> Tuple[str, List[str]]:
        """
        验证阶段一致性，执行证伪逻辑

        Args:
            preliminary_phase: 初步识别的阶段
            events: 收集到的事件字典
            arbitration_result: 事件仲裁结果（可选）

        Returns:
            (最终阶段, 修订日志列表)
        """
        revision_logs = []

        # 如果没有检测到关键事件，保持初步阶段
        if preliminary_phase == 'Unknown':
            return preliminary_phase, revision_logs

        # === 优先级0: TR突破反噬规则 ===
        breakout_analysis = events.breakout_analysis
        if breakout_analysis and getattr(breakout_analysis, 'is_breakout', False):
            override_phase, override_reason, conf_adjust = self._apply_breakout_override(
                preliminary_phase, events.trading_range, breakout_analysis
            )

            if override_reason:
                revision_logs.append(f"[突破反噬] {override_reason}")
                if conf_adjust < 1.0:
                    revision_logs.append(f"[置信度调整] 由于突破反噬，置信度×{conf_adjust:.2f}")
                return override_phase, revision_logs

        # === 优先级1: 事件仲裁结果 ===
        if arbitration_result and arbitration_result.has_conflict:
            suggested_phase = arbitration_result.suggested_phase
            if suggested_phase:
                revision_logs.append(
                    f"[事件仲裁] {arbitration_result.arbitration_reason}"
                )
                revision_logs.append(
                    f"[阶段调整] 基于仲裁结果，阶段从 {preliminary_phase} 调整为 {suggested_phase}"
                )
                return suggested_phase, revision_logs

        # === 优先级2: 检查是否有矛盾的证据 ===
        spring_upthrust = events.spring_upthrust
        sos_sow = events.sos_sow

        if spring_upthrust:
            # Bug 1 修复：DualEventModel 使用 .type_ 属性，不是 .get('_type')
            event_type = spring_upthrust.type_
            #  修复问题1：Phase A 与 Spring 时序矛盾
            # Wyckoff 理论：Spring 只能发生在 Phase C（吸筹区积累完成后的震仓测试）
            if 'Phase A' in preliminary_phase and 'Accumulation' in preliminary_phase and event_type == 'spring':
                new_phase = 'Accumulation Phase C'
                revision_logs.append(
                    f"[时序修正] Spring 只属于 Phase C。当前阶段 '{preliminary_phase}' 与 Spring 信号矛盾，"
                    f"强制升级为 '{new_phase}'。（Spring 是 Phase C 的震仓测试行为，"
                    f"发生在 SC→AR→ST 积累之后，而非 Phase A 初期）"
                )
                return new_phase, revision_logs
            # 派发阶段同理：Phase A 不应出现 Upthrust。根据威科夫强证据链，若是决断性的 UTAD 则应升级为 Phase C，若仅是普通上冲测试则修正为 Phase B。
            if 'Phase A' in preliminary_phase and 'Distribution' in preliminary_phase and event_type == 'upthrust':
                is_valid_c = False
                try:
                    ut_res = self.detector.detect_utad()
                    if ut_res.get('detected'):
                        is_valid_c = True
                except Exception:
                    pass
                
                # 检查最新 upthrust 的质量特征
                up_obj = getattr(events, 'upthrust', None)
                if up_obj and not is_valid_c:
                    latest_ut = getattr(up_obj, 'latest_upthrust', None)
                    if not latest_ut:
                        signals = getattr(up_obj, 'upthrusts', [])
                        latest_ut = signals[-1] if signals else None
                    if latest_ut:
                        is_valid = getattr(latest_ut, 'is_valid', True) or latest_ut.get('is_valid', True)
                        rejection_days = getattr(latest_ut, 'rejection_days', 99) or latest_ut.get('rejection_days', 99)
                        ft_quality = getattr(latest_ut, 'follow_through_quality', 0.0) or latest_ut.get('follow_through_quality', 0.0)
                        
                        if is_valid and rejection_days <= 3 and ft_quality >= 33.0:
                            is_valid_c = True
                
                if is_valid_c:
                    new_phase = 'Distribution Phase C'
                    revision_logs.append(
                        f"[时序修正] 检测到符合 Phase C 强证据链的决断性 Upthrust (UTAD)。当前阶段 '{preliminary_phase}' 与其冲突，"
                        f"强制升级为 '{new_phase}'。"
                    )
                    return new_phase, revision_logs
                else:
                    new_phase = 'Distribution Phase B'
                    revision_logs.append(
                        f"[时序修正] 检测到普通 Upthrust 阻力测试信号。当前阶段 '{preliminary_phase}' 转为修正为 '{new_phase}'（属于 Phase B 区间测试）。"
                    )
                    return new_phase, revision_logs
            # 如果初步判断是派发，但检测到 Spring
            if 'Distribution' in preliminary_phase and event_type == 'spring':
                revision_logs.append(f"检测到 Spring，从 {preliminary_phase} 修正为 Accumulation")
                return self._replace_phase_type(preliminary_phase, 'Accumulation'), revision_logs
            # 如果初步判断是吸筹，但检测到 Upthrust
            elif 'Accumulation' in preliminary_phase and event_type == 'upthrust':
                revision_logs.append(f"检测到 Upthrust，从 {preliminary_phase} 修正为 Distribution")
                return self._replace_phase_type(preliminary_phase, 'Distribution'), revision_logs

        # === 优先级3: 前序趋势否决权（熊市中继/再派发定性） ===
        if 'Accumulation' in preliminary_phase:
            prior_trend = self._detect_prior_trend()
            if prior_trend == 'markdown':
                has_confirmed_spring = False
                if events.spring and events.spring.detected:
                    signals = getattr(events.spring, 'signals', []) or []
                    for sig in signals:
                        if getattr(sig, 'st_confirmed', False):
                            has_confirmed_spring = True
                            break
                
                has_choch_up = False
                choch_dict = self.detector.detect_choch()
                if choch_dict.get('detected') and choch_dict.get('direction') == 'bullish':
                    has_choch_up = True
                
                if not has_confirmed_spring and not has_choch_up:
                    new_phase = self._replace_phase_type(preliminary_phase, 'Distribution (Re-distribution)')
                    revision_logs.append(
                        f"[前序趋势否决] 当前前序趋势为 markdown（下跌趋势），且缺乏已确认的 Spring 或 Choch Up 强确认，"
                        f"强制将初步吸筹阶段定性为熊市中继派发 '{new_phase}'。"
                    )
                    preliminary_phase = new_phase

        if sos_sow:
            # Bug 1 修复：DualEventModel 使用 .type_ 属性
            event_type = sos_sow.type_
            # SOS 确认吸筹
            if event_type == 'sos' and 'Accumulation' in preliminary_phase:
                revision_logs.append(f"SOS 确认吸筹阶段: {preliminary_phase}")
            # SOW 确认派发
            elif event_type == 'sow' and 'Distribution' in preliminary_phase:
                revision_logs.append(f"SOW 确认派发阶段: {preliminary_phase}")

        return preliminary_phase, revision_logs

    def _apply_breakout_override(
        self,
        current_phase: str,
        trading_range: 'TradingRangeModel',
        breakout_analysis: 'BreakoutAnalysisModel'
    ) -> Tuple[str, str, float]:
        """
        应用突破反噬规则

        优先级：TR突破 > 原有阶段判断

        Args:
            current_phase: 当前阶段
            trading_range: TradingRangeModel（Pydantic 模型）
            breakout_analysis: BreakoutAnalysisModel（Pydantic 模型）

        Returns:
            (新阶段, 覆盖理由, 置信度调整系数)
        """
        # Bug 2 修复：BreakoutAnalysisModel 用属性访问，不用 .get()
        if not breakout_analysis or not getattr(breakout_analysis, 'is_breakout', False):
            return current_phase, "", 1.0

        # TradingRangeModel 直接属性访问
        current_price = getattr(trading_range, 'current_price', 0) or 0
        tr_low = getattr(trading_range, 'low', 0) or 0
        tr_high = getattr(trading_range, 'high', 0) or 0

        direction = getattr(breakout_analysis, 'direction', None)

        # 规则1：向上突破 + 派发判断 → 强制否决
        if direction == 'up' and 'Distribution' in current_phase:
            quality = getattr(breakout_analysis, 'quality', 'unknown') or 'unknown'
            is_upthrust = getattr(breakout_analysis, 'is_upthrust', False)
            conclusion = getattr(breakout_analysis, 'conclusion', '') or ''

            if is_upthrust:
                return (
                    "Trending / Range Transition",
                    f"向上突破至{current_price:.2f}元疑似Upthrust（{conclusion}），"
                    f"可能重新测试原区间{tr_high:.2f}元",
                    0.5
                )
            else:
                return (
                    "Trending / Reaccumulation",
                    f"TR向上突破至{current_price:.2f}元（{quality}突破），"
                    f"否决了'派发'假设（原区间：{tr_low:.2f}-{tr_high:.2f}）。",
                    0.6
                )

        # 规则2：向下突破 + 吸筹判断 → 强制否决
        if direction == 'down' and 'Accumulation' in current_phase:
            quality = getattr(breakout_analysis, 'quality', 'unknown') or 'unknown'
            return (
                "Markdown / Trending Down",
                f"TR向下突破至{current_price:.2f}元（{quality}突破），"
                f"否决了'吸筹'假设（原区间：{tr_low:.2f}-{tr_high:.2f}）。",
                0.6
            )

        # 规则3：其他情况 → 降低置信度并标记需要重新评估
        return (
            current_phase,
            "",
            0.7  # 突破后降低置信度
        )

    def _build_lps_sequence(self, events) -> list:
        """
        构建 LPS 序列列表（最近30天内的所有LPS信号）
        """
        lps_list = []
        
        if isinstance(events, dict):
            lps_res = events.get('lps', {})
        else:
            lps_res = getattr(events, 'lps', None)

        if not lps_res:
            return lps_list

        is_detected = lps_res.get('detected') if isinstance(lps_res, dict) else getattr(lps_res, 'detected', False)
        if not is_detected:
            return lps_list

        if isinstance(lps_res, dict) and 'all_lps' in lps_res:
            for lps in lps_res['all_lps']:
                lps_list.append({
                    'date': lps.get('date'),
                    'price': lps.get('price'),
                    'volume': lps.get('volume'),
                    'detected': True
                })
        elif hasattr(lps_res, 'all_lps') and getattr(lps_res, 'all_lps'):
            for lps in getattr(lps_res, 'all_lps'):
                lps_list.append({
                    'date': getattr(lps, 'date', None),
                    'price': getattr(lps, 'price', None),
                    'volume': getattr(lps, 'volume', None),
                    'detected': True
                })
        else:
            lps_list.append({
                'date': lps_res.get('date') if isinstance(lps_res, dict) else getattr(lps_res, 'date', None),
                'price': lps_res.get('price') if isinstance(lps_res, dict) else getattr(lps_res, 'price', None),
                'volume': lps_res.get('volume') if isinstance(lps_res, dict) else getattr(lps_res, 'volume', None),
                'detected': True
            })

        return lps_list

    def _build_ut_sequence(self, events) -> list:
        """
        构建 UT 序列列表（最近30天内的所有UT信号）
        """
        ut_list = []
        
        if isinstance(events, dict):
            ut_res = events.get('upthrust', {})
        else:
            ut_res = getattr(events, 'upthrust', None)

        if not ut_res:
            return ut_list

        is_detected = ut_res.get('detected') if isinstance(ut_res, dict) else getattr(ut_res, 'detected', False)
        if not is_detected:
            return ut_list

        if isinstance(ut_res, dict) and 'upthrusts' in ut_res:
            for ut in ut_res['upthrusts']:
                ut_list.append({
                    'date': ut.get('date'),
                    'breakout_price': ut.get('breakout_price'),
                    'volume_ratio': ut.get('breakout_volume_ratio'),
                    'detected': True
                })
        elif hasattr(ut_res, 'upthrusts') and getattr(ut_res, 'upthrusts'):
            for ut in getattr(ut_res, 'upthrusts'):
                ut_list.append({
                    'date': getattr(ut, 'date', None),
                    'breakout_price': getattr(ut, 'breakout_price', None),
                    'volume_ratio': getattr(ut, 'breakout_volume_ratio', None),
                    'detected': True
                })
        else:
            ut_list.append({
                'date': ut_res.get('date') if isinstance(ut_res, dict) else getattr(ut_res, 'date', None),
                'breakout_price': (ut_res.get('breakout_price', ut_res.get('rejection_price')) 
                                   if isinstance(ut_res, dict) 
                                   else (getattr(ut_res, 'breakout_price', None) or getattr(ut_res, 'rejection_price', None))),
                'volume_ratio': (ut_res.get('breakout_volume_ratio', 1.0) 
                                 if isinstance(ut_res, dict) 
                                 else getattr(ut_res, 'breakout_volume_ratio', 1.0)),
                'detected': True
            })

        return ut_list


class PhaseTransitionCriteria:
    """
    Phase转换量化标准

    理论依据：孟洪涛《新威科夫操盘法》
    """

    # Phase A → B 转换标准
    A_TO_B_MIN_DAYS = 20          # 震荡持续≥20天
    A_TO_B_COMPLETE_STRUCTURE = True  # 必须有完整SC/AR/ST

    # Phase B → C 转换标准
    # 威科夫理论：B→C 的触发信号因方向而异
    # - 吸筹 B→C：Spring（震仓）或 SOS（强势突破） → Phase C/D
    # - 派发 B→C：Upthrust（诱多）或 SOW（弱势信号） → Phase C/D
    B_TO_C_SIGNALS = ['spring', 'upthrust', 'sos', 'sow']

    # Phase C → D 转换标准
    C_TO_D_SIGNALS = ['lps', 'lpsy', 'joc', 'fti']

    # Phase D → E 转换标准
    D_TO_E_CONFIRMATION_DAYS = 3

    # 各阶段的最小持续时间（天）
    MIN_PHASE_A_DURATION = 10
    MIN_PHASE_B_DURATION = 15
    MIN_PHASE_C_DURATION = 10
    MIN_PHASE_D_DURATION = 7