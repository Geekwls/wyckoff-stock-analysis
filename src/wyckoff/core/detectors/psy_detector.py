import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple, List
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig, WyckoffThresholds

logger = logging.getLogger(__name__)

class PsyDetector(BaseDetector):
    """
    初次供应 (Preliminary Supply, PSY) 检测器
    
    理论依据：
    - PSY 是主升段中的第一次显著抛压，发生在 BC (买入高潮) 之前。
    - 特征：成交量放大 + 价格涨幅受窄或回落 + 上影线表现出供应压力。
    - 时序关系：PSY -> BC -> AR -> ST (派发 Phase A)。
    """
    
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect(self, lookback_days: int = 90) -> Dict:
        """
        检测 PSY 信号
        """
        try:
            if self.data is None or len(self.data) < 20:
                return {"detected": False, "reason": "数据不足"}

            # 1. 寻找主升浪的终点或高位区域
            recent_data = self.data.tail(lookback_days)
            uptrend_end_idx = self._find_uptrend_high_area(recent_data)
            
            if uptrend_end_idx is None:
                return {"detected": False, "reason": "未检测到明显的上涨趋势或高位区域"}

            # 2. 在高位区域前寻找符合 PSY 特征的 Bar
            # PSY 必须出现在高位区域，且在最终 BC 之前（或作为 BC 前的预警）
            search_data = recent_data.loc[:uptrend_end_idx]
            if len(search_data) < 5:
                return {"detected": False, "reason": "高位区域搜索范围过小"}

            # 动态阈值
            from ..utils import TypeConverter
            atr_pct = self._calculate_atr_pct(search_data)
            vol_threshold = self.thresholds.get_dynamic_volume_threshold(atr_pct, 1.3)
            vol_strong_threshold = self.thresholds.get_dynamic_volume_threshold(atr_pct, 1.8)

            potential_psy = []
            
            # 遍历寻找候选 PSY
            for i in range(5, len(search_data)):
                current = search_data.iloc[i]
                prev = search_data.iloc[i-1]
                
                vol_ma = current.get('Volume_MA20', search_data['Volume'].iloc[:i+1].tail(20).mean())
                vol_ratio = current['Volume'] / vol_ma if vol_ma > 0 else 1.0
                
                # PSY 特征 1：放量 (Effort)
                if vol_ratio < vol_threshold:
                    continue
                
                # PSY 特征 2：涨幅受窄或冲高回落 (Result)
                price_change = (current['Close'] - prev['Close']) / prev['Close']
                range_size = current['High'] - current['Low']
                body_size = abs(current['Close'] - current['Open'])
                upper_shadow = current['High'] - max(current['Open'], current['Close'])
                
                # 价格受阻的证据：
                # a) 冲高回落，上影线长
                # b) 成交量巨大但价格几乎没动 (Effort vs Result 背离)
                # c) 虽然收阳，但涨幅明显小于之前的力度
                
                shadow_resistance = upper_shadow > body_size * 0.4 if body_size > 0 else upper_shadow > 0
                effort_vs_result = vol_ratio > 2.0 and price_change < 0.01
                
                if not (shadow_resistance or effort_vs_result or price_change < 0):
                    continue

                # 评分逻辑
                confidence = 50
                if vol_ratio > vol_strong_threshold: confidence += 15
                if upper_shadow > body_size: confidence += 15
                if current['Close'] < current['Open']: confidence += 10 # 阴线 PSY 更有力
                if effort_vs_result: confidence += 10
                
                potential_psy.append({
                    "date": search_data.index[i],
                    "price": float(current['Close']),
                    "high": float(current['High']),
                    "volume_ratio": round(float(vol_ratio), 2),
                    "confidence": min(100, confidence),
                    "idx": i
                })

            if not potential_psy:
                return {"detected": False, "reason": "未找到符合 PSY 特征的量价组合"}

            # 取置信度最高的作为 PSY
            best_psy = max(potential_psy, key=lambda x: x['confidence'])
            
            # 3. 验证时序：PSY 之后是否有 BC (买入高潮)
            # 在 PSY 之后寻找更高点且伴随更大成交量的 Bar
            post_psy_data = recent_data.loc[recent_data.index > best_psy['date']]
            bc_confirmed = False
            bc_price = None
            
            for _, row in post_psy_data.iterrows():
                if row['High'] > best_psy['high'] * 0.99: # 接近或突破 PSY 高点
                    row_vol_ma = row.get('Volume_MA20', recent_data['Volume'].rolling(20).mean().loc[row.name])
                    if row['Volume'] > row_vol_ma * 2.0: # 伴随巨量
                        bc_confirmed = True
                        bc_price = float(row['High'])
                        break

            return {
                "detected": True,
                "date": best_psy['date'],
                "price": best_psy['price'],
                "high": best_psy['high'],
                "volume_ratio": best_psy['volume_ratio'],
                "confidence": best_psy['confidence'],
                "bc_confirmed_after": bc_confirmed,
                "bc_price": bc_price,
                "theory": "PSY 是派发阶段的第一个迹象，大资金开始释放供应以满足狂热需求。"
            }

        except Exception as e:
            logger.error(f"PSY 检测过程出错: {e}")
            return {"detected": False, "error": str(e)}

    def _find_uptrend_high_area(self, data: pd.DataFrame) -> Optional[any]:
        """寻找上涨趋势的高位区域起点"""
        if len(data) < 10: return None
        
        # 简单判断：价格位于 MA20 之上且 MA20 向上
        ma20 = data['Close'].rolling(window=20).mean()
        uptrend_mask = (data['Close'] > ma20) & (ma20.diff() > 0)
        
        if not uptrend_mask.any():
            return None
            
        # 返回最高点所在的日期，作为搜索的截止点
        return data['High'].idxmax()

    def _calculate_atr_pct(self, data: pd.DataFrame) -> float:
        """计算 ATR 百分比"""
        try:
            if 'ATR' in data.columns:
                return float(data['ATR'].iloc[-1] / data['Close'].iloc[-1])
            # 简易计算
            tr = pd.concat([
                data['High'] - data['Low'],
                (data['High'] - data['Close'].shift(1)).abs(),
                (data['Low'] - data['Close'].shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            return float(atr / data['Close'].iloc[-1])
        except:
            return 0.03
