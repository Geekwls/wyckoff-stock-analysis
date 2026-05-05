from abc import ABC

class BaseDetector(ABC):
    """
    威科夫检测器基类，定义统一接口
    """
    def __init__(self):
        self._current_phase = ""

    def update_analysis_context(self, phase: str):
        """
        更新分析上下文（如当前识别到的阶段）
        
        Args:
            phase: 当前识别到的市场阶段字符串
        """
        self._current_phase = phase
