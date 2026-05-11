import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, List
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig


def _swing_levels(series: pd.Series, *, kind: str, window: int = 3) -> List[float]:
    """
    寻找摆动低点/高点。
    
    kind='low': 局部最小值（低于左右各 window 根）
    kind='high': 局部最大值（高于左右各 window 根）
    """
    values = series.dropna().reset_index(drop=True)
    out: List[float] = []
    if len(values) < window * 2 + 1:
        return out
    for i in range(window, len(values) - window):
        current = float(values.iloc[i])
        span = values.iloc[i - window : i + window + 1]
        if kind == "low" and current <= float(span.min()):
            out.append(current)
        elif kind == "high" and current >= float(span.max()):
            out.append(current)
    return out


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
        self._phase_high = high
        self._phase_low = low
        self._phase_label = label

    def detect(self, window: int = 60) -> Dict:
        """
        检测交易区间。
        
        优先级：
        1. 威科夫事件边界（BC/AR/SC）— phase_events
        2. 摆动高低点（swing points）— swing
        3. 机械 min/max — mechanical
        """
        if self.data is None or len(self.data) < window:
            return {}

        # ---------- 阶段事件边界（最高优先级） ----------
        if self._phase_high is not None and self._phase_low is not None:
            high = self._phase_high
            low = self._phase_low
            method = "phase_events"
            return self._build_result(high, low, method)

        # ---------- 摆动点检测 ----------
        swing_highs = _swing_levels(self.data['High'], kind='high', window=3)
        swing_lows = _swing_levels(self.data['Low'], kind='low', window=3)

        # 仅使用最近窗口内的摆动点
        lookback = min(window, len(self.data))
        recent = self.data.tail(lookback)
        recent_highs = [h for h in swing_highs if h >= recent['Low'].min()]
        recent_lows = [l for l in swing_lows if l <= recent['High'].max()]

        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            high = float(np.median(recent_highs[-5:]))
            low = float(np.median(recent_lows[-5:]))
            method = "swing"
            # 如果摆动点中位数不合理，回退
            if low <= 0 or high <= low:
                high = recent['High'].max()
                low = recent['Low'].min()
                method = "mechanical"
        else:
            high = recent['High'].max()
            low = recent['Low'].min()
            method = "mechanical"

        return self._build_result(high, low, method)

    def _build_result(self, high: float, low: float, method: str) -> Dict:
        range_pct = (high - low) / low if low > 0 else 0

        # 使用 ATR 动态计算合理振幅阈值
        # 低波动股（ATR ~1%）→ 4% 阈值 → 严格
        # 高波动股（ATR ~5%）→ 20% 阈值 → 宽松
        atr_multiple = 4.0
        atr_pct = None
        if 'ATR' in self.data.columns and len(self.data) > 0:
            atr_val = self.data['ATR'].iloc[-1]
            close_val = self.data['Close'].iloc[-1]
            if pd.notna(atr_val) and close_val > 0:
                atr_pct = atr_val / close_val
                dynamic_threshold = min(max(atr_pct * atr_multiple, 0.08), 0.50)
        if atr_pct is None:
            dynamic_threshold = self.config.spring_range_threshold

        buffer_pct = dynamic_threshold * 0.1
        effective_threshold = dynamic_threshold + buffer_pct
        is_consolidation = range_pct < effective_threshold

        recent = self.data.tail(60)
        vol_trend = 'decreasing' if len(recent) >= 40 and recent['Volume'].iloc[-20:].mean() < recent['Volume'].iloc[:20].mean() else 'increasing'

        current_price = self.data['Close'].iloc[-1]
        position = (current_price - low) / (high - low) if high > low else 0.5

        # 检测 TR 是否已被价格突破而失效
        # 威科夫理论：有效 TR 的前提是价格停留在区间内
        # 当价格超出区间边界超过 ATR 动态阈值时，TR 视为被打破
        breakout_margin = atr_pct * 2.0 if atr_pct else 0.03
        above_range = current_price > high * (1 + breakout_margin)
        below_range = current_price < low * (1 - breakout_margin)
        is_broken = above_range or below_range
        if is_broken:
            is_consolidation = False
        breakout_direction = "up" if above_range else ("down" if below_range else None)

        # 质量评分：支撑/阻力被测试次数 + 区间宽度合理性
        support_tests = int((self.data['Low'] <= low * 1.03).sum())
        resistance_tests = int((self.data['High'] >= high * 0.97).sum())
        quality = round(min(1.0, (support_tests + resistance_tests) / 12.0), 2)

        return {
            'is_consolidation': is_consolidation,
            'is_broken': is_broken,
            'breakout_direction': breakout_direction,
            'high': high,
            'low': low,
            'range_pct': range_pct,
            'duration_days': 60,
            'consolidation_duration_days': 60,
            'volume_trend': vol_trend,
            'position': position,
            'current_price': current_price,
            '_method': method,
            '_phase_events': self._phase_label,
            '_quality': quality,
            '_support_tests': support_tests,
            '_resistance_tests': resistance_tests,
            '_atr_threshold': round(dynamic_threshold, 4),
            '_atr_pct': round(atr_pct, 4) if atr_pct else None,
        }
