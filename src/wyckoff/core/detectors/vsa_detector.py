import pandas as pd
import logging
from typing import Any, Dict
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig, WyckoffThresholds

logger = logging.getLogger(__name__)

class VsaDetector(BaseDetector):
    """
    负责检测成交量价分析 (VSA) 信号
    (No Supply, No Demand, Stopping Volume, Bag Holding, Shakeout)
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect_vsa_signals(self, lookback: int = 20) -> Dict:
        """检测基础 VSA 信号"""
        if self.data is None or len(self.data) < 20:
            return {
                'no_supply': {'detected': False},
                'no_demand': {'detected': False},
                'stopping_vol': {'detected': False}
            }

        df = self.data.tail(lookback).copy()
        vol_ma_raw, _, _ = self._get_tech_indicators(20)
        vol_ma = vol_ma_raw.reindex(df.index) if vol_ma_raw is not None else pd.Series(0.0, index=df.index)
        total_range = (df['High'] - df['Low']).replace(0, float('nan'))
        body_ratio = ((df['Close'] - df['Open']).abs() / total_range).fillna(0)
        close_position = ((df['Close'] - df['Low']) / total_range).fillna(0.5)

        no_supply_mask = (body_ratio < self.thresholds.VSA_NO_SUPPLY_BODY_RATIO) & \
                         (df['Volume'] < vol_ma * self._get_volume_threshold('shrink', self.thresholds.VSA_NO_SUPPLY_VOL_RATIO)) & \
                         (close_position >= self.thresholds.VSA_NO_SUPPLY_CLOSE_POS)

        no_demand_mask = (body_ratio < self.thresholds.VSA_NO_DEMAND_BODY_RATIO) & \
                         (df['Volume'] < vol_ma * self._get_volume_threshold('shrink', self.thresholds.VSA_NO_DEMAND_VOL_RATIO)) & \
                         (close_position <= self.thresholds.VSA_NO_DEMAND_CLOSE_POS)

        stopping_mask = (df['Volume'] > vol_ma * self.thresholds.VSA_STOPPING_VOL_RATIO) & \
                        (body_ratio < self.thresholds.VSA_STOPPING_BODY_RATIO) & \
                        (close_position >= self.thresholds.VSA_STOPPING_CLOSE_POS)

        res: Dict[str, Dict[str, Any]] = {
            'no_supply': {'detected': False},
            'no_demand': {'detected': False},
            'stopping_vol': {'detected': False}
        }
        if no_supply_mask.any():
            idx = no_supply_mask.index[no_supply_mask][-1]
            res['no_supply'] = {'detected': True, 'date': idx, 'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2), 'description': '无供应 (No Supply) - 缩量下跌且收盘位于高位，表明供应已枯竭'}
        if no_demand_mask.any():
            idx = no_demand_mask.index[no_demand_mask][-1]
            res['no_demand'] = {'detected': True, 'date': idx, 'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2), 'description': '无需求 (No Demand) - 缩量上涨且收盘位于低位，表明买盘动力不足'}
        if stopping_mask.any():
            idx = stopping_mask.index[stopping_mask][-1]
            # 检查是否同时符合 Bag Holding 条件
            bag_res = self.detect_bag_holding()
            if bag_res.get('detected') and bag_res.get('date') == idx:
                res['stopping_vol'] = bag_res
            else:
                res['stopping_vol'] = {'detected': True, 'date': idx, 'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2), 'description': '停止行为 (Stopping Volume) - 放量但价差缩小，表明需求开始吸收供应'}
        return res

    def detect_bag_holding(self) -> Dict:
        """检测 Bag Holding (极端抛售高潮)"""
        if self.data is None or len(self.data) < 20:
            return {'detected': False}
        df = self.data.tail(20)
        vol_ma_raw, _, _ = self._get_tech_indicators(20)
        vol_ma = vol_ma_raw.reindex(df.index) if vol_ma_raw is not None else pd.Series(0.0, index=df.index)

        total_range = (df['High'] - df['Low']).replace(0, float('nan'))
        body_size = (df['Close'] - df['Open']).abs()
        body_ratio = body_size / total_range

        mask = (df['Volume'] > vol_ma * self.thresholds.VSA_BAG_HOLDING_VOL_RATIO) & \
               (body_ratio < self.thresholds.VSA_STOPPING_BODY_RATIO) & \
               (df['Low'] <= df['Low'].rolling(10).min() * 1.01) # 在近期低点附近

        if mask.any():
            idx = mask.index[mask][-1]
            return {
                'detected': True,
                'type': 'bag_holding',
                'date': idx,
                'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2),
                'description': '接盘 (Bag Holding) - 极端放量且窄幅，发生在关键低位，表明大资金全力进场接盘，是强烈的停止行为'
            }
        return {'detected': False}

    def detect_shakeout(self, spring_detector=None) -> Dict:
        """检测 Shakeout (终极震仓)"""
        if not spring_detector:
            return {'detected': False}
        spring_res = spring_detector.detect_spring()
        if spring_res.get('detected'):
            latest = spring_res['latest_spring']
            support, breakdown_price = latest['support_level'], latest['breakdown_price']
            if support > 0:
                breakdown_pct = (support - breakdown_price) / support
                if breakdown_pct >= self.thresholds.VSA_SHAKEOUT_DEPTH:
                    return {'detected': True, 'date': latest['date'], 'depth': round(breakdown_pct * 100, 2), 'description': 'Shakeout - 剧烈震仓，深度洗盘后快速回收'}
        return {'detected': False}

    def detect_divergence(self, window: int = 30) -> Dict:
        """检测背离"""
        if self.data is None or len(self.data) < window:
            return {'detected': False}
        df = self.data.tail(window).copy()
        if 'RSI' not in df.columns or bool(df['RSI'].isna().all()):
            return {'detected': False}
        mid = len(df) // 2
        df_e, df_l = df.iloc[:mid], df.iloc[mid:]
        if len(df_e) < 5 or len(df_l) < 5:
            return {'detected': False}

        if df_l['High'].max() > df_e['High'].max() and df_l['RSI'].max() < df_e['RSI'].max():
            return {'detected': True, 'type': 'top_divergence', 'confidence': 0.8}
        if df_l['Low'].min() < df_e['Low'].min() and df_l['RSI'].min() > df_e['RSI'].min():
            return {'detected': True, 'type': 'bottom_divergence', 'confidence': 0.8}
        return {'detected': False}
