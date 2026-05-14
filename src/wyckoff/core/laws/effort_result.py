import logging
from ...exceptions import InsufficientDataError

logger = logging.getLogger(__name__)


class EffortResultMixin:
    """第二定律：努力 vs 结果"""

    def analyze_effort_vs_result_law(self, market_context: dict = None) -> dict:
        if self.data is None or len(self.data) < 20:
            raise InsufficientDataError("努力vs结果分析", required=20, actual=len(self.data) if self.data is not None else 0)

        df = self.data
        market_returns = {'short': 0.0, 'medium': 0.0, 'long': 0.0}
        if market_context:
            market_returns['short'] = market_context.get('short_market_return', 0.0)
            market_returns['medium'] = market_context.get('medium_market_return', 0.0)
            market_returns['long'] = market_context.get('long_market_return', 0.0)

        # P1 修复：获取当前Phase上下文
        current_phase = self._get_current_phase_context()

        timeframes = {
            'short': {'days': 5, 'name': '短期(5日)'},
            'medium': {'days': 20, 'name': '中期(20日)'},
            'long': {'days': 60, 'name': '长期(60日)'}
        }
        effort_result_analysis = {}

        for tf_key, tf_info in timeframes.items():
            days = tf_info['days']
            if len(df) < days + 10:
                continue
            recent_df = df.tail(days)
            vol_end = recent_df['Volume'].iloc[-1]
            vol_ma_ref = df['Volume_MA20'].iloc[-1]
            volume_effort = vol_end / vol_ma_ref if vol_ma_ref > 0 else 1.0
            price_start = recent_df['Close'].iloc[0]
            price_end = recent_df['Close'].iloc[-1]
            price_result_pct = ((price_end - price_start) / price_start) * 100
            market_return = market_returns.get(tf_key, 0.0) * 100
            relative_strength = price_result_pct - market_return
            effort_magnitude = abs(volume_effort - 1.0)
            result_magnitude = abs(price_result_pct)

            if effort_magnitude > 0.5:
                if result_magnitude > 2.0:
                    if (volume_effort > 1.0 and price_result_pct > 0) or (volume_effort < 1.0 and price_result_pct < 0):
                        if relative_strength > 2:
                            interpretation = "STRONG_OUTPERFORMANCE"
                            meaning = f"强势跑赢大盘：个股{price_result_pct:.1f}% vs 大盘{market_return:.1f}%，相对强度{relative_strength:.1f}%，主力控盘能力强"
                            # P1: Phase上下文
                            meaning += self._phase_context_tail(current_phase, interpretation)
                        elif relative_strength < -2:
                            interpretation = "WEAK_UNDERPERFORMANCE"
                            meaning = f"弱势跑输大盘：个股{price_result_pct:.1f}% vs 大盘{market_return:.1f}%，相对强度{relative_strength:.1f}%，需谨慎"
                            meaning += self._phase_context_tail(current_phase, interpretation)
                        else:
                            interpretation = "CONFIRMATION"
                            meaning = f"努力与结果一致，确认当前趋势（相对强度{relative_strength:.1f}%，与大盘同步）"
                            meaning += self._phase_context_tail(current_phase, interpretation)
                    else:
                        if relative_strength > 3:
                            interpretation = "DIVERGENCE_WITH_STRENGTH"
                            meaning = f"量价背离但跑赢大盘：个股{price_result_pct:.1f}% vs 大盘{market_return:.1f}%，可能存在独立行情"
                            meaning += self._phase_context_tail(current_phase, interpretation)
                        elif relative_strength < -3:
                            interpretation = "DOUBLE_WEAKNESS"
                            meaning = f"量价背离且跑输大盘：个股{price_result_pct:.1f}% vs 大盘{market_return:.1f}%，双重警示信号"
                            meaning += self._phase_context_tail(current_phase, interpretation)
                        else:
                            interpretation = "DIVERGENCE"
                            meaning = "努力与结果背离，警示信号"
                            meaning += self._phase_context_tail(current_phase, interpretation)
                else:
                    if effort_magnitude > 0.8:
                        interpretation = "EFFORT_WITHOUT_RESULT"
                        meaning = f"大努力无结果，可能是拐点信号（相对强度{relative_strength:.1f}%）"
                        meaning += self._phase_context_tail(current_phase, interpretation)
                    else:
                        interpretation = "WEAK_CONFIRMATION"
                        meaning = f"努力与结果基本一致，但强度较弱（相对强度{relative_strength:.1f}%）"
                        meaning += self._phase_context_tail(current_phase, interpretation)
            else:
                if result_magnitude > 3.0:
                    interpretation = "RESULT_WITHOUT_EFFORT"
                    if price_result_pct > 0 and relative_strength > 3:
                        meaning = f"无量上涨但跑赢大盘{relative_strength:.1f}%，可能存在独立行情或操纵"
                    elif price_result_pct < 0 and relative_strength < -3:
                        meaning = f"无量下跌且跑输大盘{relative_strength:.1f}%，弱势特征明显"
                    else:
                        meaning = "价格变动缺乏成交量支持，需谨慎"
                    meaning += self._phase_context_tail(current_phase, interpretation)
                else:
                    interpretation = "NORMAL"
                    meaning = f"正常的量价关系（相对强度{relative_strength:.1f}%）"
                    meaning += self._phase_context_tail(current_phase, interpretation)

            effort_result_analysis[tf_key] = {
                "timeframe": tf_info['name'],
                "volume_effort": round(volume_effort, 2),
                "price_result": round(price_result_pct, 2),
                "market_return": round(market_return, 2),
                "relative_strength": round(relative_strength, 2),
                "effort_magnitude": round(effort_magnitude, 3),
                "result_magnitude": round(result_magnitude, 2),
                "interpretation": interpretation,
                "meaning": meaning,
                "phase_context": current_phase,
            }

        interpretations = [tf['interpretation'] for tf in effort_result_analysis.values()]
        if all(interp == "CONFIRMATION" for interp in interpretations):
            overall_assessment = "STRONG_CONFIRMATION"
            wyckoff_guidance = "多时间框架一致确认，趋势可靠性高"
        elif any(interp in ["DIVERGENCE", "EFFORT_WITHOUT_RESULT"] for interp in interpretations):
            overall_assessment = "WARNING_SIGNAL"
            wyckoff_guidance = "检测到努力vs结果背离，建议谨慎或等待确认"
        elif any(interp == "RESULT_WITHOUT_EFFORT" for interp in interpretations):
            overall_assessment = "WEAK_SIGNAL"
            wyckoff_guidance = "价格变动缺乏成交量支持，信号强度不足"
        else:
            overall_assessment = "NEUTRAL"
            wyckoff_guidance = "量价关系正常，无明确信号"

        volume_health = self._analyze_volume_health_context()
        follow_through = self._analyze_signal_follow_through()
        vsa_anomalies = self._detect_vsa_anomalies()

        return {
            "overall_assessment": overall_assessment,
            "wyckoff_guidance": wyckoff_guidance,
            "timeframe_analysis": effort_result_analysis,
            "volume_health": volume_health,
            "follow_through": follow_through,
            "vsa_anomalies": vsa_anomalies
        }

    def _analyze_volume_health_context(self) -> dict:
        df = self.data
        if len(df) < 25:
            return {"status": "insufficient_data"}
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        vol_ratio = curr['Volume'] / max(prev['Volume'], 1)
        prev_spread = max(prev['High'] - prev['Low'], 1e-9)
        curr_spread = max(curr['High'] - curr['Low'], 1e-9)
        spread_ratio = curr_spread / prev_spread
        evr = vol_ratio >= 1.5 and spread_ratio <= 0.8
        tr_window = df.tail(60)
        range_high = tr_window['High'].max()
        range_low = tr_window['Low'].min()
        pos = (curr['Close'] - range_low) / max(range_high - range_low, 1e-9)
        is_high_zone = pos >= 0.7
        is_low_zone = pos <= 0.3
        vol_ma20 = df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]
        shrink = curr['Volume'] < vol_ma20 * 0.85
        contraction_signal = "neutral"
        contraction_meaning = "缩量信号不明确"
        if shrink and is_high_zone:
            contraction_signal = "LPSY_RISK"
            contraction_meaning = "高位缩量上涨/横盘，需求衰竭，警惕LPSY前兆"
        elif shrink and is_low_zone:
            contraction_signal = "LPS_CANDIDATE"
            contraction_meaning = "低位缩量止跌，供应耗尽，符合LPS测试特征"
        close_pos = (curr['Close'] - curr['Low']) / max(curr['High'] - curr['Low'], 1e-9)
        high_vol = curr['Volume'] > vol_ma20 * 1.4
        candle_read = "neutral"
        if high_vol and close_pos <= 0.2:
            candle_read = "SOW_BEARISH_CLOSE"
        elif high_vol and close_pos >= 0.8:
            candle_read = "ABSORPTION_BULLISH_CLOSE"
        return {
            "status": "alert" if evr else "normal",
            "evr": {
                "detected": bool(evr),
                "label": "红色预警：停止行为" if evr else "未见显著停止行为",
                "volume_expansion_ratio": round(vol_ratio, 2),
                "spread_change_ratio": round(spread_ratio, 2)
            },
            "contraction_context": {
                "detected": bool(shrink),
                "price_position": "high" if is_high_zone else "low" if is_low_zone else "middle",
                "signal": contraction_signal,
                "meaning": contraction_meaning,
            },
            "high_volume_close_reading": {
                "close_position": round(close_pos, 2),
                "high_volume": bool(high_vol),
                "signal": candle_read,
            },
            "wave_comparison": self._analyze_wave_efficiency(df)
        }

    def _analyze_wave_efficiency(self, df) -> dict:
        if len(df) < 25:
            return {"status": "insufficient_data"}
            
        try:
            from ..weis_wave import WeisWaveGenerator
            generator = WeisWaveGenerator(df)
            waves = generator.generate()
            
            if len(waves) >= 3:
                # 寻找最近的两个同向波段
                last_wave = waves[-1]
                direction = last_wave.direction
                
                # 倒序查找同向波段
                same_dir_waves = [w for w in waves if w.direction == direction]
                if len(same_dir_waves) >= 2:
                    wave2 = same_dir_waves[-1] # 当前/最近波段
                    wave1 = same_dir_waves[-2] # 上一个同向波段
                    
                    # SOT 判断：推力减小但成交量放大
                    sot = wave2.volume > wave1.volume * 1.1 and wave2.thrust < wave1.thrust * 0.8
                    return {
                        "status": "ok",
                        "sot_detected": bool(sot),
                        "wave1_push": round(wave1.thrust, 2),
                        "wave2_push": round(wave2.thrust, 2),
                        "wave1_vol": round(wave1.volume, 2),
                        "wave2_vol": round(wave2.volume, 2),
                        "method": "weis_wave"
                    }
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"WeisWave analysis failed: {e}. Falling back to legacy mode.")

        # Legacy Mode (降级方案): 不再硬编码 6天，而是改为动态窗口
        recent = df.tail(40)
        # 根据 ATR 或简单的高低点寻找一个稍微动态的窗口长度
        # 为了稳定，取近期的波动周期，这里取 8 天作为默认降级窗口
        w_len = 8
        if len(recent) >= w_len * 2:
            wave1 = recent.iloc[-w_len*2:-w_len]
            wave2 = recent.iloc[-w_len:]
            wave1_push = max(wave1['High'].max() - wave1['Low'].min(), 1e-9)
            wave2_push = max(wave2['High'].max() - wave2['Low'].min(), 1e-9)
            # Legacy 模式下原来用的是 mean()，现在改为真实波段累加的 sum()，以向 Weis Wave 靠拢
            wave1_vol = wave1['Volume'].sum()
            wave2_vol = wave2['Volume'].sum()
            sot = wave2_vol > wave1_vol * 1.1 and wave2_push < wave1_push * 0.8
            return {
                "status": "ok",
                "sot_detected": bool(sot),
                "wave1_push": round(wave1_push, 2),
                "wave2_push": round(wave2_push, 2),
                "wave1_vol": round(wave1_vol, 2),
                "wave2_vol": round(wave2_vol, 2),
                "method": "legacy_fixed_window"
            }
            
        return {"status": "insufficient_swings"}

    def _analyze_signal_follow_through(self) -> dict:
        if len(self.data) < 5:
            return {"status": "insufficient_data"}
        df = self.data
        spring = self.pattern_detector.detect_spring() if self.pattern_detector else {}
        upthrust = self.pattern_detector.detect_upthrust() if self.pattern_detector else {}
        out = {"status": "ok", "spring_follow_through": {"tracked": False}, "upthrust_follow_through": {"tracked": False}}
        if spring.get('detected'):
            c0, c1 = df.iloc[-2], df.iloc[-1]
            three_h = c1['High'] > c0['High']
            three_l = c1['Low'] > c0['Low']
            three_c = c1['Close'] > c0['Close']
            vol_shrink_hard = c1['Volume'] < c0['Volume'] * 0.6
            failed = (not (three_h and three_l and three_c)) or vol_shrink_hard
            out['spring_follow_through'] = {
                "tracked": True,
                "three_highs_confirmed": bool(three_h and three_l and three_c),
                "low_quality": bool(failed),
                "priority_adjustment": "decrease" if failed else "keep",
            }
        if upthrust.get('detected'):
            c0, c1 = df.iloc[-2], df.iloc[-1]
            engulf_bull = c1['Close'] > c0['High'] and c1['Open'] <= c0['Close']
            vol_up = c1['Volume'] > c0['Volume'] * 1.05
            ut_invalid = engulf_bull and vol_up
            out['upthrust_follow_through'] = {
                "tracked": True,
                "bear_follow_through_confirmed": bool((c1['Close'] < c1['Open']) and vol_up),
                "trap_invalidated": bool(ut_invalid),
                "short_alert": "解除" if ut_invalid else "维持观察",
            }
        return out

    def _get_current_phase_context(self) -> str:
        """获取当前Phase上下文用于增强努力vs结果分析"""
        try:
            if self.pattern_detector:
                phase_result = self.pattern_detector.identify_phase()
                if isinstance(phase_result, dict):
                    return phase_result.get('phase', 'Unknown')
                return str(phase_result) if phase_result else 'Unknown'
        except Exception:
            pass
        return 'Unknown'

    def _phase_context_tail(self, phase: str, interpretation: str) -> str:
        """
        根据Phase上下文追加条件解释

        Wyckoff理论要求：同一量价行为在不同阶段意义完全不同。
        - Phase A: 高量低价 = 吸筹(正面), 高量高价 = 派发(负面)
        - Phase B: 高量窄幅 = 积累/派发进展中
        - Phase C: 量价背离 = 震仓信号
        - Phase D: 高量突破 = 趋势确认
        - Phase E: 缩量新高 = 需求枯竭, 缩量新低 = 供应枯竭
        """
        if 'Phase A' in phase:
            if interpretation in ('RESULT_WITHOUT_EFFORT', 'NORMAL'):
                return ' | [Phase A] 趋势停止阶段，缩量属于正常供应/需求吸收过程'
            elif interpretation == 'EFFORT_WITHOUT_RESULT':
                return ' | [Phase A] 大努力无结果确认停止行为(Stop Volume)，关键拐点信号'
            elif interpretation == 'DIVERGENCE':
                return ' | [Phase A] 背离确认趋势衰竭，等待AR/ST确认'
        elif 'Phase B' in phase:
            if interpretation == 'WEAK_CONFIRMATION':
                return ' | [Phase B] 积累/派发推进中，弱势量价关系属正常区间波动'
            elif interpretation == 'EFFORT_WITHOUT_RESULT':
                return ' | [Phase B] 大努力无结果可能预示区间失效或即将出现Spring/Upthrust'
        elif 'Phase C' in phase:
            if interpretation in ('DIVERGENCE', 'EFFORT_WITHOUT_RESULT'):
                return ' | [Phase C] 背离信号可能确认Spring/Upthrust震仓有效'
            elif interpretation == 'CONFIRMATION':
                return ' | [Phase C] 努力结果一致有利于震仓后趋势反转'
        elif 'Phase D' in phase:
            if interpretation == 'CONFIRMATION':
                return ' | [Phase D] 高量突破是趋势启动的理想确认信号'
            elif interpretation == 'RESULT_WITHOUT_EFFORT':
                return ' | [Phase D] 缩量突破需警惕假突破(LPSY/UT)'
        elif 'Phase E' in phase:
            if interpretation == 'RESULT_WITHOUT_EFFORT':
                return ' | [Phase E] 缩量推进需警惕趋势末端的需求/供应枯竭'
            elif interpretation == 'CONFIRMATION':
                return ' | [Phase E] 高量同向推进，趋势健康持续'
        elif 'Distribution' in phase or '派发' in phase:
            if interpretation in ('CONFIRMATION', 'WEAK_CONFIRMATION'):
                return ' | [Distribution] 量价确认派发趋势，供应主导市场'
            elif interpretation in ('DIVERGENCE', 'EFFORT_WITHOUT_RESULT'):
                return ' | [Distribution] 背离确认派发衰竭，可能出现 LPSY 或 Spring'
            elif interpretation == 'RESULT_WITHOUT_EFFORT':
                return ' | [Distribution] 缩量下跌需求枯竭，派发末端信号'
            elif interpretation == 'STRONG_OUTPERFORMANCE':
                return ' | [Distribution] 相对强势但处于派发期，可能为诱多反弹，警惕 UT'
        elif 'Markup' in phase:
            if interpretation == 'RESULT_WITHOUT_EFFORT':
                return ' | [Markup] 无量上涨，警惕需求衰竭，注意止盈'
            elif interpretation == 'CONFIRMATION':
                return ' | [Markup] 价量配合的健康上涨趋势'
            elif interpretation == 'DIVERGENCE':
                return ' | [Markup] 量价背离可能预示 Markup 末端，关注 Phase A 派发信号'
        elif 'Markdown' in phase:
            if interpretation == 'RESULT_WITHOUT_EFFORT':
                return ' | [Markdown] 无量下跌，供应趋于枯竭，关注筑底信号'
            elif interpretation == 'CONFIRMATION':
                return ' | [Markdown] 价量配合的下跌趋势持续'
            elif interpretation == 'DIVERGENCE':
                return ' | [Markdown] 量价背离预示卖盘枯竭，可能出现 Spring 或 PS'
            elif interpretation in ('WEAK_UNDERPERFORMANCE', 'DOUBLE_WEAKNESS'):
                return ' | [Markdown] 弱势放量下跌，市场恐慌情绪加剧，等待 SC 出现'
        return ''

    def _detect_vsa_anomalies(self) -> dict:
        """
        检测微观 VSA (Volume Spread Analysis) 关键确认信号
        - 无供应柱 (No Supply Bar): 收盘下跌，价差缩小，成交量低于前两日
        - 无需求柱 (No Demand Bar): 收盘上涨，价差缩小，成交量低于前两日
        """
        if self.data is None or len(self.data) < 5:
            return {"status": "insufficient_data"}
            
        df = self.data.tail(5)
        last_idx = len(df) - 1
        curr = df.iloc[last_idx]
        prev1 = df.iloc[last_idx - 1]
        prev2 = df.iloc[last_idx - 2]
        
        curr_spread = curr['High'] - curr['Low']
        prev1_spread = prev1['High'] - prev1['Low']
        prev2_spread = prev2['High'] - prev2['Low']
        
        is_down_close = curr['Close'] < prev1['Close']
        is_narrow_spread = curr_spread < prev1_spread and curr_spread < prev2_spread
        is_low_volume = curr['Volume'] < prev1['Volume'] and curr['Volume'] < prev2['Volume']
        
        no_supply = is_down_close and is_narrow_spread and is_low_volume
        
        is_up_close = curr['Close'] > prev1['Close']
        no_demand = is_up_close and is_narrow_spread and is_low_volume
        
        signal = "none"
        desc = "未检测到微观VSA枯竭信号"
        
        if no_supply:
            signal = "no_supply"
            desc = "检测到【无供应柱】(No Supply)：缩量窄幅回落，供应枯竭，是二次测试(ST)或破底翻的绝佳微观确认"
        elif no_demand:
            signal = "no_demand"
            desc = "检测到【无需求柱】(No Demand)：缩量窄幅反弹，需求枯竭，是遇阻(Upthrust)或假突破的绝佳微观确认"
            
        return {
            "status": "ok",
            "signal": signal,
            "description": desc,
            "is_no_supply": bool(no_supply),
            "is_no_demand": bool(no_demand)
        }
