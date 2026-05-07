import pandas as pd
from typing import Dict, Optional, Tuple, List
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig

class TradingRangeDetector(BaseDetector):
    """负责检测交易区间（积累/分布）"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig):
        super().__init__()
        self.data = data
        self.config = config
        self._phase_high = None
        self._phase_low = None
        self._phase_label = ""

    def update_from_phase_events(self, high: float, low: float, label: str = ""):
        """
        从威科夫阶段事件更新区间边界（替代机械扫描）
        
        派发期：high=BC高点, low=AR低点
        积累期：high=AR高点, low=SC低点
        
        Args:
            high: 已知区间上沿
            low: 已知区间下沿
            label: 事件描述（如 "BC-AR"）
        """
        self._phase_high = high
        self._phase_low = low
        self._phase_label = label

    def detect(self, window: int = 60) -> Dict:
        """
        检测交易区间
        
        优先使用已知的威科夫事件边界（BC/AR/SC），
        当事件边界不可用时回退到机械扫描。
        """
        if self.data is None or len(self.data) < window:
            return {}

        if self._phase_high is not None and self._phase_low is not None:
            high_max = self._phase_high
            low_min = self._phase_low
            range_pct = (high_max - low_min) / low_min if low_min > 0 else 0
            method = "phase_events"
        else:
            df = self.data.tail(window).copy()
            high_max = df['High'].max()
            low_min = df['Low'].min()
            range_pct = (high_max - low_min) / low_min
            method = "mechanical"

        buffer_pct = self.config.spring_range_threshold * 0.1
        effective_threshold = self.config.spring_range_threshold + buffer_pct
        is_consolidation = range_pct < effective_threshold

        recent = self.data.tail(60)
        recent_mean = recent['Volume'].iloc[-20:].mean() if len(recent) >= 20 else recent['Volume'].mean()
        early_mean = recent['Volume'].iloc[:20].mean() if len(recent) >= 40 else recent_mean
        vol_trend = 'decreasing' if recent_mean < early_mean else 'increasing'

        current_price = self.data['Close'].iloc[-1]
        position = (current_price - low_min) / (high_max - low_min) if high_max > low_min else 0.5

        return {
            'is_consolidation': is_consolidation,
            'high': high_max,
            'low': low_min,
            'range_pct': range_pct,
            'duration_days': window,
            'consolidation_duration_days': window,
            'volume_trend': vol_trend,
            'position': position,
            'current_price': current_price,
            '_method': method,
            '_phase_events': self._phase_label,
        }
