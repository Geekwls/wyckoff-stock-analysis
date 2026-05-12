import pandas as pd
import numpy as np
import logging
from typing import Dict, List
from .base_detector import BaseDetector

logger = logging.getLogger(__name__)

class MengVsaDetector(BaseDetector):
    """
    孟洪涛增强型 VSA 检测器
    (VSA Signals, Boring Zone)
    """
    def __init__(self, data: pd.DataFrame, config, thresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect_vsa_signals(self) -> Dict:
        """孟洪涛版 VSA 信号检测"""
        if self.data is None or len(self.data) < 20:
            return {"no_supply": {"detected": False}, "no_demand": {"detected": False}, "stopping_vol": {"detected": False}}
        df = self.data.copy()
        vol_ma20 = df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]
        ns, nd, sv = [], [], []
        t = self.thresholds
        for i in range(10, len(df)):
            pr = df['High'].iloc[i] - df['Low'].iloc[i]
            if pr <= 0: continue
            body_pct, vol_r = abs(df['Close'].iloc[i] - df['Open'].iloc[i]) / pr, df['Volume'].iloc[i] / vol_ma20 if vol_ma20 > 0 else 1
            if df['Close'].iloc[i] > df.get('MA20', df['Close'].rolling(20).mean()).iloc[i]:
                if body_pct < t.MENG_VSA_BODY_RATIO:
                    cp = (df['Close'].iloc[i] - df['Low'].iloc[i]) / pr
                    if cp > t.MENG_VSA_CLOSE_POS and vol_r < t.MENG_VSA_VOL_RATIO:
                        ns.append({"date": df.index[i], "vol_ratio": round(vol_r, 2), "close_position": round(cp * 100, 1)})
            if df['Close'].iloc[i] < df.get('MA20', df['Close'].rolling(20).mean()).iloc[i]:
                if body_pct < 0.3 and vol_r < 0.6:
                    nd.append({"date": df.index[i], "vol_ratio": round(vol_r, 2)})
            if df['Close'].iloc[i] < df.get('MA50', df['Close'].rolling(50).mean()).iloc[i]:
                if vol_r > 1.5 and (abs(df['Close'].iloc[i] - df['Open'].iloc[i]) / pr < 0.3):
                    ls = min(df['Open'].iloc[i], df['Close'].iloc[i]) - df['Low'].iloc[i]
                    if ls > pr * 0.3:
                        sv.append({"date": df.index[i], "vol_ratio": round(vol_r, 2), "price": df['Close'].iloc[i]})
        return {
            "no_supply": {"detected": len(ns) > 0, "signals": ns[-5:], "latest": ns[-1] if ns else None},
            "no_demand": {"detected": len(nd) > 0, "signals": nd[-5:], "latest": nd[-1] if nd else None},
            "stopping_vol": {"detected": len(sv) > 0, "signals": sv[-3:], "latest": sv[-1] if sv else None}
        }

    def detect_boring_zone(self, window: int = 14) -> Dict:
        """检测枯燥区"""
        if self.data is None or len(self.data) < window + 20: return {"detected": False, "reason": "insufficient_data"}
        df = self.data.tail(window + 20).copy()
        atr_s = self._calculate_atr_series(df, 14)
        df['ATR_Pct'] = atr_s / df['Close'] * 100
        avg_atr_p = df['ATR_Pct'].iloc[:-window].mean()
        recent = df.tail(window)
        rv_avg = recent['Volume'].mean()
        ov_ma20 = df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]
        vc, ac = rv_avg / ov_ma20 if ov_ma20 > 0 else 1.0, recent['ATR_Pct'].mean() / avg_atr_p if avg_atr_p > 0 else 1.0
        is_boring = vc < 0.75 and ac < 0.8
        score = self.calculate_boring_alert_score(vc, ac, window)
        return {"detected": is_boring, "score": score, "vol_contraction": round(vc, 2), "atr_contraction": round(ac, 2), "duration": window, "high_alert": score >= 85}

    def calculate_boring_alert_score(self, vc, ac, dur) -> int:
        score = 0
        if vc < 0.5: score += 40
        elif vc < 0.7: score += 30
        elif vc < 0.85: score += 15
        if ac < 0.6: score += 40
        elif ac < 0.75: score += 30
        elif ac < 0.9: score += 15
        if dur >= 20: score += 20
        elif dur >= 10: score += 15
        elif dur >= 5: score += 10
        return score
