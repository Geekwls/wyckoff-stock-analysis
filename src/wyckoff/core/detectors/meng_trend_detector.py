import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional
from .base_detector import BaseDetector, USE_VECTORIZED

logger = logging.getLogger(__name__)

class MengTrendDetector(BaseDetector):
    """
    孟洪涛增强型趋势检测器
    (Enhanced JOC, Dead Corner Breakout)
    """
    def __init__(self, data: pd.DataFrame, config, thresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect_joc_enhanced(self) -> Dict:
        """孟洪涛增强版 JOC 检测"""
        if USE_VECTORIZED:
            try: return self._detect_joc_enhanced_vectorized()
            except Exception as e:
                logger.warning(f"Vectorized JOC failed: {e}. Falling back to iterative method.")
                return self._detect_joc_enhanced_iterative()
        return self._detect_joc_enhanced_iterative()

    def _detect_joc_enhanced_vectorized(self) -> Dict:
        if self.data is None or len(self.data) < 40: return {"detected": False, "reason": "insufficient_data"}
        df = self.data.copy()
        tr = self._detect_trading_range(df, window=60)
        if not tr.get("is_consolidation"): return {"detected": False, "reason": "not_in_consolidation"}
        creek_level = tr["high"]
        vol_ma20_s = df['Volume_MA20'].values if 'Volume_MA20' in df.columns else df['Volume'].rolling(20, min_periods=1).mean().values
        vol_ma20 = vol_ma20_s[-1]
        closes, opens, highs, lows, volumes = df['Close'].values, df['Open'].values, df['High'].values, df['Low'].values, df['Volume'].values
        prev_closes = np.roll(closes, 1)
        prev_closes[0] = closes[0]
        is_breakout = (closes > creek_level) & (prev_closes <= creek_level)
        is_breakout[:20] = False
        safe_opens = np.where(np.abs(opens) > 1e-9, opens, 1.0)
        price_changes = (closes - opens) / safe_opens * 100
        volume_ratios = np.where(vol_ma20 > 0, volumes / vol_ma20, 1.0)
        daily_ranges = highs - lows
        close_positions = np.where(daily_ranges > 0, (closes - lows) / daily_ranges, 0.5)
        
        # 🔧 修复#4: 突破力度标准从 3% 提高到 5%（孟洪涛要求长阳线）
        valid_joc = is_breakout & (price_changes >= 5) & (volume_ratios >= 1.5) & (close_positions >= 0.75)
        indices = np.where(valid_joc)[0]
        signals, n = [], len(df)
        for i in indices:
            test_detected, test_date, test_vol_ratio = False, None, None
            end = min(i + 11, n)
            if end > i + 1:
                t_lows, t_closes, t_vols = lows[i+1:end], closes[i+1:end], volumes[i+1:end]
                # 🔧 修复#5: 回测检测逻辑优化 - 允许短暂跌破后收回
                # 孟洪涛理论：回测可以短暂跌破小溪，只要快速收回即可
                hits = (t_lows < creek_level * 1.02) & ((t_vols / vol_ma20) < 1.0 if vol_ma20 > 0 else False)
                hit_idx = np.where(hits)[0]
                if len(hit_idx) > 0:
                    fh = hit_idx[0] + i + 1
                    test_detected, test_date, test_vol_ratio = True, df.index[fh], float(volumes[fh] / vol_ma20) if vol_ma20 > 0 else 1.0
            signals.append({
                "date": df.index[i], "creek_level": float(creek_level), "close_price": float(closes[i]), "breakout_pct": round(float(price_changes[i]), 2),
                "volume_ratio": round(float(volume_ratios[i]), 2), "close_position": round(float(close_positions[i]) * 100, 1),
                "test_detected": test_detected, "test_date": test_date, "test_vol_ratio": round(test_vol_ratio, 2) if test_vol_ratio else None,
                "confidence": self._calculate_joc_confidence(price_changes[i], volume_ratios[i], close_positions[i], test_detected)
            })
        if not signals: return {"detected": False, "reason": "no_valid_joc_found"}
        ls = signals[-1]
        ls["confidence"] = round(ls["confidence"], 2)
        return {"detected": True, "signals": signals, "latest": ls, "method": "meng_hongtao_joc_vectorized", "description": "孟洪涛JOC检测"}

    def _detect_joc_enhanced_iterative(self) -> Dict:
        if self.data is None or len(self.data) < 40: return {"detected": False, "reason": "insufficient_data"}
        df = self.data.copy()
        tr = self._detect_trading_range(df, window=60)
        if not tr.get("is_consolidation"): return {"detected": False, "reason": "not_in_consolidation"}
        creek_level, vol_ma20 = tr["high"], df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]
        signals = []
        for i in range(20, len(df)):
            if df['Close'].iloc[i] > creek_level and df['Close'].iloc[i-1] <= creek_level:
                price_change = (df['Close'].iloc[i] - df['Open'].iloc[i]) / df['Open'].iloc[i] * 100
                # 🔧 修复#4: 突破力度标准从 3% 提高到 5%
                if price_change < 5: continue
                vol_ratio = df['Volume'].iloc[i] / vol_ma20 if vol_ma20 > 0 else 1
                if vol_ratio < 1.5: continue
                daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
                close_pos = (df['Close'].iloc[i] - df['Low'].iloc[i]) / daily_range if daily_range > 0 else 0.5
                if close_pos < 0.75: continue
                td, tdt, tvr = False, None, None
                for j in range(i+1, min(i+10, len(df))):
                    # 🔧 修复#5: 回测检测逻辑优化 - 允许短暂跌破后收回
                    if df['Low'].iloc[j] < creek_level * 1.02:
                        tvr_curr = df['Volume'].iloc[j] / vol_ma20 if vol_ma20 > 0 else 1
                        if tvr_curr < 1.0:
                            td, tdt, tvr = True, df.index[j], tvr_curr
                            break
                signals.append({
                    "date": df.index[i], "creek_level": creek_level, "close_price": df['Close'].iloc[i], "breakout_pct": round(price_change, 2),
                    "volume_ratio": round(vol_ratio, 2), "close_position": round(close_pos * 100, 1), "test_detected": td, "test_date": tdt,
                    "test_vol_ratio": round(tvr, 2) if tvr else None, "confidence": self._calculate_joc_confidence(price_change, vol_ratio, close_pos, td)
                })
        if not signals: return {"detected": False, "reason": "no_valid_joc_found"}
        ls = signals[-1]
        ls["confidence"] = round(ls["confidence"], 2)
        return {"detected": True, "signals": signals, "latest": ls, "method": "meng_hongtao_joc", "description": "孟洪涛JOC检测"}

    def _calculate_joc_confidence(self, breakout_pct, volume_ratio, close_position, has_test):
        score = 0
        if breakout_pct >= 5: score += 25
        elif breakout_pct >= 3: score += 20
        if volume_ratio >= 2.5: score += 25
        elif volume_ratio >= 2.0: score += 20
        elif volume_ratio >= 1.5: score += 15
        if close_position >= 0.9: score += 25
        elif close_position >= 0.8: score += 20
        elif close_position >= 0.75: score += 15
        if has_test: score += 25
        return score

    def detect_dead_corner_breakout(self, vsa_detector=None) -> Dict:
        """检测死角突破"""
        if not vsa_detector: return {"detected": False, "reason": "vsa_detector_required"}
        boring_res = vsa_detector.detect_boring_zone(window=10)
        if not boring_res.get("detected") and boring_res.get("score", 0) < 85:
            return {"detected": False, "reason": "boring_score_too_low", "boring_zone": boring_res, "required_score": 85}
        if self.data is None or len(self.data) < 20: return {"detected": False, "reason": "insufficient_data"}
        df = self.data.tail(20).copy()
        boring_high = df['High'].iloc[-10:-1].max()
        vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
        bf, b_idx, b_bar = False, None, None
        for i in range(len(df) - 1, -1, -1):
            if df['Volume'].iloc[i] > vol_ma20 * 2.0 and df['Close'].iloc[i] > boring_high:
                bf, b_idx, b_bar = True, i, df.iloc[i]
                break
        if not bf or b_bar is None: return {"detected": False, "reason": "no_breakout_found", "boring_zone": boring_res}
        ft_conf, max_pb = False, 0
        if b_idx < len(df) - 1:
            for j in range(1, min(3, len(df) - b_idx - 1) + 1):
                f_bar = df.iloc[b_idx + j]
                max_pb = max(max_pb, (b_bar['Close'] - f_bar['Low']) / b_bar['Close'])
                if f_bar['Close'] > b_bar['Close']:
                    ft_conf = True
                    break
        conf_factors = {'boring': boring_res.get('score', 0) / 100, 'vol': min(b_bar['Volume'] / vol_ma20 / 3, 1), 'ft': 1.0 if ft_conf else 0.5, 'pb': max(0, 1 - max_pb * 10)}
        conf = conf_factors['boring'] * 0.3 + conf_factors['vol'] * 0.3 + conf_factors['ft'] * 0.25 + conf_factors['pb'] * 0.15
        if not (bf and conf > 0.6): return {"detected": False, "reason": "confidence_too_low", "confidence": round(conf * 100, 1)}
        return {
            "detected": True, "boring_zone": boring_res, "breakout_price": round(float(b_bar['Close']), 2),
            "breakout_volume_ratio": round(float(b_bar['Volume']) / vol_ma20, 2), "breakout_date": df.index[b_idx],
            "follow_through_confirmation": ft_conf, "max_pullback_pct": round(max_pb * 100, 2), "confidence": round(min(conf * 100, 100), 1),
            "description": f'🎯 死角突破!枯燥区{boring_res["score"]}分后的{"强势" if ft_conf else "弱势"}突破'
        }

    def detect_dead_corner_breakout_enhanced(self, vsa_detector=None) -> Dict:
        base = self.detect_dead_corner_breakout(vsa_detector)
        if not base.get("detected"): return base
        strength = self._classify_breakout_strength(base)
        base.update({"breakout_strength": strength, "trading_advice": self._generate_breakout_trading_advice(base, strength)})
        return base

    def _classify_breakout_strength(self, res: Dict) -> str:
        conf, vol_r, ft = res.get("confidence", 0), res.get("breakout_volume_ratio", 0), res.get("follow_through_confirmation", False)
        if conf >= 85 and vol_r >= 2.5 and ft: return "SUPER_STRONG"
        if conf >= 75 and vol_r >= 2.0: return "STRONG"
        if conf >= 65: return "MODERATE"
        return "WEAK"

    def _generate_breakout_trading_advice(self, res: Dict, strength: str) -> Dict:
        bp = res.get("breakout_price", 0)
        if strength == "SUPER_STRONG": return {"action": "STRONG_BUY", "entry": "激进追涨", "sl": round(bp * 0.98, 2), "target": f"{round(bp*1.1, 2)}/{round(bp*1.2, 2)}"}
        if strength == "STRONG": return {"action": "BUY", "entry": "稳健做多", "sl": round(bp * 0.97, 2), "target": f"{round(bp*1.08, 2)}/{round(bp*1.15, 2)}"}
        return {"action": "WATCH", "entry": "观望等待"}
