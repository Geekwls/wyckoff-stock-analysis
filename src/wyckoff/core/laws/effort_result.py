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
                        elif relative_strength < -2:
                            interpretation = "WEAK_UNDERPERFORMANCE"
                            meaning = f"弱势跑输大盘：个股{price_result_pct:.1f}% vs 大盘{market_return:.1f}%，相对强度{relative_strength:.1f}%，需谨慎"
                        else:
                            interpretation = "CONFIRMATION"
                            meaning = f"努力与结果一致，确认当前趋势（相对强度{relative_strength:.1f}%，与大盘同步）"
                    else:
                        if relative_strength > 3:
                            interpretation = "DIVERGENCE_WITH_STRENGTH"
                            meaning = f"量价背离但跑赢大盘：个股{price_result_pct:.1f}% vs 大盘{market_return:.1f}%，可能存在独立行情"
                        elif relative_strength < -3:
                            interpretation = "DOUBLE_WEAKNESS"
                            meaning = f"量价背离且跑输大盘：个股{price_result_pct:.1f}% vs 大盘{market_return:.1f}%，双重警示信号"
                        else:
                            interpretation = "DIVERGENCE"
                            meaning = "努力与结果背离，警示信号"
                else:
                    if effort_magnitude > 0.8:
                        interpretation = "EFFORT_WITHOUT_RESULT"
                        meaning = f"大努力无结果，可能是拐点信号（相对强度{relative_strength:.1f}%）"
                    else:
                        interpretation = "WEAK_CONFIRMATION"
                        meaning = f"努力与结果基本一致，但强度较弱（相对强度{relative_strength:.1f}%）"
            else:
                if result_magnitude > 3.0:
                    interpretation = "RESULT_WITHOUT_EFFORT"
                    if price_result_pct > 0 and relative_strength > 3:
                        meaning = f"无量上涨但跑赢大盘{relative_strength:.1f}%，可能存在独立行情或操纵"
                    elif price_result_pct < 0 and relative_strength < -3:
                        meaning = f"无量下跌且跑输大盘{relative_strength:.1f}%，弱势特征明显"
                    else:
                        meaning = "价格变动缺乏成交量支持，需谨慎"
                else:
                    interpretation = "NORMAL"
                    meaning = f"正常的量价关系（相对强度{relative_strength:.1f}%）"

            effort_result_analysis[tf_key] = {
                "timeframe": tf_info['name'],
                "volume_effort": round(volume_effort, 2),
                "price_result": round(price_result_pct, 2),
                "market_return": round(market_return, 2),
                "relative_strength": round(relative_strength, 2),
                "effort_magnitude": round(effort_magnitude, 3),
                "result_magnitude": round(result_magnitude, 2),
                "interpretation": interpretation,
                "meaning": meaning
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

        return {
            "overall_assessment": overall_assessment,
            "wyckoff_guidance": wyckoff_guidance,
            "timeframe_analysis": effort_result_analysis,
            "volume_health": volume_health,
            "follow_through": follow_through
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
        recent = df.tail(25)
        returns = recent['Close'].pct_change().fillna(0)
        up_idx = returns[returns > 0].index.tolist()
        if len(up_idx) < 6:
            return {"status": "insufficient_swings"}
        wave1 = recent.iloc[-12:-6]
        wave2 = recent.iloc[-6:]
        wave1_push = wave1['High'].max() - wave1['Low'].min()
        wave2_push = wave2['High'].max() - wave2['Low'].min()
        wave1_vol = wave1['Volume'].mean()
        wave2_vol = wave2['Volume'].mean()
        sot = wave2_vol > wave1_vol * 1.1 and wave2_push < wave1_push * 0.8
        return {
            "status": "ok",
            "sot_detected": bool(sot),
            "wave1_push": round(wave1_push, 2),
            "wave2_push": round(wave2_push, 2),
            "wave1_avg_vol": round(wave1_vol, 2),
            "wave2_avg_vol": round(wave2_vol, 2)
        }

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
