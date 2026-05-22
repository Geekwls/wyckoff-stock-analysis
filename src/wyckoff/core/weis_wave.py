import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Any, cast

@dataclass
class WeisWave:
    direction: str       # 'up' or 'down'
    start_idx: Any       # 开始时间的索引
    end_idx: Any         # 结束时间的索引
    start_price: float   # 起始价格
    end_price: float     # 结束价格
    thrust: float        #  缺陷2修复：百分比涨跌幅 abs(end-start)/start，跨价位可比
    volume: float        # 波段累加成交量
    duration: int        # 波段持续天数/K线数


class WeisWaveGenerator:
    """
    韦斯波浪发生器 (Weis Wave Generator)
    核心思想：按波段方向（上涨或下跌）累加成交量，展现真实的“努力”。
    转折点确认：基于动态 ATR 倍数（默认2倍）或固定百分比。
    """
    def __init__(self, data: pd.DataFrame, atr_multiplier: float = 2.0, fallback_pct: float = 0.03):
        self.data = data
        self.atr_multiplier = atr_multiplier
        self.fallback_pct = fallback_pct

    def _calculate_atr(self, window: int = 14) -> pd.Series:
        if 'ATR' in self.data.columns:
            res = self.data['ATR']
            if isinstance(res, pd.DataFrame):
                return cast(pd.Series, res.iloc[:, 0])
            return cast(pd.Series, res)

        high = self.data['High']
        low = self.data['Low']
        close = self.data['Close'].shift(1)

        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()

        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        atr = tr.rolling(window=window, min_periods=1).mean()
        return cast(pd.Series, atr)

    def find_pivots(self) -> List[dict]:
        """寻找波段的高低转折点"""
        if len(self.data) < 2:
            return []

        atr = self._calculate_atr()
        highs = self.data['High'].values
        lows = self.data['Low'].values
        closes = self.data['Close'].values

        pivots = []
        direction = 0  # 1 for up, -1 for down

        extreme_idx = 0
        extreme_high = highs[0]
        extreme_low = lows[0]
        #  缺陷1修复：独立跟踪极值高低点各自的真实索引
        extreme_high_idx = 0
        extreme_low_idx = 0

        for i in range(1, len(self.data)):
            current_high = highs[i]
            current_low = lows[i]

            current_atr = atr.iloc[i]
            if pd.notna(current_atr) and current_atr > 0:
                reversal_amount = current_atr * self.atr_multiplier
            else:
                reversal_amount = closes[i] * self.fallback_pct

            if direction == 0:
                if current_high >= extreme_low + reversal_amount:
                    direction = 1
                    extreme_high = current_high
                    extreme_high_idx = i
                    extreme_idx = i
                    #  缺陷1修复：使用真实 extreme_low_idx 而非硬编码 0
                    pivots.append({'idx': extreme_low_idx, 'price': extreme_low, 'type': 'low'})
                elif current_low <= extreme_high - reversal_amount:
                    direction = -1
                    extreme_low = current_low
                    extreme_low_idx = i
                    extreme_idx = i
                    #  缺陷1修复：使用真实 extreme_high_idx 而非硬编码 0
                    pivots.append({'idx': extreme_high_idx, 'price': extreme_high, 'type': 'high'})
                else:
                    # 更新各自极值及其索引
                    if current_high > extreme_high:
                        extreme_high = current_high
                        extreme_high_idx = i
                        extreme_idx = i
                    if current_low < extreme_low:
                        extreme_low = current_low
                        extreme_low_idx = i
                        extreme_idx = i

            elif direction == 1:
                if current_high > extreme_high:
                    extreme_high = current_high
                    extreme_high_idx = i
                    extreme_idx = i
                elif current_low <= extreme_high - reversal_amount:
                    # 向下反转确认
                    pivots.append({'idx': extreme_idx, 'price': extreme_high, 'type': 'high'})
                    direction = -1
                    extreme_low = current_low
                    extreme_low_idx = i
                    extreme_idx = i

            elif direction == -1:
                if current_low < extreme_low:
                    extreme_low = current_low
                    extreme_low_idx = i
                    extreme_idx = i
                elif current_high >= extreme_low + reversal_amount:
                    # 向上反转确认
                    pivots.append({'idx': extreme_idx, 'price': extreme_low, 'type': 'low'})
                    direction = 1
                    extreme_high = current_high
                    extreme_high_idx = i
                    extreme_idx = i

        # 处理最后一个未闭合的波段
        if not pivots or extreme_idx != pivots[-1]['idx']:
            p_type = 'high' if direction == 1 else 'low'
            p_price = extreme_high if direction == 1 else extreme_low
            pivots.append({'idx': extreme_idx, 'price': p_price, 'type': p_type})

        return pivots

    def generate(self) -> List[WeisWave]:
        """生成所有的 Weis Wave 波段"""
        pivots = self.find_pivots()
        waves = []
        indices = self.data.index
        volumes = np.asarray(self.data['Volume'])

        for i in range(1, len(pivots)):
            start_pivot = pivots[i-1]
            end_pivot = pivots[i]

            start_idx = start_pivot['idx']
            end_idx = end_pivot['idx']

            if end_idx <= start_idx:
                continue

            direction = 'up' if end_pivot['type'] == 'high' else 'down'
            start_price = start_pivot['price']
            end_price = end_pivot['price']

            # 成交量累加：从转折点后一根 K 线开始，直到（并包含）当前波段的极值点
            vol_sum = float(np.sum(volumes[start_idx + 1 : end_idx + 1]))

            waves.append(WeisWave(
                direction=direction,
                start_idx=indices[start_idx],
                end_idx=indices[end_idx],
                start_price=float(start_price),
                end_price=float(end_price),
                # 改用百分比推力，使不同价位的波段推力可横向比较
                thrust=float(abs(end_price - start_price) / start_price) if start_price > 0 else 0.0,
                volume=vol_sum,
                duration=int(end_idx - start_idx)
            ))

        return waves
