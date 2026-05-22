import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple, List
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig, WyckoffThresholds

logger = logging.getLogger(__name__)

class PsDetector(BaseDetector):
    """
    初次支撑 (Preliminary Support, PS) 检测器
    
    理论依据：
    - PS 是主跌段中的第一次抄底尝试，发生在 SC (恐慌抛售) 之前。
    - 特征：成交量放大 + 价格止跌/反弹 + 下影线抵抗。
    - 时序关系：PS -> SC -> AR -> ST (吸筹 Phase A)。
    """
    
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect(self, lookback_days: int = 90) -> Dict:
        """
        检测 PS 信号
        """
        try:
            if self.data is None or len(self.data) < 20:
                return {"detected": False, "reason": "数据不足"}

            # 1. 寻找主跌段的起点或低位区域
            recent_data = self.data.tail(lookback_days)
            downtrend_start = self._find_downtrend_start(recent_data)
            
            if downtrend_start is None:
                return {"detected": False, "reason": "未检测到明显的下跌趋势"}
            if downtrend_start >= len(recent_data) - 5:
                return {"detected": False, "reason": "下跌趋势太短"}

            # 动态阈值
            from ..utils import TypeConverter
            atr_pct = self._calculate_atr_pct(recent_data)
            vol_threshold = self.thresholds.get_dynamic_volume_threshold(atr_pct, 1.2)
            vol_strong_threshold = self.thresholds.get_dynamic_volume_threshold(atr_pct, 1.5)

            potential_ps = []
            downtrend_data = recent_data.iloc[downtrend_start:]
            
            for i in range(2, len(downtrend_data) - 1):
                current = downtrend_data.iloc[i]
                prev = downtrend_data.iloc[i-1]
                next_day = downtrend_data.iloc[i+1]
                
                vol_ma = current.get('Volume_MA20', recent_data['Volume'].iloc[:downtrend_start + i + 1].tail(20).mean())
                vol_ratio = current['Volume'] / vol_ma if vol_ma > 0 else 1.0
                
                # PS 特征：放量止跌
                if vol_ratio < vol_threshold:
                    continue
                
                # 价格止跌证据：收盘 > 前一收盘 或 收盘 > 开盘
                price_stabilized = (current['Close'] > prev['Close']) or (current['Close'] > current['Open'])
                body = abs(current['Close'] - current['Open'])
                lower_shadow = min(current['Open'], current['Close']) - current['Low']
                # 下影线抵抗
                shadow_resistance = lower_shadow > body * 0.5 if body > 0 else lower_shadow > 0
                
                if not (price_stabilized and shadow_resistance):
                    continue
                
                # 评分逻辑
                confidence = 50
                if vol_ratio > vol_strong_threshold:
                    confidence += 15
                if current['Close'] > current['Open']:
                    confidence += 10
                if lower_shadow > body:
                    confidence += 10
                if next_day['Close'] > current['Close']:
                    confidence += 15
                
                potential_ps.append({
                    "date": downtrend_data.index[i],
                    "price": float(current['Close']),
                    "low": float(current['Low']),
                    "vol_ratio": float(vol_ratio),
                    "lower_shadow_ratio": float(lower_shadow / (body + 0.001)),
                    "confidence": min(100, confidence),
                    "idx": downtrend_start + i
                })

            if not potential_ps:
                return {"detected": False, "reason": "未找到符合 PS 特征的量价组合"}

            # 取置信度最高的作为 PS
            best_ps = max(potential_ps, key=lambda x: x['confidence'])
            
            # 验证 PS 之后是否有 SC (恐慌抛售)
            post_ps_data = recent_data.iloc[best_ps['idx'] + 1:]
            sc_found = False
            sc_price = None
            for _, row in post_ps_data.iterrows():
                if row['Low'] < best_ps['low']:
                    row_vol_ma = row.get('Volume_MA20', recent_data['Volume'].rolling(20).mean().loc[row.name])
                    if row['Volume'] > row_vol_ma * 1.5:
                        sc_found = True
                        sc_price = float(row['Low'])
                        break

            return {
                "detected": True,
                "date": best_ps['date'], # 修正为正确的变量名，之前实现可能有误
                "ps_date": best_ps['date'],
                "ps_price": best_ps['price'],
                "ps_low": best_ps['low'],
                "vol_ratio": best_ps['vol_ratio'],
                "lower_shadow_ratio": best_ps['lower_shadow_ratio'],
                "confidence": best_ps['confidence'],
                "sc_confirmed_after": sc_found,
                "sc_price": sc_price,
                "theory": "PS 是主跌段中的第一次抄底尝试，发生在 SC 之前。"
            }

        except Exception as e:
            logger.error(f"PS 检测过程出错: {e}")
            return {"detected": False, "error": str(e)}

    def _find_downtrend_start(self, data: pd.DataFrame) -> Optional[int]:
        """找到主跌段起点（价格跌破MA20的位置）"""
        ma20 = data['Close'].rolling(window=20).mean()
        downtrend_mask = data['Close'] < ma20
        if not downtrend_mask.any():
            return None
        for i in range(len(data)):
            if downtrend_mask.iloc[i]:
                return i
        return None

    def _calculate_atr_pct(self, data: pd.DataFrame) -> float:
        """计算 ATR 百分比"""
        try:
            if 'ATR' in data.columns:
                return float(data['ATR'].iloc[-1] / data['Close'].iloc[-1])
            return 0.03
        except:
            return 0.03
