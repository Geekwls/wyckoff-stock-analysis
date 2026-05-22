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

        #  修复#1: 收回天数逻辑优化 - 根据波动率动态调整
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
        
        #  修复#1: 跌破幅度根据波动率动态调整
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
                    #  修复#2: 成交量比较逻辑 - 量比阈值提高到 1.2
                    vol_ratio = recovery_vol / breakdown_vol if breakdown_vol > 0 else 1.0
                    if vol_ratio < 1.2: continue  # 孟洪涛要求：收回时成交量必须明显放大（>1.2 倍）
                    
                    # 计算收回日收盘在日内振幅中的位置 (0=最低, 1=最高)
                    bar_range = highs[j] - lows[j]
                    close_position = (closes[j] - lows[j]) / bar_range if bar_range > 0 else 0.5
                    
                    # 孟洪涛5重过滤：收回价格必须收在日内K线的高位（默认前70%）
                    if close_position < t.MENG_SPRING_RECOVERY_CLOSE_POS:
                        continue
                    
                    # 新增：收回速率量化 (Velocity of Recovery)
                    breakdown_velocity = support_level - breakdown_price
                    recovery_velocity = (closes[j] - breakdown_price) / recovery_days
                    is_high_speed = (recovery_velocity > breakdown_velocity * 1.5) and (close_position > 0.7)

                    # 获取均量用于分类 (Type 1/2/3)
                    v_ma = vol_ma20_s[i] if 'vol_ma20_s' in locals() else (df['Volume'].rolling(20).mean().values[i] if i >= 20 else breakdown_vol)
                    
                    signal = self._build_spring_signal(
                        df.index[j], breakdown_price, support_level, closes[j], 
                        recovery_days, vol_ratio, close_position, breakdown_pct,
                        recovery_velocity, breakdown_velocity, is_high_speed,
                        breakdown_vol, v_ma, float(highs[j])
                    )
                    self._track_spring_status(signal)
                    signals.append(signal)
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
        # 与向量化路径保持一致：波动率越高，允许的收回窗口越长
        max_recovery_days = 3 if atr_pct < 1.5 else 4 if atr_pct < 3.0 else 5
        t = self.thresholds
        for i in range(20, len(df) - 5):
            support_level = df['Low'].iloc[i-20:i].min()
            if df['Low'].iloc[i] < support_level:
                breakdown_price, breakdown_vol = df['Low'].iloc[i], df['Volume'].iloc[i]
                breakdown_pct = (support_level - breakdown_price) / support_level * 100
                dynamic_max_breakdown = 3.0 if atr_pct < 1.5 else 4.0 if atr_pct < 3.0 else 6.0
                if not (t.MENG_SPRING_BREAKDOWN_MIN <= breakdown_pct <= dynamic_max_breakdown): continue
                for j in range(i+1, min(i+max_recovery_days+1, len(df))):
                    if df['Close'].iloc[j] > support_level:
                        vol_ratio = df['Volume'].iloc[j] / breakdown_vol if breakdown_vol > 0 else 1
                        if vol_ratio < t.MENG_SPRING_VOL_RATIO: continue
                        
                        # 计算收回日收盘在日内振幅中的位置 (0=最低, 1=最高)
                        bar_range = df['High'].iloc[j] - df['Low'].iloc[j]
                        close_position = (df['Close'].iloc[j] - df['Low'].iloc[j]) / bar_range if bar_range > 0 else 0.5
                        
                        # 孟洪涛5重过滤：收回价格必须收在日内K线的高位（默认前70%）
                        if close_position < t.MENG_SPRING_RECOVERY_CLOSE_POS:
                            continue
                        
                        # 收回速率量化
                        breakdown_velocity = support_level - breakdown_price
                        recovery_velocity = (df['Close'].iloc[j] - breakdown_price) / (j - i)
                        is_high_speed = (recovery_velocity > breakdown_velocity * 1.5) and (close_position > 0.7)

                        # 获取均量用于分类
                        v_ma = df['Volume'].rolling(20).mean().iloc[i] if i >= 20 else breakdown_vol
                        
                        signal = self._build_spring_signal(
                            df.index[j], breakdown_price, support_level, df['Close'].iloc[j], 
                            j - i, vol_ratio, close_position, breakdown_pct,
                            recovery_velocity, breakdown_velocity, is_high_speed,
                            breakdown_vol, v_ma, float(df['High'].iloc[j])
                        )
                        self._track_spring_status(signal)
                        signals.append(signal)
                        break
        if not signals: return {"detected": False, "reason": "no_valid_spring_found"}
        latest_spring = signals[-1]
        latest_spring["confidence"] = round(latest_spring["confidence"], 2)
        return {"detected": True, "signals": signals, "latest_spring": latest_spring, "method": "meng_hongtao_5_filters", "description": "孟洪涛5重过滤Spring检测"}

    def _build_spring_signal(self, idx, breakdown_price, support_level, close_price, recovery_days, vol_ratio, close_position, breakdown_pct, recovery_vel=0, breakdown_vel=0, is_high_speed=False, b_vol=0, v_ma=0, recovery_high=0) -> dict:
        # 分类逻辑 (P0: 1-3 号模型)
        vol_to_ma = b_vol / v_ma if v_ma > 0 else 1.0
        if vol_to_ma > 1.5:
            s_type, s_note = 1, "1号 Spring (终极震仓): 跌破时放量，反映恐慌盘涌出。需等待二次测试确认。"
        elif vol_to_ma < 0.8:
            s_type, s_note = 3, "3号 Spring (卖压枯竭): 跌破时极度缩量。反映供应已耗尽，是最强反转信号。"
        else:
            s_type, s_note = 2, "2号 Spring (普通测试): 正常成交量跌破。需结合后续反弹强度判断。"
            
        confidence = self._calculate_spring_confidence(breakdown_pct, recovery_days, vol_ratio, close_position, is_high_speed, s_type)
        return {
            "date": idx, "breakdown_price": float(breakdown_price), "support_level": float(support_level),
            "recovery_price": float(close_price), "recovery_days": int(recovery_days), "vol_ratio": round(float(vol_ratio), 2),
            "close_position": round(float(close_position) * 100, 1),
            "recovery_velocity": round(float(recovery_vel), 4),
            "breakdown_velocity": round(float(breakdown_vel), 4),
            "is_high_speed_recovery": bool(is_high_speed),
            "spring_type": s_type,
            "type_description": s_note,
            "recovery_high": float(recovery_high),
            "confidence": confidence
        }

    def _track_spring_status(self, signal: dict):
        """
        跟踪 Spring 状态并进行生命周期管理 (P0 #1)
        理论依据：震仓后应快速恢复。若10日不创新高或深度跌破，则为失败。
        """
        df = self.data
        try:
            recovery_date = signal['date']
            recovery_idx = df.index.get_loc(recovery_date)
            recovery_high = signal.get('recovery_high', 0)
            
            # 确定观察窗口：收回日之后 10 天
            n = len(df)
            window_end = min(recovery_idx + 10, n - 1)
            
            if recovery_idx >= n - 1:
                signal['lifecycle_status'] = 'active'
                return

            window_df = df.iloc[recovery_idx + 1:window_end + 1]
            if len(window_df) == 0:
                signal['lifecycle_status'] = 'active'
                return

            # 判定失败 1: 价格跌破 Spring 最低价 3% (缓冲空间合理，避免假刺穿)
            spring_low = signal['breakdown_price']
            failure_threshold = spring_low * 0.97
            min_low = window_df['Low'].min()
            
            if min_low < failure_threshold:
                signal['lifecycle_status'] = 'failed'
                signal['failure_reason'] = f"价格跌破 Spring 低位 3% ({min_low:.2f} < {failure_threshold:.2f})"
                return

            # 判定失败 2: 10 天内未突破收回日高点 (需求跟进不足)
            max_high = window_df['High'].max()
            if len(window_df) >= 10 and max_high < recovery_high:
                signal['lifecycle_status'] = 'failed'
                signal['failure_reason'] = f"10日内未能突破收回日高点 ({recovery_high:.2f})"
                return

            # 判定成功：价格突破收回日高点
            if max_high >= recovery_high:
                signal['lifecycle_status'] = 'confirmed'
                return

            signal['lifecycle_status'] = 'active'
        except Exception:
            signal['lifecycle_status'] = 'active'

    def detect_upthrust_enhanced(self) -> Dict:
        """孟洪涛增强版 Upthrust 检测"""
        if self.data is None or len(self.data) < 20: return {"detected": False, "reason": "insufficient_data"}
        df = self.data.copy()
        atr_series = self._calculate_atr_series(df, 14)
        atr_pct = (atr_series.iloc[-1] / df['Close'].iloc[-1] * 100) if df['Close'].iloc[-1] > 0 else 0
        
        # 动态调整参数
        max_rejection_days = 3 if atr_pct < 1.5 else 4 if atr_pct < 3.0 else 5
        dynamic_max_breakout = 3.0 if atr_pct < 1.5 else 4.0 if atr_pct < 3.0 else 6.0
        
        highs, lows, closes, volumes, opens = df['High'].values, df['Low'].values, df['Close'].values, df['Volume'].values, df['Open'].values
        resistance_levels = df['High'].rolling(window=20).max().shift(1).values
        
        signals, n = [], len(df)
        for i in range(20, n - 5):
            res_level = resistance_levels[i]
            if highs[i] > res_level:
                breakout_price, breakdown_vol = highs[i], volumes[i]
                breakout_pct = (breakout_price - res_level) / res_level * 100
                if not (0.5 <= breakout_pct <= dynamic_max_breakout): continue
                
                for j in range(i + 1, min(i + max_rejection_days + 1, n)):
                    if closes[j] < res_level:
                        rejection_days, rejection_vol = j - i, volumes[j]
                        vol_ratio = rejection_vol / breakdown_vol if breakdown_vol > 0 else 1.0
                        if vol_ratio < 1.2: continue
                        
                        daily_range = highs[j] - lows[j]
                        # 收盘位置：(High - Close) / Range -> 越靠近低位越好
                        close_position = (highs[j] - closes[j]) / daily_range if daily_range > 0 else 0.5
                        if close_position < 0.7: continue
                        
                        # 速率量化 (Symmetry with Spring)
                        breakout_velocity = breakout_price - res_level
                        rejection_velocity = (breakout_price - closes[j]) / rejection_days
                        is_high_speed = (rejection_velocity > breakout_velocity * 1.5) and (close_position > 0.7)
                        
                        # 分类逻辑 (P0: 1-3 号模型)
                        v_ma = volumes[i-20:i].mean() if i >= 20 else volumes[i]
                        vol_to_ma = breakdown_vol / v_ma if v_ma > 0 else 1.0
                        if vol_to_ma > 1.5:
                            ut_type, ut_note = 1, "1号 Upthrust (疯狂派发): 突破时放量，反映散户在狂热中接盘。需等待二次测试。"
                        elif vol_to_ma < 0.8:
                            ut_type, ut_note = 3, "3号 Upthrust (需求耗尽): 突破时极度缩量。反映买盘已枯竭，极度看空信号。"
                        else:
                            ut_type, ut_note = 2, "2号 Upthrust (普通测试): 正常成交量突破。"

                        confidence = self._calculate_upthrust_confidence(breakout_pct, rejection_days, vol_ratio, close_position, is_high_speed, ut_type)
                        signals.append({
                            "date": df.index[j], "breakout_price": float(breakout_price), "resistance_level": float(res_level),
                            "rejection_price": float(closes[j]), "rejection_days": int(rejection_days), "vol_ratio": round(float(vol_ratio), 2),
                            "close_position": round(float(close_position) * 100, 1),
                            "rejection_velocity": round(float(rejection_velocity), 4),
                            "breakout_velocity": round(float(breakout_velocity), 4),
                            "is_high_speed_rejection": bool(is_high_speed),
                            "upthrust_type": ut_type,
                            "type_description": ut_note,
                            "confidence": confidence
                        })
                        break
        
        if not signals: return {"detected": False, "reason": "no_valid_upthrust_found"}
        latest_ut = signals[-1]
        latest_ut["confidence"] = round(latest_ut["confidence"], 2)
        return {"detected": True, "signals": signals, "latest_upthrust": latest_ut, "method": "meng_hongtao_upthrust", "description": "孟洪涛增强版Upthrust检测"}

    def _calculate_upthrust_confidence(self, breakout_pct, rejection_days, vol_ratio, close_position, is_high_speed, ut_type=2):
        score = 0
        if 1.0 <= breakout_pct <= 3.0: score += 25
        elif 0.5 <= breakout_pct <= 5.0: score += 15
        if rejection_days in [1, 2]: score += 25
        elif rejection_days in [3, 4]: score += 20
        if vol_ratio >= 1.5: score += 25
        elif vol_ratio >= 1.2: score += 15
        if close_position >= 0.8: score += 25
        elif close_position >= 0.7: score += 15
        if is_high_speed: score += 15
        else: score -= 10
        
        # 类型加权
        if ut_type == 3: score += 10 # 3号最强
        elif ut_type == 1: score -= 5 # 1号需等待测试
        
        return max(0, min(100, score))

    def _calculate_spring_confidence(self, breakdown_pct, recovery_days, vol_ratio, close_position, is_high_speed, s_type=2):
        """
        🔧 修复#3: 置信度评分系统优化 - 细化各维度评分档位并加入速率加权
        
        孟洪涛理论权重：
        - 跌破幅度：1-3%最优（25 分）
        - 收回天数：1-2 天最优（25 分）
        - 成交量：>2.0 倍最优（25 分）
        - 收盘位置：>80%最优（25 分）
        - 收回速率：高速收回（额外 +15 分），低速收回（-10 分）
        - 分类加权：3号 (最强) +10分，1号 (需测试) -5分
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
        
        # 收盘位置评分（最优>80%）
        if close_position >= 80:
            score += 25
        elif close_position >= 70:
            score += 20
        elif close_position >= 60:
            score += 15
        
        # 收回速率评分 (P0 优化)
        if is_high_speed:
            score += 15
        else:
            score -= 10
        
        # 类型加权
        if s_type == 3: score += 10
        elif s_type == 1: score -= 5
            
        return max(0, min(100, score))

    def detect_choch(self) -> Dict:
        """
        检测特征变异 (Change of Character, CHoCH)
        理论依据：趋势中第一个显著的反向波段，量能和价差均超过前期水平。
        """
        if self.data is None or len(self.data) < 30:
            return {"detected": False}
            
        # 简化逻辑：最近 5 天的波动率 vs 20 天波动率
        df = self.data.tail(30).copy()
        recent = df.tail(5)
        
        # 计算最高价差
        recent_range = (recent['High'] - recent['Low']).max()
        avg_range = (df['High'] - df['Low']).mean()
        
        # 计算最高成交量
        recent_vol = recent['Volume'].max()
        avg_vol = df['Volume'].mean()
        
        # 必须是反向动作（例如在下跌趋势中出现大阳线，或上涨趋势中出现大阴线）
        # 这里简单通过价格相对于均线的位置判断
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        current_price = df['Close'].iloc[-1]
        
        # 如果最近出现了超大波幅且超量
        if recent_range > avg_range * 1.8 and recent_vol > avg_vol * 1.5:
            # 进一步判断性质
            is_bullish_choch = (recent['Close'] > recent['Open']).sum() >= 3 and current_price > ma20
            is_bearish_choch = (recent['Close'] < recent['Open']).sum() >= 3 and current_price < ma20
            
            if is_bullish_choch or is_bearish_choch:
                return {
                    "detected": True,
                    "date": recent.index[-1].strftime('%Y-%m-%d') if hasattr(recent.index[-1], 'strftime') else str(recent.index[-1]),
                    "type": "CHoCH",
                    "direction": "bullish" if is_bullish_choch else "bearish",
                    "intensity": round(float(recent_range / avg_range), 2),
                    "vol_intensity": round(float(recent_vol / avg_vol), 2),
                    "interpretation": "特征变异：波幅与量能显著放大，提示原趋势动力衰竭，进入盘整或反转期"
                }
            
        return {"detected": False}

