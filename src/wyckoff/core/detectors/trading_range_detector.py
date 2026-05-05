import pandas as pd
from typing import Dict, Optional
from ...config.settings import WyckoffConfig

class TradingRangeDetector:
    """负责检测交易区间（积累/分布）"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig):
        self.data = data
        self.config = config

    def detect(self, window: int = 60) -> Dict:
        """
        检测交易区间
        
        关键修复：添加缓冲区（buffer），避免因为微小差异而产生错误判断
        例如：range_pct=30.2% 和 spring_range_threshold=30% 的差距只有0.2%，
        但从逻辑上来说，30.2%的波动范围应该被认为是"盘整"而非"趋势"
        """
        if self.data is None or len(self.data) < window:
            return {}

        df = self.data.tail(window).copy()
        high_max = df['High'].max()
        low_min = df['Low'].min()
        range_pct = (high_max - low_min) / low_min
        
        # 关键修复：添加5%的缓冲区，避免因为微小差异而产生错误判断
        # 例如：threshold=30%，buffer=5%，则实际阈值=35%
        buffer_pct = 0.05  # 5%的缓冲区
        effective_threshold = self.config.spring_range_threshold + buffer_pct
        is_consolidation = range_pct < effective_threshold

        recent_mean = df['Volume'].iloc[-20:].mean()
        early_mean = df['Volume'].iloc[:-20].mean() if len(df) > 20 else recent_mean
        vol_trend = 'decreasing' if recent_mean < early_mean else 'increasing'

        current_price = df['Close'].iloc[-1]
        position = (current_price - low_min) / (high_max - low_min) if high_max > low_min else 0.5

        consolidation_duration_days = window
        if is_consolidation and len(self.data) > window:
            extra_df = self.data.copy()
            for extra_window in [90, 120, 180, 252]:
                if len(extra_df) < extra_window:
                    break
                ext = extra_df.tail(extra_window)
                ext_range = (ext['High'].max() - ext['Low'].min()) / ext['Low'].min()
                if ext_range < self.config.spring_range_threshold + 0.05:
                    consolidation_duration_days = extra_window
                else:
                    break

        return {
            'is_consolidation': is_consolidation,
            'high': high_max,
            'low': low_min,
            'range_pct': range_pct,
            'duration_days': window,
            'consolidation_duration_days': consolidation_duration_days,
            'volume_trend': vol_trend,
            'position': position,
            'current_price': current_price
        }
