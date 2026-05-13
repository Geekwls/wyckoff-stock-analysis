import pandas as pd
import numpy as np
import logging
from typing import Dict, List
from .base_detector import BaseDetector, USE_VECTORIZED

logger = logging.getLogger(__name__)

class MengReversalDetector(BaseDetector):
    """
    孟洪涛增强型反转检测器
    (Enhanced Spring)
    """
    def __init__(self, data: pd.DataFrame, config, thresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect_spring_enhanced(self) -> Dict:
        """孟洪涛增强版 Spring 检测"""
        if USE_VECTORIZED:
            try:
                return self._detect_spring_enhanced_vectorized()
            except Exception as e:
                logger.warning(f"Vectorized Spring failed: {e}. Falling back to iterative method.")
                return self._detect_spring_enhanced_iterative()
        return self._detect_spring_enhanced_iterative()

    def _detect_spring_enhanced_vectorized(self) -> Dict:
        if self.data is None or len(self.data) < 20:
            return {"detected": False, "reason": "insufficient_data"}

        df = self.data.copy()
        atr_series = self._calculate_atr_series(df, 14)
        last_close = df['Close'].iloc[-1]
        atr_pct = (atr_series.iloc[-1] / last_close * 100) if last_close > 0 else 0

        # 🔧 修复#1: 收回天数逻辑优化 - 根据波动率动态调整
        # 孟洪涛理论：低波动 1-3 天，中等波动 2-4 天，高波动 3-5 天
        if atr_pct < 1.5:
            max_recovery_days = 3  # 低波动：最多 3 天
        elif atr_pct < 3.0:
            max_recovery_days = 4  # 中等波动：最多 4 天
        else:
            max_recovery_days = 5  # 高波动：最多 5 天
        
        lows, closes, highs, opens, volumes = df['Low'].values, df['Close'].values, df['High'].values, df['Open'].values, df['Volume'].values
        support_levels = df['Low'].rolling(window=20).min().shift(1).values
        
        safe_support = np.where(support_levels > 1e-9, support_levels, 1.0)
        breakdown_pcts = (safe_support - lows) / safe_support * 100
        t = self.thresholds
        
        # 🔧 修复#1: 跌破幅度根据波动率动态调整
        # 低波动：1-3%，中等波动：1-4%，高波动：1-6%
        dynamic_max_breakdown = 3.0 if atr_pct < 1.5 else 4.0 if atr_pct < 3.0 else 6.0
        valid_breakdown = (lows < support_levels) & (breakdown_pcts >= t.MENG_SPRING_BREAKDOWN_MIN) & (breakdown_pcts <= dynamic_max_breakdown)
        valid_breakdown[:20], valid_breakdown[-5:] = False, False

        breakdown_indices = np.where(valid_breakdown)[0]
        signals, n = [], len(df)
        
        for i in breakdown_indices:
            support_level, breakdown_price, breakdown_vol, breakdown_pct = support_levels[i], lows[i], volumes[i], breakdown_pcts[i]
            for j in range(i + 1, min(i + max_recovery_days + 1, n)):
                if closes[j] > support_level:
                    recovery_days, recovery_vol = j - i, volumes[j]
                    # 🔧 修复#2: 成交量比较逻辑 - 量比阈值提高到 1.2
                    vol_ratio = recovery_vol / breakdown_vol if breakdown_vol > 0 else 1.0
                    if vol_ratio < 1.2: continue  # 孟洪涛要求：收回时成交量必须明显放大（>1.2 倍）
                    daily_range = highs[j] - lows[j]
                    close_position = (closes[j] - lows[j]) / daily_range if daily_range > 0 else 0.5
                    if close_position < 0.7: continue
                    signals.append(self._build_spring_signal(df.index[j], breakdown_price, support_level, closes[j], recovery_days, vol_ratio, close_position, breakdown_pct))
                    break
                    
        if not signals: return {"detected": False, "reason": "no_valid_spring_found"}
        latest_spring = signals[-1]
        latest_spring["confidence"] = round(latest_spring["confidence"], 2)
        return {"detected": True, "signals": signals, "latest_spring": latest_spring, "method": "meng_hongtao_5_filters_vectorized", "description": "孟洪涛5重过滤Spring检测"}

    def _detect_spring_enhanced_iterative(self) -> Dict:
        if self.data is None or len(self.data) < 20: return {"detected": False, "reason": "insufficient_data"}
        df, signals = self.data.copy(), []
        atr_series = self._calculate_atr_series(df, 14)
        atr_pct = (atr_series.iloc[-1] / df['Close'].iloc[-1] * 100) if df['Close'].iloc[-1] > 0 else 0
        max_recovery_days = 5 if atr_pct < 1.5 else 3 if atr_pct < 3 else 2
        t = self.thresholds
        for i in range(20, len(df) - 5):
            support_level = df['Low'].iloc[i-20:i].min()
            if df['Low'].iloc[i] < support_level:
                breakdown_price, breakdown_vol = df['Low'].iloc[i], df['Volume'].iloc[i]
                breakdown_pct = (support_level - breakdown_price) / support_level * 100
                if not (t.MENG_SPRING_BREAKDOWN_MIN <= breakdown_pct <= t.MENG_SPRING_BREAKDOWN_MAX): continue
                for j in range(i+1, min(i+max_recovery_days+1, len(df))):
                    if df['Close'].iloc[j] > support_level:
                        vol_ratio = df['Volume'].iloc[j] / breakdown_vol if breakdown_vol > 0 else 1
                        if vol_ratio < t.MENG_SPRING_VOL_RATIO: continue
                        daily_range = df['High'].iloc[j] - df['Low'].iloc[j]
                        close_position = (df['Close'].iloc[j] - df['Low'].iloc[j]) / daily_range if daily_range > 0 else 0.5
                        if close_position < t.MENG_SPRING_RECOVERY_CLOSE_POS: continue
                        signals.append(self._build_spring_signal(df.index[j], breakdown_price, support_level, df['Close'].iloc[j], j - i, vol_ratio, close_position, breakdown_pct))
                        break
        if not signals: return {"detected": False, "reason": "no_valid_spring_found"}
        latest_spring = signals[-1]
        latest_spring["confidence"] = round(latest_spring["confidence"], 2)
        return {"detected": True, "signals": signals, "latest_spring": latest_spring, "method": "meng_hongtao_5_filters", "description": "孟洪涛5重过滤Spring检测"}

    def _build_spring_signal(self, idx, breakdown_price, support_level, close_price, recovery_days, vol_ratio, close_position, breakdown_pct) -> dict:
        return {
            "date": idx, "breakdown_price": float(breakdown_price), "support_level": float(support_level),
            "recovery_price": float(close_price), "recovery_days": int(recovery_days), "vol_ratio": round(float(vol_ratio), 2),
            "close_position": round(float(close_position) * 100, 1),
            "confidence": self._calculate_spring_confidence(breakdown_pct, recovery_days, vol_ratio, close_position)
        }

    def _calculate_spring_confidence(self, breakdown_pct, recovery_days, vol_ratio, close_position):
        """
        🔧 修复#3: 置信度评分系统优化 - 细化各维度评分档位
        
        孟洪涛理论权重：
        - 跌破幅度：1-3%最优（25 分），1-5%可接受（20 分）
        - 收回天数：1-2 天最优（25 分），3-4 天次之（20 分），5 天再次（15 分）
        - 成交量：>2.0 倍最优（25 分），>1.5 倍次之（20 分），>1.2 倍再次（15 分）
        - 收盘位置：>80%最优（25 分），>70%次之（20 分），>60%再次（15 分）
        """
        score = 0
        
        # 跌破幅度评分（最优 1.5-2.5%）
        if 1.5 <= breakdown_pct <= 2.5:
            score += 25
        elif 1.0 <= breakdown_pct <= 3.0:
            score += 20
        elif 3.0 < breakdown_pct <= 5.0:
            score += 15  # 高波动市场可接受
        
        # 收回天数评分（最优 1-2 天）
        if recovery_days in [1, 2]:
            score += 25
        elif recovery_days in [3, 4]:
            score += 20
        elif recovery_days == 5:
            score += 15
        
        # 成交量评分（最优>2.0 倍）
        if vol_ratio >= 2.0:
            score += 25
        elif vol_ratio >= 1.5:
            score += 20
        elif vol_ratio >= 1.2:
            score += 15
        # <1.2 不得分（不符合孟洪涛要求）
        
        # 收盘位置评分（最优>80%）
        if close_position >= 80:
            score += 25
        elif close_position >= 70:
            score += 20
        elif close_position >= 60:
            score += 15
        # <60% 不得分（不符合孟洪涛要求）
        
        return score
