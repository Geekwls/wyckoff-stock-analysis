"""60-minute / hourly VSA entry-quality analysis (WIE 3.2 MVP step 1)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from .vsa_analyzer import VSAAnalyzer


class IntradayVSAService:
    """Summarize hourly-bar microstructure for precise LPS/LPSY entry timing."""

    def __init__(self, spread_window: int = 20, vol_window: int = 60):
        self.spread_window = spread_window
        self.vol_window = vol_window

    def analyze_entry_quality(
        self,
        df_hourly: pd.DataFrame,
        *,
        direction: str = 'long',
        anchor_level: Optional[float] = None,
    ) -> Dict[str, Any]:
        if df_hourly is None or len(df_hourly) < 12:
            return {
                'available': False,
                'entry_quality': 'unknown',
                'note': '小时线数据不足',
            }

        window = min(self.vol_window, max(len(df_hourly), self.spread_window))
        analyzer = VSAAnalyzer(spread_window=min(self.spread_window, window), vol_percentile_window=window)
        out = analyzer.analyze(df_hourly.tail(max(window, 24)).copy())
        if out.empty:
            return {'available': False, 'entry_quality': 'unknown', 'note': 'VSA 分析失败'}

        last = out.iloc[-1]
        close = float(last['close'])
        vol_pct = float(last['vol_percentile'])
        evr = float(last['evr_divergence'])
        clv = float(last['clv'])
        spread_z = float(last['spread_zscore'])

        vol_ma = float(out['volume'].rolling(min(12, len(out))).mean().iloc[-1])
        vol_ratio = float(last['volume']) / vol_ma if vol_ma > 0 else 1.0
        low_volume = vol_ratio < 0.85

        near_anchor = True
        if anchor_level and anchor_level > 0:
            tolerance = max(anchor_level * 0.015, 0.01)
            if direction == 'long':
                near_anchor = abs(close - anchor_level) <= tolerance or close <= anchor_level * 1.01
            else:
                near_anchor = abs(close - anchor_level) <= tolerance or close >= anchor_level * 0.99

        no_supply = direction == 'long' and evr > 0.25 and clv > 0.15 and low_volume
        no_demand = direction == 'short' and evr > 0.25 and clv < -0.15 and low_volume
        narrow_spread = spread_z < 0.5 and low_volume

        vsa_confirmed = no_supply or no_demand
        if vsa_confirmed and near_anchor:
            entry_quality = 'excellent'
        elif vsa_confirmed or (narrow_spread and near_anchor):
            entry_quality = 'good'
        elif near_anchor:
            entry_quality = 'fair'
        else:
            entry_quality = 'unknown'

        flags = []
        if no_supply:
            flags.append('NO_SUPPLY')
        if no_demand:
            flags.append('NO_DEMAND')
        if narrow_spread:
            flags.append('NARROW_SPREAD')

        return {
            'available': True,
            'entry_quality': entry_quality,
            'direction': direction,
            'current_price': round(close, 2),
            'volume_ratio': round(vol_ratio, 2),
            'vol_percentile': round(vol_pct, 3),
            'evr_divergence': round(evr, 3),
            'clv': round(clv, 3),
            'spread_zscore': round(spread_z, 3),
            'near_anchor': near_anchor,
            'no_supply': no_supply,
            'no_demand': no_demand,
            'narrow_spread': narrow_spread,
            'flags': flags,
            'note': self._build_note(direction, entry_quality, flags, vol_ratio),
        }

    @staticmethod
    def _build_note(direction: str, quality: str, flags: list[str], vol_ratio: float) -> str:
        side = '无供应' if direction == 'long' else '无需求'
        if quality == 'excellent':
            return f"60min VSA：{side} + 锚点共振 + 量比{vol_ratio:.2f}x（优质入场）"
        if quality == 'good':
            tag = '/'.join(flags) if flags else '缩量'
            return f"60min VSA：{tag} 确认，量比{vol_ratio:.2f}x"
        if quality == 'fair':
            return f"60min 接近锚点，等待{side}确认（量比{vol_ratio:.2f}x）"
        return "60min 微观结构未确认入场条件"
