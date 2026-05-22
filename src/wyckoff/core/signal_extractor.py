"""
信号提取工具类
用于从事件检测结果中提取和验证信号
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import numpy as np
from ..config.settings import WyckoffThresholds
from .enums import WyckoffPhase
from .utils import PhaseAdapter


class SignalExtractor:
    """从威科夫事件检测结果中提取信号的工具类"""

    @staticmethod
    def extract_signals(phase_result: Dict[str, Any]) -> Dict[str, bool]:
        """
        从阶段识别结果中提取所有信号状态

        Args:
            phase_result: identify_phase() 或 identify_phase_with_rs() 的返回结果

        Returns:
            包含各信号检测状态的字典
        """
        events = phase_result.get('events_detected') if isinstance(phase_result, dict) else getattr(phase_result, 'events_detected', None)
        if not events:
            events = phase_result

        # 如果 events 是 dict
        if isinstance(events, dict):
            spring_upthrust = events.get('spring_upthrust') or {}
            sos_sow = events.get('sos_sow') or {}
            lps_lpsy = events.get('lps_lpsy') or {}
            lps_data = lps_lpsy.get('lps', {}) if isinstance(lps_lpsy, dict) else {}
            lpsy_data = lps_lpsy.get('lpsy', {}) if isinstance(lps_lpsy, dict) else {}

            has_spring = spring_upthrust.get('_type') == 'spring'
            has_upthrust = spring_upthrust.get('_type') == 'upthrust'
            has_sos = sos_sow.get('_type') == 'sos'
            has_sow = sos_sow.get('_type') == 'sow'
            has_lps = getattr(lps_data, 'detected', False) if hasattr(lps_data, 'detected') else lps_data.get('detected', False)
            has_lpsy = getattr(lpsy_data, 'detected', False) if hasattr(lpsy_data, 'detected') else lpsy_data.get('detected', False)
        else:
            # 强类型 Pydantic Model (EventsModel)
            spring_upthrust = getattr(events, 'spring_upthrust', None)
            sos_sow = getattr(events, 'sos_sow', None)
            lps_data = getattr(events, 'lps', None)
            lpsy_data = getattr(events, 'lpsy', None)

            has_spring = spring_upthrust.type_ == 'spring' if spring_upthrust else False
            has_upthrust = spring_upthrust.type_ == 'upthrust' if spring_upthrust else False
            has_sos = sos_sow.type_ == 'sos' if sos_sow else False
            has_sow = sos_sow.type_ == 'sow' if sos_sow else False
            has_lps = getattr(lps_data, 'detected', False) if lps_data else False
            has_lpsy = getattr(lpsy_data, 'detected', False) if lpsy_data else False

        return {
            'has_spring': has_spring,
            'has_upthrust': has_upthrust,
            'has_sos': has_sos,
            'has_sow': has_sow,
            'has_lps': has_lps,
            'has_lpsy': has_lpsy,
        }

    @staticmethod
    def extract_accumulation_signals(phase_result: Dict[str, Any]) -> Dict[str, bool]:
        """
        提取积累期相关信号（Spring, SOS, LPS）

        Args:
            phase_result: 阶段识别结果

        Returns:
            包含积累期信号的字典
        """
        signals = SignalExtractor.extract_signals(phase_result)
        return {
            'has_spring': signals['has_spring'],
            'has_sos': signals['has_sos'],
            'has_lps': signals['has_lps'],
        }

    @staticmethod
    def extract_distribution_signals(phase_result: Dict[str, Any]) -> Dict[str, bool]:
        """
        提取派发期相关信号（Upthrust, SOW, LPSY）

        Args:
            phase_result: 阶段识别结果

        Returns:
            包含派发期信号的字典
        """
        signals = SignalExtractor.extract_signals(phase_result)
        return {
            'has_upthrust': signals['has_upthrust'],
            'has_sow': signals['has_sow'],
            'has_lpsy': signals['has_lpsy'],
        }

    @staticmethod
    def calculate_weighted_score(phase_result: Dict[str, Any], thresholds: WyckoffThresholds = None) -> float:
        """
        计算加权信号强度得分 (0-100)
        包含：信号质量分、时间衰减、多空冲突惩罚
        """
        if thresholds is None:
            thresholds = WyckoffThresholds()

        events = phase_result.get('events_detected') if isinstance(phase_result, dict) else getattr(phase_result, 'events_detected', None)
        if not events:
            events = phase_result

        if not events:
            return 0.0

        base_score = 0.0
        latest_date = None

        # 1. 计算信号质量分
        weights = thresholds.QUALITY_WEIGHTS

        # 处理主要信号
        important_signals = [
            ('spring_upthrust', 40),
            ('sos_sow', 35),
            ('lps_lpsy', 25)
        ]

        bullish_count = 0
        bearish_count = 0

        for key, max_weight in important_signals:
            if isinstance(events, dict):
                info = events.get(key)
            else:
                info = getattr(events, key, None)

            if not info:
                # 兼容：如果 key 是 lps_lpsy 且 events 是 EventsModel
                if key == 'lps_lpsy' and not isinstance(events, dict):
                    lps = getattr(events, 'lps', None)
                    lpsy = getattr(events, 'lpsy', None)
                    is_lps_detected = getattr(lps, 'detected', False) if lps else False
                    is_lpsy_detected = getattr(lpsy, 'detected', False) if lpsy else False
                    if is_lps_detected:
                        info = lps
                    elif is_lpsy_detected:
                        info = lpsy
                if not info:
                    continue

            # 统一提取具体的事件实体和类型
            if isinstance(info, dict):
                data = info.get('data') or info
                sig_type = info.get('_type') or info.get('type', '')
            else:
                # 强类型，可能是 DualEventModel 或具体的 LpsModel/LpsyModel
                if hasattr(info, 'type_'):
                    sig_type = info.type_
                    data = info.data
                else:
                    sig_type = key
                    data = info

            if not data or not getattr(data, 'detected', False):
                continue

            # 判断方向供冲突检测
            if sig_type in ['spring', 'sos', 'lps']:
                bullish_count += 1
            elif sig_type in ['upthrust', 'sow', 'lpsy']:
                bearish_count += 1

            # 计算该信号的质量因子 (0.5 - 1.2)
            quality_factor = 0.8 # 默认基础分

            # 考虑成交量比 (Volume Ratio)
            vol_ratio = getattr(data, 'volume_ratio', 1.0)
            if vol_ratio > 2.0:
                quality_factor += weights['volume_ratio']
            elif vol_ratio > 1.5:
                quality_factor += weights['volume_ratio'] * 0.5

            # 考虑置信度 (Confidence)
            conf = getattr(data, 'confidence', 0.5)
            quality_factor += (conf - 0.5) * weights['confidence']

            # 考虑日期 (时间衰减)
            sig_date = getattr(data, 'date', None)
            if sig_date:
                if isinstance(sig_date, str):
                    try:
                        sig_date = datetime.strptime(sig_date, '%Y-%m-%d')
                    except Exception:
                        pass

                if isinstance(sig_date, datetime):
                    if latest_date is None or sig_date > latest_date:
                        latest_date = sig_date

                    # 时间衰减因子
                    days_ago = (datetime.now() - sig_date).days
                    decay = np.exp(-0.693 * max(0, days_ago) / thresholds.TIME_DECAY_HALF_LIFE)
                    quality_factor *= decay

            base_score += max_weight * min(quality_factor, 1.5)

        # 2. 冲突惩罚
        if bullish_count > 0 and bearish_count > 0:
            base_score -= thresholds.CONFLICT_PENALTY

        # 3. 基础置信度加成
        phase_conf = phase_result.get('confidence') if isinstance(phase_result, dict) else getattr(phase_result, 'confidence', 0.0)
        phase_conf = phase_conf or 0.0
        base_score += phase_conf * 10

        return round(max(0.0, min(base_score, 100.0)), 2)

    @staticmethod
    def calculate_signal_strength(signals: Dict[str, bool]) -> int:
        """保持兼容性的旧方法"""
        return sum(1 for v in signals.values() if v)

    @staticmethod
    def get_phase_string(phase_result: Dict[str, Any]) -> str:
        """
        从阶段识别结果中获取阶段字符串

        Args:
            phase_result: 阶段识别结果

        Returns:
            阶段字符串
        """
        return phase_result.get('phase', 'Unknown') if isinstance(phase_result, dict) else str(phase_result)

    @staticmethod
    def is_accumulation_phase(phase_str: str) -> bool:
        """判断是否为积累期"""
        return PhaseAdapter.is_accumulation(phase_str)

    @staticmethod
    def is_distribution_phase(phase_str: str) -> bool:
        """判断是否为派发期"""
        return PhaseAdapter.is_distribution(phase_str)

    @staticmethod
    def is_markup_phase(phase_str: str) -> bool:
        """判断是否为上涨期"""
        return PhaseAdapter.is_markup(phase_str)

    @staticmethod
    def is_markdown_phase(phase_str: str) -> bool:
        """判断是否为下跌期"""
        return PhaseAdapter.is_markdown(phase_str)

    @staticmethod
    def is_late_stage(phase_enum: WyckoffPhase) -> bool:
        """判断是否为后期阶段 (C/D)"""
        return PhaseAdapter.is_late_stage(phase_enum)
