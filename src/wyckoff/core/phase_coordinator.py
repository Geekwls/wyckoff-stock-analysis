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
    JocModel, FtiModel
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
        # 🔧 P0-2修复步骤1：在每次分析开始时重置屏蔽状态，避免污染
        if hasattr(self.detector, 'sw_detector'):
            self.detector.sw_detector.reset_blocked_signals()

        # 1. 收集基础价格形态（不依赖全局阶段）
        # 🔧 P3修复：弃用旧的基于固定百分比的 detect_climax，全面拥抱动态 ATR 的 SC/BC
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

        spring_res = self.detector.detect_spring()
        upthrust_res = self.detector.detect_upthrust()

        boring_zone_res = self.detector.detect_boring_zone()

        # P1 修复：存储完整Phase A事件(PS→SC/BC→AR→ST)到detector
        phase_a_events = {
            'ps': ps_res,
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
            climax_res, ar_res, st_res, spring_res, upthrust_res, ps_res
        )

        # 🔧 P0-2修复步骤2：初步阶段识别后立即屏蔽矛盾信号（从源头杜绝信号污染）
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
        self._update_trading_range_from_events(climax_res, ar_res, preliminary_phase)

        # 统一更新子检测器的分析上下文
        self.detector._update_all_detectors_context(preliminary_phase)

        # 4. 收集趋势/强度信号（此时 TR 已使用已知边界）
        sos_res = self.detector.detect_sos()
        sow_res = self.detector.detect_sow()

        tr_res = self.detector.detect_trading_range()
        lps_res = self.detector.detect_lps(sos_res, spring_res)
        lpsy_res = self.detector.detect_lpsy(trading_range=tr_res)
        joc_res = self.detector.detect_joc()
        fti_res = self.detector.detect_fti()

        # 5. 运行事件序列验证（在原始dict上，模型封装前）
        raw_events = {
            "preliminary_support": ps_res,
            "climax": climax_res,
            "automatic_reaction": ar_res,
            "secondary_test": st_res,
            "spring": spring_res,
            "upthrust": upthrust_res,
            "sos": sos_res,
            "sow": sow_res,
            "lps": lps_res,
            "lpsy": lpsy_res,
            "joc": joc_res,
            "fti": fti_res,
        }
        sequence_validation = SequenceValidator(raw_events, self.detector.data).validate_all()

        # 5.5. 运行事件仲裁（解决信号冲突）
        arbitration_result = self._arbitrate_events(raw_events)

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
        }
        # 5.6. 分析突破质量（在tr_res和trading_range创建后调用）
        trading_range_model = _safe_model(TradingRangeModel, tr_res)
        breakout_analysis = self.analyze_breakout_quality(tr_res)

        events = {
            'trading_range': trading_range_model,
            '_raw_events': raw_events_map,
            'climax': _safe_model(ClimaxModel, climax_res),
            'automatic_reaction': _safe_model(WyckoffEventModel, ar_res) if ar_res.get('detected') else WyckoffEventModel(detected=False),
            'secondary_test': _safe_model(WyckoffEventModel, st_res) if st_res.get('detected') else WyckoffEventModel(detected=False),
            'spring_upthrust': None,
            'sos_sow': None,
            'lps_lpsy': {
                'lps': _safe_model(LpsModel, lps_res),
                'lpsy': _safe_model(LpsyModel, lpsy_res)
            },
            'joc': _safe_model(JocModel, joc_res) if joc_res.get('detected') else None,
            'fti': _safe_model(FtiModel, fti_res) if fti_res.get('detected') else None,
            'boring_zone': boring_zone_res,
            'phase_revision_log': [],
            'sequence_validation': sequence_validation,
            'arbitration_result': arbitration_result,
            'breakout_analysis': breakout_analysis,
        }

        if spring_res.get('detected'):
            events['spring_upthrust'] = {'_type': 'spring', 'data': SpringModel(**spring_res)}
        elif upthrust_res.get('detected'):
            events['spring_upthrust'] = {'_type': 'upthrust', 'data': UpthrustModel(**upthrust_res)}

        if sos_res.get('detected'):
            events['sos_sow'] = {'_type': 'sos', 'data': SosModel(**sos_res)}
        elif sow_res.get('detected'):
            events['sos_sow'] = {'_type': 'sow', 'data': SowModel(**sow_res)}

        # 7. 执行证伪验证（考虑仲裁结果和突破分析）
        final_phase, revision_logs = self.validate_phase_consistency(
            preliminary_phase, events, arbitration_result, breakout_analysis
        )
        events['phase_revision_log'] = revision_logs

        # 统一更新子检测器的最终分析上下文
        self.detector._update_all_detectors_context(final_phase)

        return events

    def _update_trading_range_from_events(self, climax_res: Dict, ar_res: Dict, phase: str):
        """
        从威科夫事件更新交易区间边界
        
        派发期：TR上沿 = BC高点, TR下沿 = AR低点
        积累期：TR上沿 = AR高点, TR下沿 = SC低点
        """
        tr_detector = self.detector.range_detector
        
        if 'Distribution' in phase:
            bc_high = climax_res.get('price') if climax_res.get('type') == 'buying_climax' else None
            ar_low = ar_res.get('price') if ar_res.get('detected') else None
            if bc_high and ar_low and bc_high > ar_low:
                tr_detector.update_from_phase_events(bc_high, ar_low, "BC-AR")
                return
        elif 'Accumulation' in phase:
            sc_low = climax_res.get('price') if climax_res.get('type') == 'selling_climax' else None
            ar_high = ar_res.get('price') if ar_res.get('detected') else None
            if sc_low and ar_high and ar_high > sc_low:
                tr_detector.update_from_phase_events(ar_high, sc_low, "SC-AR")

    def _preliminary_phase_identification(
        self,
        climax_res: Dict,
        ar_res: Dict,
        st_res: Dict,
        spring_res: Dict,
        upthrust_res: Dict,
        ps_res: Optional[Dict] = None,
    ) -> str:
        """
        初步阶段识别：基于已收集的事件进行初步判断

        优化：增加 PS/SC 确认链条和 AR/ST 协同校验。
        Phase A 完整链条: PS → SC/BC → AR → ST
        """
        is_ps = ps_res.get('detected') if ps_res else False
        is_sc = climax_res.get('detected') and climax_res.get('type') == 'selling_climax'
        is_bc = climax_res.get('detected') and climax_res.get('type') == 'buying_climax'
        is_ar = ar_res.get('detected')
        is_st = st_res.get('detected')

        # 派发初步迹象：BC + AR/ST
        if is_bc and (is_ar or is_st):
            return 'Distribution Phase A'

        # 吸筹初步迹象：SC + AR/ST
        if is_sc and (is_ar or is_st):
            return 'Accumulation Phase A'

        # PS (初次支撑) 确认吸筹结构启动
        if is_ps and is_sc:
            return 'Accumulation Phase A'

        # 强信号覆盖
        if spring_res.get('detected'):
            return 'Accumulation Phase C'
        if upthrust_res.get('detected'):
            return 'Distribution Phase C'

        # 默认未知
        return 'Unknown'


    def _replace_phase_type(self, phase: Optional[str], new_type: str) -> str:
        """替换阶段类型（保持 Phase X 部分）"""
        if not phase or 'Phase' not in phase:
            return f"{new_type} Unknown"
        parts = phase.split()
        phase_letter = parts[-1]
        return f"{new_type} Phase {phase_letter}"

    def transition_phase_with_criteria(self, current_phase: str, events: Dict) -> Tuple[str, float]:
        """
        🔧 v1.1新增：使用量化标准进行Phase转换

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

    def _transition_from_phase_a(self, current_phase: str, events: Dict, criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
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

    def _transition_from_phase_b(self, current_phase: str, events: Dict, criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """从Phase B转换的逻辑"""
        # 检查Phase C触发信号
        trigger = self._check_phase_triggers(events, criteria.B_TO_C_SIGNALS)
        if trigger:
            new_phase = self._replace_phase_type(current_phase, 'Phase C')
            return new_phase, 0.85

        # 保持Phase B
        return current_phase, 0.7

    def _transition_from_phase_c(self, current_phase: str, events: Dict, criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """从Phase C转换的逻辑"""
        # 检查Phase D确认信号
        confirmations = self._check_phase_triggers(events, criteria.C_TO_D_SIGNALS)
        if confirmations:
            new_phase = self._replace_phase_type(current_phase, 'Phase D')
            return new_phase, 0.8

        # 保持Phase C
        return current_phase, 0.7

    def _transition_from_phase_d(self, current_phase: str, events: Dict, criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """从Phase D转换的逻辑"""
        # 检查是否有连续3天的确认
        if self._has_continuous_confirmation(criteria.D_TO_E_CONFIRMATION_DAYS):
            new_phase = self._replace_phase_type(current_phase, 'Phase E')
            return new_phase, 0.9

        # 保持Phase D
        return current_phase, 0.7

    def _identify_initial_phase(self, events: Dict, criteria: 'PhaseTransitionCriteria') -> Tuple[str, float]:
        """识别初始阶段"""
        climax_res = events.get('climax', {})
        ar_res = events.get('automatic_reaction', {})
        st_res = events.get('secondary_test', {})

        # 检查Phase A
        if self._has_complete_phase_a(events):
            if climax_res.get('type') == 'selling_climax':
                return 'Accumulation Phase A', 0.7
            elif climax_res.get('type') == 'buying_climax':
                return 'Distribution Phase A', 0.7

        # 检查Spring/Upthrust直接进入Phase C
        spring_res = events.get('spring_upthrust', {})
        if spring_res.get('detected'):
            if spring_res.get('_type') == 'spring':
                return 'Accumulation Phase C', 0.8
            elif spring_res.get('_type') == 'upthrust':
                return 'Distribution Phase C', 0.8

        return 'Unknown', 0.5

    def _has_complete_phase_a(self, events: Dict) -> bool:
        """检查是否有完整的Phase A结构（SC/AR + ST）"""
        climax_res = events.get('climax', {})
        ar_res = events.get('automatic_reaction', {})
        st_res = events.get('secondary_test', {})

        has_climax = climax_res.get('detected', False)
        has_ar = ar_res.get('detected', False)
        has_st = st_res.get('detected', False)

        return has_climax and (has_ar or has_st)

    def _calculate_consolidation_duration(self, events: Dict) -> int:
        """计算震荡持续时间"""
        # 尝试从数据中计算实际震荡时间
        try:
            if hasattr(self.detector, 'data') and self.detector.data is not None:
                df = self.detector.data
                # 简单计算：在TR内的天数
                tr = self.detector.detect_trading_range()
                if tr and 'low' in tr and 'high' in tr:
                    in_tr = df[
                        (df['Close'] >= tr['low']) &
                        (df['Close'] <= tr['high'])
                    ]
                    return len(in_tr)
        except Exception as e:
            logger.debug(f"Failed to calculate consolidation duration: {e}")
            pass

        # 备用估算
        return 30

    def _check_phase_triggers(self, events: Dict, trigger_types: List[str]) -> bool:
        """检查Phase转换触发信号"""
        for trigger_type in trigger_types:
            if trigger_type == 'spring':
                event = events.get('spring_upthrust', {})
                if event.get('detected') and event.get('_type') == 'spring':
                    return True
            elif trigger_type == 'upthrust':
                event = events.get('spring_upthrust', {})
                if event.get('detected') and event.get('_type') == 'upthrust':
                    return True
            elif trigger_type == 'sos':
                event = events.get('sos_sow', {})
                if event.get('detected') and event.get('_type') == 'sos':
                    return True
            elif trigger_type == 'sow':
                event = events.get('sos_sow', {})
                if event.get('detected') and event.get('_type') == 'sow':
                    return True
            elif trigger_type == 'lps':
                event = events.get('lps_lpsy', {})
                lps = event.get('lps', {})
                if lps.get('detected'):
                    return True
            elif trigger_type == 'lpsy':
                event = events.get('lps_lpsy', {})
                lpsy = event.get('lpsy', {})
                if lpsy.get('detected'):
                    return True
            elif trigger_type == 'joc':
                # 需要单独检查JOC
                try:
                    joc_result = self.detector.detect_joc()
                    if joc_result.get('detected'):
                        return True
                except Exception as e:
                    logger.debug(f"JOC trigger check failed: {e}")
                    pass
            elif trigger_type == 'fti':
                # 需要单独检查FTI
                try:
                    fti_result = self.detector.detect_fti()
                    if fti_result.get('detected'):
                        return True
                except Exception as e:
                    logger.debug(f"FTI trigger check failed: {e}")
                    pass

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
        breakout_analysis = events.get('breakout_analysis')
        if breakout_analysis and breakout_analysis.get('is_breakout'):
            override_phase, override_reason, conf_adjust = self._apply_breakout_override(
                preliminary_phase, events.get('trading_range', {}), breakout_analysis
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
        spring_upthrust = events.get('spring_upthrust')
        sos_sow = events.get('sos_sow')

        if spring_upthrust:
            event_type = spring_upthrust.get('_type')
            # 如果初步判断是派发，但检测到 Spring
            if 'Distribution' in preliminary_phase and event_type == 'spring':
                revision_logs.append(f"检测到 Spring，从 {preliminary_phase} 修正为 Accumulation")
                return self._replace_phase_type(preliminary_phase, 'Accumulation'), revision_logs
            # 如果初步判断是吸筹，但检测到 Upthrust
            elif 'Accumulation' in preliminary_phase and event_type == 'upthrust':
                revision_logs.append(f"检测到 Upthrust，从 {preliminary_phase} 修正为 Distribution")
                return self._replace_phase_type(preliminary_phase, 'Distribution'), revision_logs

        if sos_sow:
            event_type = sos_sow.get('_type')
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
        trading_range,
        breakout_analysis: Dict
    ) -> Tuple[str, str, float]:
        """
        应用突破反噬规则

        优先级：TR突破 > 原有阶段判断

        Args:
            current_phase: 当前阶段
            trading_range: 交易区间（可能是dict或Pydantic模型）
            breakout_analysis: 突破分析结果

        Returns:
            (新阶段, 覆盖理由, 置信度调整系数)
        """
        if not breakout_analysis or not breakout_analysis.get('is_breakout'):
            return current_phase, "", 1.0

        # 兼容dict和Pydantic模型
        if hasattr(trading_range, 'dict'):
            # Pydantic v1
            tr_dict = trading_range.dict()
        elif hasattr(trading_range, 'model_dump'):
            # Pydantic v2
            tr_dict = trading_range.model_dump()
        elif isinstance(trading_range, dict):
            tr_dict = trading_range
        else:
            tr_dict = {}

        direction = breakout_analysis.get('direction')
        current_price = tr_dict.get('current_price', 0)
        tr_low = tr_dict.get('low', 0)
        tr_high = tr_dict.get('high', 0)

        # 规则1：向上突破 + 派发判断 → 强制否决
        if direction == 'up' and 'Distribution' in current_phase:
            # 检查突破质量
            quality = breakout_analysis.get('quality', 'unknown')
            is_upthrust = breakout_analysis.get('is_upthrust', False)

            if is_upthrust:
                # Upthrust（假突破）- 仍然可能回到区间
                return (
                    "Trending / Range Transition",
                    f"向上突破至{current_price:.2f}元疑似Upthrust（{breakout_analysis.get('conclusion', '')}），"
                    f"可能重新测试原区间{tr_high:.2f}元",
                    0.5
                )
            else:
                # 真实突破 - 否决派发
                return (
                    "Trending / Reaccumulation",
                    f"TR向上突破至{current_price:.2f}元（{quality}突破），"
                    f"否决了'派发'假设（原区间：{tr_low:.2f}-{tr_high:.2f}）。",
                    0.6
                )

        # 规则2：向下突破 + 吸筹判断 → 强制否决
        if direction == 'down' and 'Accumulation' in current_phase:
            quality = breakout_analysis.get('quality', 'unknown')
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


class PhaseTransitionCriteria:
    """
    Phase转换量化标准

    理论依据：孟洪涛《新威科夫操盘法》
    """

    # Phase A → B 转换标准
    A_TO_B_MIN_DAYS = 20          # 震荡持续≥20天
    A_TO_B_COMPLETE_STRUCTURE = True  # 必须有完整SC/AR/ST

    # Phase B → C 转换标准
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