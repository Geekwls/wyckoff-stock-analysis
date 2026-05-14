import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional
from .base_detector import BaseDetector
from ..weis_wave import WeisWaveGenerator, WeisWave

logger = logging.getLogger(__name__)

class ChannelDetector(BaseDetector):
    """
    倾斜趋势通道检测器 (Trend Channels)
    基于 Weis Wave 的波段高低点，构建上升/下降通道。
    检测超买/超卖 (Overbought/Oversold) 刺穿，以及行为改变 (COB)。
    """
    def __init__(self, data: pd.DataFrame, use_log_price: bool = False, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.use_log_price = use_log_price

    def _calc_slope(self, idx1: int, price1: float, idx2: int, price2: float) -> float:
        if idx2 == idx1:
            return 0.0
        if self.use_log_price:
            return (np.log(price2) - np.log(price1)) / (idx2 - idx1)
        else:
            return (price2 - price1) / (idx2 - idx1)

    def _get_y(self, slope: float, anchor_idx: int, anchor_price: float, target_idx: int) -> float:
        if self.use_log_price:
            return np.exp(np.log(anchor_price) + slope * (target_idx - anchor_idx))
        else:
            return anchor_price + slope * (target_idx - anchor_idx)

    def build_channel(self) -> Optional[Dict]:
        """寻找并构建当前主导的趋势通道"""
        generator = WeisWaveGenerator(self.data)
        pivots = generator.find_pivots()
        waves = generator.generate()
        
        if len(pivots) < 3:
            return None
            
        # 寻找最近的有效结构通道（最多回溯 5 个拐点，确保通道对当前价格有约束力）
        for i in range(len(pivots) - 1, max(1, len(pivots) - 6), -1):
            p3 = pivots[i]
            p2 = pivots[i-1]
            p1 = pivots[i-2]
            
            if p1['type'] == 'low' and p3['type'] == 'low' and p2['type'] == 'high':
                if p3['price'] > p1['price']:
                    # 上升通道: L1, H1, L2 (L2 > L1)
                    return self._create_channel('up', p1, p2, p3, waves)
                    
            elif p1['type'] == 'high' and p3['type'] == 'high' and p2['type'] == 'low':
                if p3['price'] < p1['price']:
                    # 下降通道: H1, L1, H2 (H2 < H1)
                    return self._create_channel('down', p1, p2, p3, waves)
                    
        return None

    def _create_channel(self, channel_type: str, p1: dict, p2: dict, p3: dict, waves: List[WeisWave]) -> Dict:
        slope = self._calc_slope(p1['idx'], p1['price'], p3['idx'], p3['price'])
        return {
            'type': channel_type,
            'p1': p1,        # Demand/Supply 起点
            'p2': p2,        # 平行线锚点 (H1 或 L1)
            'p3': p3,        # Demand/Supply 终点
            'slope': slope,
            'anchor': p2,
            'waves': waves
        }

    def _check_largest_thrust(self, waves: List[WeisWave], target_dir: str) -> bool:
        """检查当前的逆势推力是否是近期最大的一次"""
        dir_waves = [w for w in waves if w.direction == target_dir]
        if not dir_waves:
            return True
            
        last_wave = dir_waves[-1]
        recent_counter_waves = dir_waves[-5:-1] # 比较最近的几次同向波段
        if not recent_counter_waves:
            return True
            
        max_previous_thrust = max(w.thrust for w in recent_counter_waves)
        return last_wave.thrust > max_previous_thrust

    def detect(self) -> Dict:
        result = {
            'has_channel': False,
            'overbought_oversold': None,
            'cob': None
        }
        
        if len(self.data) < 20:
            return result
            
        channel = self.build_channel()
        if not channel:
            return result
            
        result['has_channel'] = True
        result['channel_type'] = channel['type']
        
        current_idx = len(self.data) - 1
        current_row = self.data.iloc[-1]
        current_price = current_row['Close']
        current_high = current_row['High']
        current_low = current_row['Low']
        
        # 如果通道是非常久远的，可能已经失效，不做判断
        if current_idx - channel['p3']['idx'] > 60:
            return result
        
        boundary_y = self._get_y(channel['slope'], channel['p3']['idx'], channel['p3']['price'], current_idx)
        parallel_y = self._get_y(channel['slope'], channel['anchor']['idx'], channel['anchor']['price'], current_idx)
        
        # 1. 超买/超卖检测 (2% 阈值 + 放量确认)
        ob_os_threshold = 0.02
        vol_ma = self.data['Volume'].mean()
        high_volume = current_row['Volume'] > vol_ma * 1.5
        
        # 也可以结合 SOT 判断，这里简化为量能放大（代表 Climax）
        
        if channel['type'] == 'up':
            # 刺穿超买线
            if current_high > parallel_y * (1 + ob_os_threshold):
                if high_volume:
                    result['overbought_oversold'] = {
                        'status': 'overbought',
                        'price': round(current_high, 2),
                        'line_price': round(parallel_y, 2),
                        'message': '强势刺穿超买线并伴随放量，警惕趋势耗尽 (Buying Climax)'
                    }
        else:
            # 刺穿超卖线
            if current_low < parallel_y * (1 - ob_os_threshold):
                if high_volume:
                    result['overbought_oversold'] = {
                        'status': 'oversold',
                        'price': round(current_low, 2),
                        'line_price': round(parallel_y, 2),
                        'message': '强势跌破超卖线并伴随放量，可能出现恐慌抛售极值 (Selling Climax)'
                    }
                    
        # 2. 行为改变 (COB) 检测 (0.5% 阈值 + 逆向最大推力确认)
        cob_threshold = 0.005
        
        if channel['type'] == 'up':
            # 跌破需求线
            if current_price < boundary_y * (1 - cob_threshold):
                if self._check_largest_thrust(channel['waves'], 'down'):
                    result['cob'] = {
                        'status': 'cob_down',
                        'price': round(current_price, 2),
                        'line_price': round(boundary_y, 2),
                        'message': '跌破上升通道且向下推力创近期新大，确认为行为改变 (COB)'
                    }
        else:
            # 突破供应线
            if current_price > boundary_y * (1 + cob_threshold):
                if self._check_largest_thrust(channel['waves'], 'up'):
                    result['cob'] = {
                        'status': 'cob_up',
                        'price': round(current_price, 2),
                        'line_price': round(boundary_y, 2),
                        'message': '突破下降通道且向上推力创近期新大，确认为行为改变 (COB)'
                    }
                    
        return result
