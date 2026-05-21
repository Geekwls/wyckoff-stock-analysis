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

    def _calculate_adaptive_creek(self, df: pd.DataFrame, window: int = 60) -> float:
        """
        自适应计算 Creek（小溪阻力线）- 孟洪涛原则升级版
        
        算法步骤：
        1. 识别 window（默认60）内所有的 Swing High（局部高点）
           局部高点定义：过去 5 天（包含前后 2 天）内的最高点
        2. 如果 Swing High 数量不足 2，则回退到绝对最高价作为 Creek
        3. 对识别到的所有 Swing High，按其对应的成交量 Volume 进行降序排列
        4. 安全过滤（用户高价值建议）：
           计算最近 14 天的 ATR（若异常则使用收盘价的 2% 代替）。
           以成交量最大的那个高点价格作为核心基准价 base_price。
           过滤前 3 个候选高点，剔除与 base_price 偏离超过 1.5 * ATR 的离散高点。
        5. 对过滤后的剩余高点求均值，作为自适应 Creek 颈线。
        """
        if df is None or len(df) < 10:
            return df['High'].max() if (df is not None and len(df) > 0) else 0.0
            
        recent_df = df.tail(window)
        highs = recent_df['High'].values
        volumes = recent_df['Volume'].values
        
        swing_highs = []
        n = len(highs)
        
        # 寻找局部 Swing High (在过去 2 天和未来 2 天中是最高点)
        for i in range(2, n - 2):
            if (highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and
                highs[i] >= highs[i+1] and highs[i] >= highs[i+2]):
                swing_highs.append((highs[i], volumes[i]))
                
        if len(swing_highs) < 2:
            return float(recent_df['High'].max())
            
        # 按成交量降序排列
        swing_highs.sort(key=lambda x: x[1], reverse=True)
        
        # 核心成交量最大的阻力位基准
        base_price, base_vol = swing_highs[0]
        
        # 计算 ATR 波动率度量
        atr_series = self._calculate_atr_series(df, 14)
        current_atr = atr_series.iloc[-1] if len(atr_series) > 0 else np.nan
        
        # Fallback 容错
        if pd.isna(current_atr) or current_atr <= 0:
            current_atr = df['Close'].iloc[-1] * 0.02 if len(df) > 0 else 1.0
            
        # 1.5 * ATR 过滤阈值
        atr_threshold = 1.5 * current_atr
        
        # 过滤前 3 个最强量能高点，防范 Upthrust 离散噪点
        top_candidates = swing_highs[:min(3, len(swing_highs))]
        filtered_highs = [base_price]
        
        for price, vol in top_candidates[1:]:
            if abs(price - base_price) <= atr_threshold:
                filtered_highs.append(price)
                
        return float(np.mean(filtered_highs))

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
        # 🔧 升级为最终自适应聚类 Creek 颈线
        creek_level = self._calculate_adaptive_creek(df, window=60)
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

        # ── 天量突破 JOC 过载保护与买入高潮 ──
        breakout_indices = np.where(is_breakout)[0]
        if len(breakout_indices) > 0:
            latest_breakout_idx = breakout_indices[-1]
            v_ratio = volume_ratios[latest_breakout_idx]
            hl_range = highs[latest_breakout_idx] - lows[latest_breakout_idx]
            if hl_range > 0:
                shadow_ratio = (highs[latest_breakout_idx] - max(opens[latest_breakout_idx], closes[latest_breakout_idx])) / hl_range
                close_pos = (closes[latest_breakout_idx] - lows[latest_breakout_idx]) / hl_range
            else:
                shadow_ratio = 0.0
                close_pos = 0.5
                
            if v_ratio >= 3.0 and (shadow_ratio >= 0.35 or close_pos < 0.60):
                logger.warning(f"Meng JOC Vectorized Overload (Buying Climax) detected: volume ratio {v_ratio:.2f}")
                return {
                    'detected': False,
                    'joc_overload_warning': True,
                    'reason': 'joc_volume_overload_buying_climax',
                    'evidence': {
                        'date': str(df.index[latest_breakout_idx]),
                        'volume_ratio': round(float(v_ratio), 2),
                        'upper_shadow_ratio': round(float(shadow_ratio), 3),
                        'close_position': round(float(close_pos), 3)
                    }
                }

        valid_joc = (
            is_breakout
            & (price_changes >= self.thresholds.JOC_MIN_BREAKOUT_PCT)
            & (volume_ratios >= self.thresholds.JOC_VOLUME_RATIO)
            & (close_positions >= self.thresholds.JOC_CLOSE_POSITION)
        )
        indices = np.where(valid_joc)[0]
        signals, n = [], len(df)
        for i in indices:
            test_detected, test_date, test_vol_ratio = False, None, None
            end = min(i + 11, n)
            if end > i + 1:
                t_lows, t_closes, t_vols = lows[i+1:end], closes[i+1:end], volumes[i+1:end]
                #  修复#5: 回测检测逻辑优化 - 允许短暂跌破后收回
                # 孟洪涛理论：回测可以短暂跌破小溪，只要快速收回即可
                hits = (t_lows < creek_level * 1.02) & ((t_vols / vol_ma20) < 1.0 if vol_ma20 > 0 else False)
                hit_idx = np.where(hits)[0]
                if len(hit_idx) > 0:
                    fh = hit_idx[0] + i + 1
                    test_detected = True
                    test_date = df.index[fh]
                    test_vol_ratio = float(volumes[fh] / vol_ma20) if vol_ma20 > 0 else 1.0
                    
                    # 细化回测质量评分 (P0 #2)
                    prev_close = closes[fh-1] if fh > 0 else closes[fh]
                    prev_open = opens[fh-1] if fh > 0 else opens[fh]
                    prev_body_pct = abs(prev_close - prev_open) / prev_close * 100 if prev_close > 0 else 0
                    
                    t_score, t_quality = self._calculate_joc_test_quality(
                        closes[fh], opens[fh], highs[fh], lows[fh], 
                        volumes[fh], vol_ma20, creek_level, prev_body_pct
                    )
                    test_score = t_score
                    test_quality = t_quality
            signals.append({
                "date": df.index[i], "creek_level": float(creek_level), "close_price": float(closes[i]), "breakout_pct": round(float(price_changes[i]), 2),
                "volume_ratio": round(float(volume_ratios[i]), 2), "close_position": round(float(close_positions[i]) * 100, 1),
                "test_detected": test_detected, "test_date": test_date, "test_vol_ratio": round(test_vol_ratio, 2) if test_vol_ratio else None,
                "test_score": test_score if test_detected else 0,
                "test_quality": test_quality if test_detected else None,
                "confidence": self._calculate_joc_confidence(price_changes[i], volume_ratios[i], close_positions[i], test_detected, test_score if test_detected else 0)
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
        vol_ma20 = df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]

        # ── 天量突破 JOC 过载保护与买入高潮 ──
        for i in range(len(df) - 1, 19, -1):
            current_creek = self._calculate_adaptive_creek(df.iloc[:i+1], window=60)
            if df['Close'].iloc[i] > current_creek and df['Close'].iloc[i-1] <= current_creek:
                vol_ratio = df['Volume'].iloc[i] / vol_ma20 if vol_ma20 > 0 else 1.0
                hl_range = df['High'].iloc[i] - df['Low'].iloc[i]
                if hl_range > 0:
                    shadow_ratio = (df['High'].iloc[i] - max(df['Open'].iloc[i], df['Close'].iloc[i])) / hl_range
                    close_pos = (df['Close'].iloc[i] - df['Low'].iloc[i]) / hl_range
                else:
                    shadow_ratio = 0.0
                    close_pos = 0.5
                    
                if vol_ratio >= 3.0 and (shadow_ratio >= 0.35 or close_pos < 0.60):
                    logger.warning(f"Meng JOC Iterative Overload (Buying Climax) detected: volume ratio {vol_ratio:.2f}")
                    return {
                        'detected': False,
                        'joc_overload_warning': True,
                        'reason': 'joc_volume_overload_buying_climax',
                        'evidence': {
                            'date': str(df.index[i]),
                            'volume_ratio': round(float(vol_ratio), 2),
                            'upper_shadow_ratio': round(float(shadow_ratio), 3),
                            'close_position': round(float(close_pos), 3)
                        }
                    }
                break

        signals = []
        for i in range(20, len(df)):
            # 🔧 自适应计算当前时刻 i 的 Creek 阻力位
            current_creek = self._calculate_adaptive_creek(df.iloc[:i+1], window=60)
            if df['Close'].iloc[i] > current_creek and df['Close'].iloc[i-1] <= current_creek:
                price_change = (df['Close'].iloc[i] - df['Open'].iloc[i]) / df['Open'].iloc[i] * 100
                if price_change < self.thresholds.JOC_MIN_BREAKOUT_PCT: continue
                vol_ratio = df['Volume'].iloc[i] / vol_ma20 if vol_ma20 > 0 else 1
                if vol_ratio < self.thresholds.JOC_VOLUME_RATIO: continue
                daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
                close_pos = (df['Close'].iloc[i] - df['Low'].iloc[i]) / daily_range if daily_range > 0 else 0.5
                if close_pos < self.thresholds.JOC_CLOSE_POSITION: continue
                td, tdt, tvr = False, None, None
                for j in range(i+1, min(i+10, len(df))):
                    #  修复#5: 回测检测逻辑优化 - 允许短暂跌破后收回
                    if df['Low'].iloc[j] < current_creek * 1.02:
                        tvr_curr = df['Volume'].iloc[j] / vol_ma20 if vol_ma20 > 0 else 1
                        if tvr_curr < 1.0:
                            td, tdt, tvr = True, df.index[j], tvr_curr
                            break
                signals.append({
                    "date": df.index[i], "creek_level": float(current_creek), "close_price": float(df['Close'].iloc[i]), "breakout_pct": round(price_change, 2),
                    "volume_ratio": round(vol_ratio, 2), "close_position": round(close_pos * 100, 1), "test_detected": td, "test_date": tdt,
                    "test_vol_ratio": round(tvr, 2) if tvr else None, "confidence": self._calculate_joc_confidence(price_change, vol_ratio, close_pos, td)
                })
        if not signals: return {"detected": False, "reason": "no_valid_joc_found"}
        ls = signals[-1]
        ls["confidence"] = round(ls["confidence"], 2)
        return {"detected": True, "signals": signals, "latest": ls, "method": "meng_hongtao_joc", "description": "孟洪涛JOC检测"}

    def _calculate_joc_confidence(self, breakout_pct, volume_ratio, close_position, has_test, test_score=0):
        score = 0
        t = self.thresholds
        # 突破幅度评分：优秀阈值取配置值与5%的较大者
        excellent_breakout_threshold = max(t.JOC_EXCELLENT_BREAKOUT_PCT, t.JOC_MIN_BREAKOUT_PCT)
        if breakout_pct >= excellent_breakout_threshold: score += 25
        elif breakout_pct >= t.JOC_MIN_BREAKOUT_PCT: score += 20

        # 量能评分
        if volume_ratio >= t.JOC_EXCELLENT_VOLUME_RATIO: score += 25
        elif volume_ratio >= t.JOC_GOOD_VOLUME_RATIO: score += 20
        elif volume_ratio >= t.JOC_VOLUME_RATIO: score += 15

        # 收盘位置评分
        if close_position >= t.JOC_EXCELLENT_CLOSE_POSITION: score += 25
        elif close_position >= t.JOC_GOOD_CLOSE_POSITION: score += 20
        elif close_position >= t.JOC_CLOSE_POSITION: score += 15

        # 回测权重提升
        if has_test:
            score += 25
            if test_score >= 80: score += 10  # 高质量回测额外加分

        return min(100, score)

    def _calculate_joc_test_quality(self, close, open, high, low, vol, vol_ma20, creek_level, prev_body_pct=None):
        """
        计算 JOC 回测质量评分 (P0 #2)
        评分维度：成交量(40)、价格行为(40)、位置(20)、下影线(奖励5)
        """
        score = 0
        
        # 1. 成交量评分 (40分)
        vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 1.0
        if vol_ratio < 0.6: score += 40
        elif vol_ratio < 0.8: score += 30
        elif vol_ratio < 1.0: score += 20
        
        # 2. 价格行为评分 (40分)
        body = abs(close - open)
        price = close
        body_pct = (body / price) * 100
        is_above_creek = close >= creek_level
        
        if body_pct < 1.5 and is_above_creek:
            score += 30 # 基础分
            # 实体趋势检测与容差处理 (P0 #2)
            if prev_body_pct is not None:
                # 如果 prev_body 极小 (十字星)，允许 1.2x 容差
                is_shrinking = body_pct < prev_body_pct * 1.2 if prev_body_pct < 0.1 else body_pct < prev_body_pct
                if is_shrinking: score += 10
            else:
                score += 5 # 无前日数据给中等分
        elif body_pct < 3.0 and is_above_creek:
            score += 20
            
        # 3. 位置评分 (20分)
        # 最低价恰好触碰 Creek 或在 Creek 上方 2% 以内
        dist_to_creek = (low - creek_level) / creek_level * 100
        if 0 <= dist_to_creek <= 2.0:
            score += 20
        elif -2.0 <= dist_to_creek < 0: # 允许轻微跌破
            score += 10
            
        # 4. 下影线奖励 (5分)
        # 下影线 > 实体 * 2
        shadow = close - low if close > open else open - low
        if shadow > body * 2:
            score += 5
            
        # 等级判定
        if score >= 80: quality = "HIGH"
        elif score >= 60: quality = "MEDIUM"
        else: quality = "LOW"
        
        return score, quality

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
