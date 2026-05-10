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
        events = phase_result.get('events_detected', {})
        spring_upthrust = events.get('spring_upthrust') or {}
        sos_sow = events.get('sos_sow') or {}
        lps_lpsy = events.get('lps_lpsy') or {}

        return {
            'has_spring': spring_upthrust.get('detected', False) and spring_upthrust.get('_type') == 'spring',
            'has_upthrust': spring_upthrust.get('detected', False) and spring_upthrust.get('_type') == 'upthrust',
            'has_sos': sos_sow.get('detected', False) and sos_sow.get('_type') == 'sos',
            'has_sow': sos_sow.get('detected', False) and sos_sow.get('_type') == 'sow',
            'has_lps': lps_lpsy.get('detected', False) and lps_lpsy.get('_type') == 'lps',
            'has_lpsy': lps_lpsy.get('detected', False) and lps_lpsy.get('_type') == 'lpsy',
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
            
        events = phase_result.get('events_detected', {})
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
            info = events.get(key)
            if not info: continue
            
            data = info.get('data') if isinstance(info, dict) else info
            if not data or not getattr(data, 'detected', False): continue
            
            # 判断方向供冲突检测
            sig_type = info.get('_type') if isinstance(info, dict) else getattr(data, 'type', '')
            if sig_type in ['spring', 'sos', 'lps']: bullish_count += 1
            elif sig_type in ['upthrust', 'sow', 'lpsy']: bearish_count += 1
            
            # 计算该信号的质量因子 (0.5 - 1.2)
            quality_factor = 0.8 # 默认基础分
            
            # 考虑成交量比 (Volume Ratio)
            vol_ratio = getattr(data, 'volume_ratio', 1.0)
            if vol_ratio > 2.0: quality_factor += weights['volume_ratio']
            elif vol_ratio > 1.5: quality_factor += weights['volume_ratio'] * 0.5
            
            # 考虑置信度 (Confidence)
            conf = getattr(data, 'confidence', 0.5)
            quality_factor += (conf - 0.5) * weights['confidence']
            
            # 考虑日期 (时间衰减)
            sig_date = getattr(data, 'date', None)
            if sig_date:
                if isinstance(sig_date, str):
                    try: sig_date = datetime.strptime(sig_date, '%Y-%m-%d')
                    except Exception:
                        # 转换失败保持原样，后面会有类型检查
                        pass
                
                if isinstance(sig_date, datetime):
                    if latest_date is None or sig_date > latest_date:
                        latest_date = sig_date
                    
                    # 时间衰减因子: exp(-ln(2) * t / half_life)
                    days_ago = (datetime.now() - sig_date).days
                    decay = np.exp(-0.693 * max(0, days_ago) / thresholds.TIME_DECAY_HALF_LIFE)
                    quality_factor *= decay
            
            base_score += max_weight * min(quality_factor, 1.5)
            
        # 2. 冲突惩罚
        if bullish_count > 0 and bearish_count > 0:
            base_score -= thresholds.CONFLICT_PENALTY
            
        # 3. 基础置信度加成
        phase_conf = phase_result.get('confidence') or 0.0
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

    @staticmethod
    def get_execution_score(current_price: float, support: float, resistance: float, direction: str) -> float:
        """
        计算可执行性得分 (风盈比与距离)
        """
        if direction == "做多":
            if current_price <= support or current_price >= resistance: return 10.0
            dist_to_support = (current_price - support) / current_price
            
            # 越接近支撑位得分越高，理想距离在 1-5%
            if dist_to_support < 0.05:
                return round(100.0 * (1.0 - dist_to_support/0.05), 2)
            return 20.0
        else:
            if current_price >= resistance or current_price <= support: return 10.0
            dist_to_res = (resistance - current_price) / current_price
            if dist_to_res < 0.05:
                return round(100.0 * (1.0 - dist_to_res/0.05), 2)
            return 20.0
