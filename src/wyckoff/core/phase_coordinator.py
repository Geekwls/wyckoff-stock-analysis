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
import logging

logger = logging.getLogger(__name__)


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
        # 1. 收集基础价格形态（不依赖全局阶段）
        climax_res = self.detector.detect_climax()
        ar_res = self.detector.detect_automatic_reaction(climax_res)
        st_res = self.detector.detect_secondary_test(climax_res, ar_res)

        spring_res = self.detector.detect_spring()
        upthrust_res = self.detector.detect_upthrust()

        boring_zone_res = self.detector.detect_boring_zone()

        # 2. 初步阶段识别
        preliminary_phase = self._preliminary_phase_identification(
            climax_res, ar_res, st_res, spring_res, upthrust_res
        )

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

        # 6. 统一使用强类型模型封装
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
            'fti': FtiModel(**fti_res) if fti_res.get('detected') else None,
            'boring_zone': boring_zone_res,
            'phase_revision_log': [],
            'sequence_validation': sequence_validation,
        }

        if spring_res.get('detected'):
            events['spring_upthrust'] = {'_type': 'spring', 'data': SpringModel(**spring_res)}
        elif upthrust_res.get('detected'):
            events['spring_upthrust'] = {'_type': 'upthrust', 'data': UpthrustModel(**upthrust_res)}

        if sos_res.get('detected'):
            events['sos_sow'] = {'_type': 'sos', 'data': SosModel(**sos_res)}
        elif sow_res.get('detected'):
            events['sos_sow'] = {'_type': 'sow', 'data': SowModel(**sow_res)}

        # 7. 执行证伪验证
        final_phase, revision_logs = self.validate_phase_consistency(preliminary_phase, events)
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
        upthrust_res: Dict
    ) -> str:
        """
        初步阶段识别：基于已收集的事件进行初步判断

        优化：增加对 AR 和 ST 的协同校验，避免仅凭 BC/SC 就定性。
        """
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

        # 强信号覆盖
        if spring_res.get('detected'):
            return 'Accumulation Phase C'
        if upthrust_res.get('detected'):
            return 'Distribution Phase C'

        # 默认未知
        return 'Unknown'

    def validate_phase_consistency(
        self,
        preliminary_phase: str,
        events: Dict
    ) -> Tuple[str, List[str]]:
        """
        验证阶段一致性，执行证伪逻辑

        Args:
            preliminary_phase: 初步识别的阶段
            events: 收集到的事件字典

        Returns:
            (最终阶段, 修订日志列表)
        """
        revision_logs = []

        # 如果没有检测到关键事件，保持初步阶段
        if preliminary_phase == 'Unknown':
            return preliminary_phase, revision_logs

        # 检查是否有矛盾的证据
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

    def _replace_phase_type(self, phase: str, new_type: str) -> str:
        """替换阶段类型（保持 Phase X 部分）"""
        if 'Phase' in phase:
            parts = phase.split()
            phase_letter = parts[-1]
            return f"{new_type} Phase {phase_letter}"
        return f"{new_type} Unknown"
