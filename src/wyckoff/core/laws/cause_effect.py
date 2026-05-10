import pandas as pd
import logging
from typing import Dict, Optional, Tuple
from ...exceptions import InsufficientDataError, LawAnalysisError
from ..point_and_figure import calculate_cause_effect_from_pnf

logger = logging.getLogger(__name__)


class CauseEffectMixin:
    """第三定律：因果定律"""

    def analyze_cause_effect_law_enhanced(self) -> dict:
        if self.data is None or len(self.data) < 60:
            raise InsufficientDataError("因果分析", required=60, actual=len(self.data) if self.data is not None else 0)

        trading_range = self.pattern_detector.detect_trading_range()
        tr_story = self._build_tr_story()
        current_close = self.data['Close'].iloc[-1]
        phase_result = self.pattern_detector.identify_phase() if self.pattern_detector else {}
        phase = phase_result.get("phase", "") if isinstance(phase_result, dict) else ""
        if not phase:
            ma60 = self.data['Close'].rolling(60).mean().iloc[-1] if len(self.data) >= 60 else current_close
            if trading_range.get("is_consolidation"):
                phase = "Accumulation" if current_close < ma60 else "Distribution"
            else:
                phase = "Markup" if current_close > ma60 else "Markdown"

        basic_cause_effect = self._basic_cause_effect_analysis(
            phase=phase,
            known_tr_high=trading_range.get('high'),
            known_tr_low=trading_range.get('low'),
        )

        if trading_range.get("is_consolidation"):
            return self._analyze_cause_effect_in_range(trading_range, phase, basic_cause_effect, tr_story, current_close)
        else:
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
                "enhanced_analysis": {"trend_mode_cause_effect": trend_analysis, "tr_story": tr_story}
            }

    def _analyze_cause_effect_in_range(self, trading_range: dict, phase: str, basic_cause_effect: dict, tr_story: dict, current_close: float) -> dict:
        range_high = trading_range.get("high", current_close)
        range_low = trading_range.get("low", current_close * 0.95)
        range_duration = trading_range.get("duration_days", 60)
        df = self.data.tail(range_duration)
        avg_range_volume = df['Volume'].mean()
        total_range_volume = df['Volume'].sum()
        range_tightness = (range_high - range_low) / max((range_high + range_low) / 2, 1e-9)
        vol_ma20 = df['Volume_MA20'].mean() if 'Volume_MA20' in df.columns else avg_range_volume
        volume_participation = (avg_range_volume / vol_ma20) if vol_ma20 and vol_ma20 > 0 else 1.0

        accumulation_effort = {
            "time_effort": range_duration,
            "volume_effort": total_range_volume,
            "avg_volume": avg_range_volume,
            "volume_participation": round(volume_participation, 2),
            "price_consolidation": range_tightness,
            "cause_size": range_high - range_low,
            "effort_quality": "HIGH" if range_tightness < 0.15 else "MEDIUM" if range_tightness < 0.25 else "LOW"
        }

        current_position = trading_range.get("position", 0.5)
        cause = range_high - range_low

        try:
            return self._try_pnf_cause_effect(phase, range_high, range_low, tr_story, accumulation_effort, basic_cause_effect, current_position)
        except Exception as e:
            logger.warning(f"点数图计算失败，使用备用方法: {e}")

        return self._fallback_cause_effect(phase, range_high, range_low, range_duration, tr_story, accumulation_effort, basic_cause_effect, current_position, cause)

    def _try_pnf_cause_effect(self, phase, range_high, range_low, tr_story, accumulation_effort, basic_cause_effect, current_position):
        pnf_result = calculate_cause_effect_from_pnf(
            self.data, box_size_pct=1.0, reversal_boxes=3, phase=phase,
            known_tr_high=range_high, known_tr_low=range_low,
        )
        if pnf_result.get('horizontal_count', 0) >= 3:
            targets = pnf_result.get('targets', {})
            projected_direction = "UPSIDE" if pnf_result.get('breakout_direction') == 'up' else "DOWNSIDE"
            effect_probability = self._calculate_breakout_probability(phase, pnf_result.get('breakout_direction', 'up'))
            is_distribution_phase = 'Distribution' in phase or 'Markdown' in phase

            if is_distribution_phase and projected_direction == "DOWNSIDE":
                breakdown_detected = tr_story.get('breakdown', {}).get('detected', False)
                breakdown_point = range_low
                if not breakdown_detected:
                    cause_effect_interpretation = {
                        "method": "point_and_figure",
                        "current_situation": f"当前处于{phase}，点数图水平计数{pnf_result.get('horizontal_count', 0)}列",
                        "effort_assessment": f"积累/派发努力质量为{accumulation_effort['effort_quality']}",
                        "projected_direction": "DOWNSIDE_PENDING",
                        "breakout_probability": f"待破位激活（需跌破 {breakdown_point:.2f}）",
                        "target_projections": {
                            "status": "pending_breakdown",
                            "note": "威科夫理论约束：派发期的向下因果目标必须以跌破AR低点为激活条件",
                            "breakdown_threshold": float(round(breakdown_point, 2)),
                            "downside_targets_pending": targets,
                            "pnf_horizontal_count": pnf_result.get('horizontal_count', 0)
                        },
                        "wyckoff_logic": pnf_result.get('description', ''),
                        "theory": "威科夫因果法则：水平计数决定垂直目标（派发期需破位激活）"
                    }
                    return self._build_final_cause_effect_return(basic_cause_effect, accumulation_effort, cause_effect_interpretation, tr_story)

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
            return self._build_final_cause_effect_return(basic_cause_effect, accumulation_effort, cause_effect_interpretation, tr_story)
        return None

    def _fallback_cause_effect(self, phase, range_high, range_low, range_duration, tr_story, accumulation_effort, basic_cause_effect, current_position, cause):
        atr = self.data['ATR'].iloc[-1] if 'ATR' in self.data.columns else (range_high - range_low) / 5
        recent_data = self.data.tail(range_duration)
        atr_series = (recent_data['High'] - recent_data['Low']).rolling(window=5).mean()
        atr_start = atr_series.iloc[0] if len(atr_series) > 0 else 0
        atr_end = atr_series.iloc[-1] if len(atr_series) > 0 else 0
        volatility_contraction = 1 - (atr_end / atr_start) if atr_start > 0 else 0
        contraction_factor = max(0.5, 1 + volatility_contraction * 2)
        horizontal_potential = cause * contraction_factor * (range_duration / 30)
        is_distribution_phase = 'Distribution' in phase or 'Markdown' in phase
        is_downside_target = current_position <= 0.5
        needs_breakdown_validation = is_distribution_phase and is_downside_target

        if not needs_breakdown_validation:
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
        else:
            breakdown_detected = tr_story.get('breakdown', {}).get('detected', False)
            breakdown_point = range_low
            if not breakdown_detected:
                cause_effect_interpretation = {
                    "method": "volatility_contraction",
                    "current_situation": f"当前处于{phase}（TR下半部），波动率收缩{volatility_contraction*100:.1f}%",
                    "effort_assessment": f"积累/派发努力质量为{accumulation_effort['effort_quality']}",
                    "projected_direction": "DOWNSIDE_PENDING",
                    "breakout_probability": f"待破位激活（需跌破 {breakdown_point:.2f}）",
                    "target_projections": {
                        "status": "pending_breakdown",
                        "note": "威科夫理论约束：派发期的向下因果目标必须以跌破AR低点为激活条件",
                        "breakdown_threshold": float(round(breakdown_point, 2)),
                        "downside_targets_pending": {
                            "minimum_target": float(round(breakdown_point - horizontal_potential * 0.618, 2)),
                            "likely_target": float(round(breakdown_point - horizontal_potential, 2)),
                            "maximum_target": float(round(breakdown_point - horizontal_potential * 1.618, 2))
                        }
                    },
                    "wyckoff_logic": f"基于波动率收缩{volatility_contraction*100:.1f}%和{range_duration}天积累，预计{cause:.2f}点的派发努力",
                    "theory": "威科夫因果定律：派发期的目标需破位激活（书中明确要求）"
                }
                return self._build_final_cause_effect_return(basic_cause_effect, accumulation_effort, cause_effect_interpretation, tr_story)
            else:
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
        return self._build_final_cause_effect_return(basic_cause_effect, accumulation_effort, cause_effect_interpretation, tr_story)

    def _build_tr_story(self) -> dict:
        df = self.data
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
            "tr_range": {"resistance": round(high, 2), "support": round(low, 2), "width": round(width, 2)},
            "breakdown": {"detected": bool(broke_down), "downside_target_1": round(downside_target_1, 2) if downside_target_1 is not None else None},
            "dynamic_target_context": dynamic_path,
            "phase_mode": mode,
            "confidence_bias": confidence_bias
        }

    def _analyze_target_path_monitor(self, recent, support: float, target):
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

    def _build_final_cause_effect_return(self, basic_cause_effect: dict, accumulation_effort: dict, cause_effect_interpretation: dict, tr_story: dict) -> dict:
        return {
            "basic_analysis": basic_cause_effect,
            "enhanced_analysis": {
                "accumulation_distribution_effort": accumulation_effort,
                "projected_effects": cause_effect_interpretation,
                "tr_story": tr_story,
            }
        }

    def _calculate_breakout_probability(self, phase: str, direction: str) -> str:
        if "Accumulation" in phase and direction == "up":
            return "HIGH (75-85%)"
        elif "Distribution" in phase and direction == "down":
            return "HIGH (75-85%)"
        return "MEDIUM (50-65%)"

    def _basic_cause_effect_analysis(self, phase: str = '', known_tr_high: float = None, known_tr_low: float = None) -> dict:
        try:
            recent_data = self.data.tail(60)
            if known_tr_high is not None and known_tr_low is not None:
                trading_range_high = known_tr_high
                trading_range_low = known_tr_low
            else:
                trading_range_high = recent_data['High'].max()
                trading_range_low = recent_data['Low'].min()
            cause_size = trading_range_high - trading_range_low

            try:
                pnf_result = calculate_cause_effect_from_pnf(
                    self.data, box_size_pct=1.0, reversal_boxes=3, phase=phase,
                    known_tr_high=trading_range_high, known_tr_low=trading_range_low,
                )
                if pnf_result.get('horizontal_count', 0) >= 3:
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

            duration = 60
            atr = self.data['ATR'].iloc[-1] if 'ATR' in self.data.columns else (trading_range_high - trading_range_low) / 5
            atr_series = (recent_data['High'] - recent_data['Low']).rolling(window=5).mean()
            atr_start = atr_series.iloc[0] if len(atr_series) > 0 else 0
            atr_end = atr_series.iloc[-1] if len(atr_series) > 0 else 0
            volatility_contraction = 1 - (atr_end / atr_start) if atr_start > 0 else 0
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
