import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from ..config.settings import WyckoffConfig
from .utils import PhaseAdapter
from ..exceptions import InsufficientDataError, LawAnalysisError
from .point_and_figure import PointAndFigureCalculator, calculate_cause_effect_from_pnf
import logging
logger = logging.getLogger(__name__)

class WyckoffLawAnalyzer:
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, pattern_detector):
        self.data = data
        self.config = config
        self.pattern_detector = pattern_detector

    def analyze_supply_demand_law(self) -> dict:
        """Wyckoff第一定律：供求定律完整分析"""
        if self.data is None or len(self.data) < 60:
            raise InsufficientDataError("供求分析", required=60, actual=len(self.data) if self.data is not None else 0)

        df = self.data.copy()

        # 1. 识别当前处于积累期还是派发期 (使用 PhaseAdapter)
        phase_result = self.pattern_detector.identify_phase()
        phase_obj = phase_result.get('phase_enum') or phase_result.get('phase', 'Unknown')
        is_accumulation = PhaseAdapter.is_accumulation(phase_obj)
        is_distribution = PhaseAdapter.is_distribution(phase_obj)

        # 2. 检测交易区间
        trading_range = self.pattern_detector.detect_trading_range()
        in_range = trading_range.get("is_consolidation", False)

        # 3. 分析供求关系关键指标
        current_price = df['Close'].iloc[-1]
        current_vol = df['Volume'].iloc[-1]
        vol_ma20 = df['Volume_MA20'].iloc[-1]

        # 4. 检测关键事件
        spring = self.pattern_detector.detect_spring()
        upthrust = self.pattern_detector.detect_upthrust()
        sos = self.pattern_detector.detect_sos()
        sow = self.pattern_detector.detect_sow()

        # 5. 供求分析
        supply_demand_analysis = {
            "current_phase": phase_obj,
            "trading_range_status": "in_consolidation" if in_range else "trending",
            "volume_analysis": {
                "current_volume_ratio": round(current_vol / max(vol_ma20, 1), 2),
                "volume_trend": "increasing" if df['Volume'].iloc[-20:].mean() > df['Volume'].iloc[-60:-20].mean() else "decreasing"
            }
        }

        # 6. 积累期供求分析
        if is_accumulation:
            accumulation_stages = {
                "preliminary_support": self._detect_preliminary_support(),
                "accumulation_range": in_range,
                "absorption_pattern": self._analyze_absorption_pattern(),
                "spring_status": "detected" if spring.get('detected') else "not_detected",
                "sos_status": "detected" if sos.get('detected') else "not_detected"
            }

            # 判断积累阶段
            if spring.get('detected') and sos.get('detected'):
                stage = "Phase D-E (准备突破)"
                supply_demand_balance = "需求主导，准备进入上涨期"
            elif in_range:
                stage = "Phase B-C (积累震荡)"
                supply_demand_balance = "供求平衡，主力吸筹中"
            else:
                stage = "Phase A (初步支撑)"
                supply_demand_balance = "需求开始出现，但未确立"

            supply_demand_analysis["accumulation_analysis"] = {
                "current_stage": stage,
                "supply_demand_balance": supply_demand_balance,
                "details": accumulation_stages
            }

        # 7. 派发期供求分析
        elif is_distribution:
            distribution_stages = {
                "preliminary_supply": self._detect_preliminary_supply(),
                "distribution_range": in_range,
                "exhaustion_pattern": self._analyze_exhaustion_pattern(),
                "upthrust_status": "detected" if upthrust.get('detected') else "not_detected",
                "sow_status": "detected" if sow.get('detected') else "not_detected"
            }

            # 判断派发阶段
            if upthrust.get('detected') and sow.get('detected'):
                stage = "Phase D-E (准备下跌)"
                supply_demand_balance = "供应主导，准备进入下跌期"
            elif in_range:
                stage = "Phase B-C (派发震荡)"
                supply_demand_balance = "供求平衡，主力出货中"
            else:
                stage = "Phase A (初步阻力)"
                supply_demand_balance = "供应开始出现，但未确立"

            supply_demand_analysis["distribution_analysis"] = {
                "current_stage": stage,
                "supply_demand_balance": supply_demand_balance,
                "details": distribution_stages
            }

        else:
            # 趋势阶段的供求分析
            current_trend = "uptrend" if df['Close'].iloc[-1] > df['MA200'].iloc[-1] else "downtrend"
            supply_demand_analysis["trend_analysis"] = {
                "current_trend": current_trend,
                "trend_strength": "strong" if current_vol / vol_ma20 > 1.5 else "moderate",
                "supply_demand_balance": "需求主导" if current_trend == "uptrend" else "供应主导"
            }

        return supply_demand_analysis

    def analyze_effort_vs_result_law(self) -> dict:
        """Wyckoff第二定律：努力vs结果定律完整分析"""
        if self.data is None or len(self.data) < 20:
            raise InsufficientDataError("努力vs结果分析", required=20, actual=len(self.data) if self.data is not None else 0)

        df = self.data.copy()

        # 分析多个时间框架
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

            # 计算努力（成交量变化）
            vol_start = recent_df['Volume'].iloc[0]
            vol_end = recent_df['Volume'].iloc[-1]
            vol_avg = recent_df['Volume'].mean()
            vol_ma_ref = df['Volume_MA20'].iloc[-1]

            volume_effort = vol_end / vol_ma_ref if vol_ma_ref > 0 else 1.0

            # 计算结果（价格变化）
            price_start = recent_df['Close'].iloc[0]
            price_end = recent_df['Close'].iloc[-1]
            price_result_pct = ((price_end - price_start) / price_start) * 100

            # Wyckoff判断逻辑
            effort_magnitude = abs(volume_effort - 1.0)
            result_magnitude = abs(price_result_pct)

            # 努力vs结果一致性分析
            if effort_magnitude > 0.5:  # 明显的成交量变化
                if result_magnitude > 2.0:  # 明显的价格变化
                    if (volume_effort > 1.0 and price_result_pct > 0) or \
                       (volume_effort < 1.0 and price_result_pct < 0):
                        interpretation = "CONFIRMATION"
                        meaning = "努力与结果一致，确认当前趋势"
                    else:
                        interpretation = "DIVERGENCE"
                        meaning = "努力与结果背离，警示信号"
                else:
                    # 大努力但价格变化小
                    if effort_magnitude > 0.8:
                        interpretation = "EFFORT_WITHOUT_RESULT"
                        meaning = "大努力无结果，可能是拐点信号"
                    else:
                        interpretation = "WEAK_CONFIRMATION"
                        meaning = "努力与结果基本一致，但强度较弱"
            else:
                # 成交量无明显变化
                if result_magnitude > 3.0:
                    interpretation = "RESULT_WITHOUT_EFFORT"
                    meaning = "价格变动缺乏成交量支持，需谨慎"
                else:
                    interpretation = "NORMAL"
                    meaning = "正常的量价关系"

            effort_result_analysis[tf_key] = {
                "timeframe": tf_info['name'],
                "volume_effort": round(volume_effort, 2),
                "price_result": round(price_result_pct, 2),
                "effort_magnitude": round(effort_magnitude, 3),
                "result_magnitude": round(result_magnitude, 2),
                "interpretation": interpretation,
                "meaning": meaning
            }

        # 综合判断
        interpretations = [tf['interpretation'] for tf in effort_result_analysis.values()]

        # 如果所有时间框架都显示CONFIRMATION
        if all(interp == "CONFIRMATION" for interp in interpretations):
            overall_assessment = "STRONG_CONFIRMATION"
            wyckoff_guidance = "多时间框架一致确认，趋势可靠性高"

        # 如果任一时间框架显示DIVERGENCE或EFFORT_WITHOUT_RESULT
        elif any(interp in ["DIVERGENCE", "EFFORT_WITHOUT_RESULT"] for interp in interpretations):
            overall_assessment = "WARNING_SIGNAL"
            wyckoff_guidance = "检测到努力vs结果背离，建议谨慎或等待确认"

        # 如果有RESULT_WITHOUT_EFFORT
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
        """成交量健康度：从量比走向量价博弈性质。"""
        df = self.data.copy()
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
        close = curr['Close']
        pos = (close - range_low) / max(range_high - range_low, 1e-9)
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

    def _analyze_wave_efficiency(self, df: pd.DataFrame) -> dict:
        """对比相邻上升波：量增但推进缩短 => SOT。"""
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
        """Spring/UT 不立即采信，要求次日跟随确认。"""
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

    def analyze_cause_effect_law_enhanced(self) -> dict:
        """Wyckoff第三定律：因果定律增强分析"""
        if self.data is None or len(self.data) < 60:
            raise InsufficientDataError("因果分析", required=60, actual=len(self.data) if self.data is not None else 0)

        # 增强因果分析
        trading_range = self.pattern_detector.detect_trading_range()
        tr_story = self._build_tr_story()
        
        # 关键修复：先获取阶段信息，再进行因果分析
        # 优先使用阶段识别器结果，避免仅用 MA60 推断造成语义偏差；失败时再降级到 MA60。
        current_close = self.data['Close'].iloc[-1]
        phase_result = self.pattern_detector.identify_phase() if self.pattern_detector else {}
        phase = phase_result.get("phase", "") if isinstance(phase_result, dict) else ""
        if not phase:
            ma60 = self.data['Close'].rolling(60).mean().iloc[-1] if len(self.data) >= 60 else current_close
            if trading_range.get("is_consolidation"):
                phase = "Accumulation" if current_close < ma60 else "Distribution"
            else:
                phase = "Markup" if current_close > ma60 else "Markdown"

        # 获取基础因果分析 - 使用内置分析方法
        basic_cause_effect = self._basic_cause_effect_analysis(
            phase=phase,
            known_tr_high=trading_range.get('high'),
            known_tr_low=trading_range.get('low'),
        )

        # 1. 测量"努力" - 更准确的积累/派发努力计算
        if trading_range.get("is_consolidation"):
            # 在交易区间内，测量积累/派发的努力
            range_high = trading_range.get("high", current_close)
            range_low = trading_range.get("low", current_close * 0.95)
            range_duration = trading_range.get("duration_days", 60)

            # 计算区间的成交量特征
            df = self.data.tail(range_duration)
            avg_range_volume = df['Volume'].mean()
            total_range_volume = df['Volume'].sum()

            # 计算价格紧密度（努力的质量指标）
            range_tightness = (range_high - range_low) / ((range_high + range_low) / 2)

            # 计算积累/派发努力的综合指标
            vol_ma20 = df['Volume_MA20'].mean() if 'Volume_MA20' in df.columns else avg_range_volume
            volume_participation = (avg_range_volume / vol_ma20) if vol_ma20 and vol_ma20 > 0 else 1.0

            accumulation_effort = {
                "time_effort": range_duration,  # 时间努力
                "volume_effort": total_range_volume,  # 成交量努力
                "avg_volume": avg_range_volume,
                "volume_participation": round(volume_participation, 2),
                "price_consolidation": range_tightness,  # 价格整理努力
                "cause_size": range_high - range_low,  # 因果幅度
                "effort_quality": "HIGH" if range_tightness < 0.15 else "MEDIUM" if range_tightness < 0.25 else "LOW"
            }

            # 2. 预测"效果" - 基于点数图水平计数的目标计算
            current_position = trading_range.get("position", 0.5)
            cause = range_high - range_low
            
            # 使用点数图计算因果效应
            try:
                pnf_result = calculate_cause_effect_from_pnf(
                    self.data, 
                    box_size_pct=1.0,
                    reversal_boxes=3,
                    phase=phase,
                    known_tr_high=trading_range.get('high'),
                    known_tr_low=trading_range.get('low'),
                )
                
                if pnf_result.get('horizontal_count', 0) >= 3:
                    targets = pnf_result.get('targets', {})
                    projected_direction = "UPSIDE" if pnf_result.get('breakout_direction') == 'up' else "DOWNSIDE"
                    effect_probability = self._calculate_breakout_probability(phase, pnf_result.get('breakout_direction', 'up'))
                    
                    cause_effect_interpretation = {
                        "method": "point_and_figure",
                        "current_situation": f"当前处于{phase}，点数图水平计数{pnf_result.get('horizontal_count', 0)}列",
                        "effort_assessment": f"积累/派发努力质量为{accumulation_effort['effort_quality']}",
                        "projected_direction": projected_direction,
                        "breakout_probability": effect_probability,
                        "target_projections": targets,
                        "wyckoff_logic": pnf_result.get('description', ''),
                        "theory": "威科夫因果法则：水平计数决定垂直目标"
                    }
                else:
                    # 备用方法：基于波动率收缩和时间积累
                    atr = self.data['ATR'].iloc[-1] if 'ATR' in self.data.columns else (range_high - range_low) / 5
                    
                    # 计算波动率收缩程度
                    recent_data = self.data.tail(range_duration)
                    atr_series = (recent_data['High'] - recent_data['Low']).rolling(window=5).mean()
                    atr_start = atr_series.iloc[0] if len(atr_series) > 0 else 0
                    atr_end = atr_series.iloc[-1] if len(atr_series) > 0 else 0
                    volatility_contraction = 1 - (atr_end / atr_start) if atr_start > 0 else 0
                    
                    # 基于波动率收缩和时间积累计算潜力
                    contraction_factor = max(0.5, 1 + volatility_contraction * 2)
                    horizontal_potential = cause * contraction_factor * (range_duration / 30)
                    
                    if current_position > 0.5:
                        breakout_point = range_high
                        targets = {
                            "minimum_target": float(round(breakout_point + horizontal_potential * 0.618, 2)),
                            "likely_target": float(round(breakout_point + horizontal_potential, 2)),
                            "maximum_target": float(round(breakout_point + horizontal_potential * 1.618, 2))
                        }
                        projected_direction = "UPSIDE"
                        effect_probability = self._calculate_breakout_probability(phase, "up")
                    else:
                        breakdown_point = range_low
                        targets = {
                            "minimum_target": float(round(breakdown_point - horizontal_potential * 0.618, 2)),
                            "likely_target": float(round(breakdown_point - horizontal_potential, 2)),
                            "maximum_target": float(round(breakdown_point - horizontal_potential * 1.618, 2))
                        }
                        projected_direction = "DOWNSIDE"
                        effect_probability = self._calculate_breakout_probability(phase, "down")
                    
                    cause_effect_interpretation = {
                        "method": "volatility_contraction",
                        "current_situation": f"当前处于{phase}，波动率收缩{volatility_contraction*100:.1f}%",
                        "effort_assessment": f"积累/派发努力质量为{accumulation_effort['effort_quality']}",
                        "projected_direction": projected_direction,
                        "breakout_probability": effect_probability,
                        "target_projections": targets,
                        "wyckoff_logic": f"基于波动率收缩{volatility_contraction*100:.1f}%和{range_duration}天积累，预计{cause:.2f}点的积累/派发努力",
                        "theory": "改进估算：基于波动率收缩和时间积累"
                    }
                    
            except Exception as e:
                logger.warning(f"点数图计算失败，使用备用方法: {e}")
                # 备用方法
                atr = self.data['ATR'].iloc[-1] if 'ATR' in self.data.columns else (range_high - range_low) / 5
                horizontal_potential = range_duration * atr * 0.25
                
                if current_position > 0.5:
                    breakout_point = range_high
                    targets = {
                        "minimum_target": float(round(breakout_point + horizontal_potential * 0.618, 2)),
                        "likely_target": float(round(breakout_point + horizontal_potential, 2)),
                        "maximum_target": float(round(breakout_point + horizontal_potential * 1.618, 2))
                    }
                    projected_direction = "UPSIDE"
                    effect_probability = self._calculate_breakout_probability(phase, "up")
                else:
                    breakdown_point = range_low
                    targets = {
                        "minimum_target": float(round(breakdown_point - horizontal_potential * 0.618, 2)),
                        "likely_target": float(round(breakdown_point - horizontal_potential, 2)),
                        "maximum_target": float(round(breakdown_point - horizontal_potential * 1.618, 2))
                    }
                    projected_direction = "DOWNSIDE"
                    effect_probability = self._calculate_breakout_probability(phase, "down")
                
                cause_effect_interpretation = {
                    "method": "fallback",
                    "current_situation": f"当前处于{phase}，因果幅度为{cause:.2f}点",
                    "effort_assessment": f"积累/派发努力质量为{accumulation_effort['effort_quality']}",
                    "projected_direction": projected_direction,
                    "breakout_probability": effect_probability,
                    "target_projections": targets,
                    "wyckoff_logic": f"备用估算：根据Wyckoff因果定律，{cause:.2f}点的积累/派发努力",
                    "theory": "备用估算方法"
                }

            return {
                "basic_analysis": basic_cause_effect,
                "enhanced_analysis": {
                    "accumulation_distribution_effort": accumulation_effort,
                    "projected_effects": cause_effect_interpretation,
                    "tr_story": tr_story,
                }
            }

        else:
            # 不在交易区间内，使用趋势因果分析
            current_price = self.data['Close'].iloc[-1]
            atr = self.data['ATR'].iloc[-1]

            trend_analysis = {
                "current_trend": phase,
                "current_price": current_price,
                "volatility_measure": atr,
                "cause_effect_status": "TREND_FOLLOWING",
                "interpretation": "当前处于趋势阶段，因果定律主要体现为趋势持续性"
            }

            return {
                "basic_analysis": basic_cause_effect,
                "enhanced_analysis": {
                    "trend_mode_cause_effect": trend_analysis,
                    "tr_story": tr_story,
                }
            }

    def _build_tr_story(self) -> dict:
        """BC/ST 锁定TR并给出破位目标，同时动态区分再派发与吸筹。"""
        df = self.data.copy()
        if len(df) < 80:
            return {"status": "insufficient_data"}

        recent = df.tail(80)
        high = recent['High'].max()
        low = recent['Low'].min()
        width = high - low
        close = recent['Close'].iloc[-1]
        broke_down = close < low
        downside_target_1 = low - width if broke_down else None

        upthrust = self.pattern_detector.detect_upthrust() if self.pattern_detector else {}
        spring = self.pattern_detector.detect_spring() if self.pattern_detector else {}
        rebound_vol = recent['Volume'].tail(10).mean()
        base_vol = recent['Volume'].head(40).mean()
        weak_rebound = rebound_vol < base_vol * 0.9

        mode = "neutral"
        confidence_bias = 0
        if spring.get('detected'):
            mode = "accumulation_monitor"
            confidence_bias = -10
        elif upthrust.get('detected') and weak_rebound:
            mode = "redistribution"
            confidence_bias = 15

        dynamic_path = self._analyze_target_path_monitor(recent, low, downside_target_1)
        return {
            "status": "active",
            "tr_range": {
                "resistance": round(high, 2),
                "support": round(low, 2),
                "width": round(width, 2)
            },
            "breakdown": {
                "detected": bool(broke_down),
                "downside_target_1": round(downside_target_1, 2) if downside_target_1 is not None else None
            },
            "dynamic_target_context": dynamic_path,
            "phase_mode": mode,
            "confidence_bias": confidence_bias
        }

    def _analyze_target_path_monitor(self, recent: pd.DataFrame, support: float, target: Optional[float]) -> dict:
        """监测目标运行路径：无需求反弹/停止行为，并识别历史密集区重叠。"""
        if target is None:
            return {"status": "inactive"}
        bins = pd.cut(recent['Close'], bins=8)
        vp = recent.groupby(bins, observed=False)['Volume'].sum()
        hvn_zone = vp.idxmax() if len(vp) else None
        overlap = False
        if hvn_zone is not None:
            overlap = hvn_zone.left <= target <= hvn_zone.right

        last5 = recent.tail(5)
        no_demand_bounces = int(((last5['Close'] > last5['Open']) & (last5['Volume'] < last5['Volume'].rolling(3).mean().fillna(last5['Volume']))).sum())
        stopping = bool(((last5['Volume'] > last5['Volume'].rolling(3).mean().fillna(last5['Volume']) * 1.4) & ((last5['High'] - last5['Low']) < (recent['High'] - recent['Low']).rolling(10).mean().iloc[-1])).any())
        return {
            "status": "active",
            "target_overlap_with_historical_demand": overlap,
            "no_demand_bounce_count": no_demand_bounces,
            "target_hit_probability_bias": 10 if no_demand_bounces >= 2 else -10 if stopping else 0,
            "bottoming_risk_alert": stopping
        }

    def _detect_preliminary_support(self) -> dict:
        """检测初步支撑（积累期Phase A特征）- 价格急跌后出现大量接盘"""
        if self.data is None or len(self.data) < 20:
            return {"detected": False}
        df = self.data.tail(60)
        price_dropped = df['Close'].pct_change(5).min() < -0.08
        high_vol_on_low = (
            (df['Volume'] > df['Volume_MA20'] * 1.5) &
            (df['Close'] < df['Close'].rolling(20).mean())
        ).any()
        detected = bool(price_dropped and high_vol_on_low)
        return {
            "detected": detected,
            "description": "检测到初步支撑：急跌后出现放量承接" if detected else "未检测到明显初步支撑"
        }

    def _detect_preliminary_supply(self) -> dict:
        """检测初步阻力（派发期Phase A特征）- 价格急涨后出现大量抛压"""
        if self.data is None or len(self.data) < 20:
            return {"detected": False}
        df = self.data.tail(60)
        price_rallied = df['Close'].pct_change(5).max() > 0.08
        high_vol_on_high = (
            (df['Volume'] > df['Volume_MA20'] * 1.5) &
            (df['Close'] > df['Close'].rolling(20).mean())
        ).any()
        detected = bool(price_rallied and high_vol_on_high)
        return {
            "detected": detected,
            "description": "检测到初步阻力：急涨后出现放量抛售" if detected else "未检测到明显初步阻力"
        }

    def _analyze_absorption_pattern(self) -> dict:
        """分析吸筹模式：缩量横盘 + 下跌时缩量、上涨时放量"""
        if self.data is None or len(self.data) < 40:
            return {"pattern": "unknown", "strength": "unknown"}
        df = self.data.tail(40)
        up_days = df[df['Close'] > df['Close'].shift(1)]
        down_days = df[df['Close'] < df['Close'].shift(1)]
        if up_days.empty or down_days.empty:
            return {"pattern": "insufficient_data", "strength": "unknown"}
        avg_up_vol = up_days['Volume'].mean()
        avg_down_vol = down_days['Volume'].mean()
        ratio = avg_up_vol / avg_down_vol if avg_down_vol > 0 else 1.0
        if ratio > 1.4:
            pattern, strength = "absorption", "strong"
        elif ratio > 1.1:
            pattern, strength = "mild_absorption", "medium"
        else:
            pattern, strength = "no_absorption", "weak"
        return {"pattern": pattern, "strength": strength, "up_down_vol_ratio": round(ratio, 2)}

    def _analyze_exhaustion_pattern(self) -> dict:
        """分析耗散模式：价格新高但成交量萎缩"""
        if self.data is None or len(self.data) < 40:
            return {"pattern": "unknown", "strength": "unknown"}
        df = self.data.tail(40)
        recent_high = df['High'].max()
        older_high = self.data.iloc[-80:-40]['High'].max() if len(self.data) >= 80 else recent_high * 0.95
        new_high = recent_high > older_high
        recent_vol = df['Volume'].mean()
        older_vol = self.data.iloc[-80:-40]['Volume'].mean() if len(self.data) >= 80 else recent_vol
        vol_declining = recent_vol < older_vol * 0.85
        if new_high and vol_declining:
            pattern, strength = "exhaustion", "strong"
        elif vol_declining:
            pattern, strength = "mild_exhaustion", "medium"
        else:
            pattern, strength = "no_exhaustion", "weak"
        return {"pattern": pattern, "strength": strength,
                "new_high": new_high, "volume_declining": vol_declining}

    def _calculate_breakout_probability(self, phase: str, direction: str) -> str:
        """计算突破概率"""
        # 基于阶段和方向计算突破概率
        if "Accumulation" in phase and direction == "up":
            return "HIGH (75-85%)"
        elif "Distribution" in phase and direction == "down":
            return "HIGH (75-85%)"
        else:
            return "MEDIUM (50-65%)"

    def _basic_cause_effect_analysis(self, phase: str = '', 
                                      known_tr_high: float = None,
                                      known_tr_low: float = None) -> dict:
        """
        基础因果分析 - 使用点数图水平计数
        
        威科夫因果法则核心：
        - 因（Cause）：水平准备（横向盘整的规模，用点数图列数衡量）
        - 果（Effect）：垂直运动（价格突破后的目标幅度）
        
        重要理论约束：
        - 派发期的"因"触发向下的"果"
        - 吸筹期的"因"触发向上的"果"
        
        Args:
            phase: 当前阶段字符串
            known_tr_high: 已知交易区间上沿（可选，优先使用）
            known_tr_low: 已知交易区间下沿（可选，优先使用）
        """
        try:
            # 计算交易区间：优先使用已知边界，否则用 60 日机械扫描
            recent_data = self.data.tail(60)
            if known_tr_high is not None and known_tr_low is not None:
                trading_range_high = known_tr_high
                trading_range_low = known_tr_low
            else:
                trading_range_high = recent_data['High'].max()
                trading_range_low = recent_data['Low'].min()
            cause_size = trading_range_high - trading_range_low

            # 使用点数图计算因果效应
            try:
                pnf_result = calculate_cause_effect_from_pnf(
                    self.data, 
                    box_size_pct=1.0,
                    reversal_boxes=3,
                    phase=phase,
                    known_tr_high=trading_range_high,
                    known_tr_low=trading_range_low,
                )
                
                if pnf_result.get('horizontal_count', 0) >= 3:
                    # 点数图计算成功
                    return {
                        "method": "point_and_figure",
                        "cause_size": cause_size,
                        "horizontal_count": pnf_result.get('horizontal_count', 0),
                        "vertical_count": pnf_result.get('vertical_count', 0),
                        "accumulation_range": pnf_result.get('accumulation_range', {}),
                        "base_effect": pnf_result.get('base_effect', 0),
                        "breakout_direction": pnf_result.get('breakout_direction', 'up'),
                        "breakout_point": trading_range_high,
                        "targets": pnf_result.get('targets', {}),
                        "current_position": (self.data['Close'].iloc[-1] - trading_range_low) / cause_size if cause_size > 0 else 0,
                        "consolidation_duration_days": 60,
                        "description": pnf_result.get('description', ''),
                        "theory": "威科夫因果法则：水平计数决定垂直目标"
                    }
            except Exception as e:
                logger.warning(f"点数图计算失败，使用备用方法: {e}")
            
            # 备用方法：基于波动率收缩和时间积累
            duration = 60
            atr = self.data['ATR'].iloc[-1] if 'ATR' in self.data.columns else (trading_range_high - trading_range_low) / 5
            
            # 计算波动率收缩程度
            atr_series = (recent_data['High'] - recent_data['Low']).rolling(window=5).mean()
            atr_start = atr_series.iloc[0] if len(atr_series) > 0 else 0
            atr_end = atr_series.iloc[-1] if len(atr_series) > 0 else 0
            volatility_contraction = 1 - (atr_end / atr_start) if atr_start > 0 else 0
            
            # 基于波动率收缩和时间积累计算潜力
            contraction_factor = max(0.5, 1 + volatility_contraction * 2)
            potential = cause_size * contraction_factor * (duration / 30)
            
            breakout_point = trading_range_high
            targets = {
                "target_1": round(breakout_point + potential * 0.618, 2),
                "target_2": round(breakout_point + potential, 2),
                "target_3": round(breakout_point + potential * 1.618, 2)
            }

            return {
                "method": "volatility_contraction",
                "cause_size": cause_size,
                "volatility_contraction": round(volatility_contraction * 100, 1),
                "contraction_factor": round(contraction_factor, 2),
                "breakout_point": breakout_point,
                "targets": targets,
                "current_position": (self.data['Close'].iloc[-1] - trading_range_low) / cause_size if cause_size > 0 else 0,
                "consolidation_duration_days": duration,
                "description": f"基于波动率收缩{volatility_contraction*100:.1f}%和{duration}天积累",
                "theory": "改进估算：基于波动率收缩和时间积累"
            }
        except Exception as e:
            raise LawAnalysisError("因果分析", str(e)) from e
  