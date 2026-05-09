from abc import ABC

class BaseDetector(ABC):
    """
    威科夫检测器基类，定义统一接口
    """
    def __init__(self):
        self._current_phase = ""
        # 🔧 P1-1修复：存储Phase A事件检测结果，供LPS等信号验证前置结构
        self._phase_a_events = {}

    def update_analysis_context(self, phase: str):
        """
        更新分析上下文（如当前识别到的阶段）

        Args:
            phase: 当前识别到的市场阶段字符串
        """
        self._current_phase = phase

    def set_phase_a_events(self, events: dict):
        """
        🔧 P1-1修复：设置Phase A事件检测结果

        Args:
            events: 包含SC/AR/ST检测结果的字典
        """
        self._phase_a_events = events

    def get_phase_a_events(self) -> dict:
        """获取Phase A事件检测结果"""
        return self._phase_a_events
