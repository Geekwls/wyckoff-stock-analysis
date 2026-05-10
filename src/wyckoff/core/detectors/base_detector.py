from abc import ABC
from datetime import datetime
import pandas as pd
import os

USE_VECTORIZED = os.environ.get('WYCKOFF_VECTORIZED', '1') == '1'

class BaseDetector(ABC):
    """
    威科夫检测器基类，定义统一接口

    🔧 v1.2新增：信号时间衰减全局应用
    - 自动过滤过期信号（默认60天有效期）
    - 支持不同信号类型的自定义有效期
    """
    def __init__(self):
        self._current_phase = ""
        # 🔧 P1-1修复：存储Phase A事件检测结果，供LPS等信号验证前置结构
        self._phase_a_events = {}
        # 🔧 v1.2新增：信号有效期配置（天数）
        self._signal_decay_days = 60  # 默认信号有效期60天
        self._signal_decay_config = {
            'spring': 90,      # Spring信号有效期90天
            'upthrust': 90,    # Upthrust信号有效期90天
            'joc': 60,         # JOC信号有效期60天
            'lps': 45,         # LPS信号有效期45天
            'sos': 75,         # SOS信号有效期75天
            'sow': 75,         # SOW信号有效期75天
            'default': 60      # 默认有效期60天
        }

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

    def _is_signal_stale(self, signal_date, signal_type: str = 'default') -> bool:
        """
        🔧 v1.2新增：检查信号是否过期

        理论依据：威科夫信号具有时效性
        - Spring/Upthrust等结构性信号：90天有效期
        - JOC/LPS等入场信号：45-60天有效期
        - 超过有效期的信号应该被过滤

        Args:
            signal_date: 信号日期（datetime或pd.Timestamp）
            signal_type: 信号类型，用于确定有效期

        Returns:
            True表示信号已过期，False表示信号仍有效
        """
        if signal_date is None:
            return False

        # 获取该类型信号的有效期
        max_days = self._signal_decay_config.get(signal_type, self._signal_decay_config['default'])

        # 统一转换为带时区的 pd.Timestamp (UTC)
        try:
            if isinstance(signal_date, str):
                ts = pd.to_datetime(signal_date)
            else:
                ts = pd.Timestamp(signal_date)
            
            if ts.tz is None:
                ts = ts.tz_localize('UTC')
            else:
                ts = ts.tz_convert('UTC')
        except Exception:
            return False

        # 计算信号距今的天数 (统一使用 UTC 时间对比)
        now = pd.Timestamp.now(tz='UTC')
        days_ago = (now - ts).days

        return days_ago > max_days

    def _get_signal_age_days(self, signal_date) -> int:
        """
        获取信号的年龄（天数）

        Args:
            signal_date: 信号日期

        Returns:
            信号距今的天数
        """
        if signal_date is None:
            return 0

        try:
            if isinstance(signal_date, str):
                ts = pd.to_datetime(signal_date)
            else:
                ts = pd.Timestamp(signal_date)
            
            if ts.tz is None:
                ts = ts.tz_localize('UTC')
            else:
                ts = ts.tz_convert('UTC')
        except Exception:
            return 0

        now = pd.Timestamp.now(tz='UTC')
        days_ago = (now - ts).days
        return max(0, days_ago)
