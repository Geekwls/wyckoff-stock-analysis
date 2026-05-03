"""
信号提取工具类
用于从事件检测结果中提取和验证信号
"""
from typing import Dict, Any, Optional


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
    def calculate_signal_strength(signals: Dict[str, bool]) -> int:
        """
        计算信号强度得分

        Args:
            signals: 信号字典

        Returns:
            信号强度得分（0-6）
        """
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
        """
        判断是否为积累期

        Args:
            phase_str: 阶段字符串

        Returns:
            是否为积累期
        """
        return 'Accumulation' in phase_str

    @staticmethod
    def is_distribution_phase(phase_str: str) -> bool:
        """
        判断是否为派发期

        Args:
            phase_str: 阶段字符串

        Returns:
            是否为派发期
        """
        return 'Distribution' in phase_str

    @staticmethod
    def is_markup_phase(phase_str: str) -> bool:
        """
        判断是否为上涨期

        Args:
            phase_str: 阶段字符串

        Returns:
            是否为上涨期
        """
        return 'Markup' in phase_str

    @staticmethod
    def is_markdown_phase(phase_str: str) -> bool:
        """
        判断是否为下跌期

        Args:
            phase_str: 阶段字符串

        Returns:
            是否为下跌期
        """
        return 'Markdown' in phase_str
