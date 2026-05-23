import pandas as pd
import logging
from typing import Dict, Optional, Tuple
from ...exceptions import InsufficientDataError, LawAnalysisError
from ..point_and_figure import calculate_cause_effect_from_pnf
from ..weis_wave import WeisWaveGenerator
from ..signal_extractor import SignalExtractor, get_events_from_phase, get_cached_phase_result

logger = logging.getLogger(__name__)


class CauseEffectMixin:
    """第三定律：因果定律"""

    def _pnf_tr_col_start_idx(self) -> int:
        """P&F 水平计数时限制为当前 TR 窗口内的列。"""
        try:
            if not self.pattern_detector:
                return 0
            phase_result = get_cached_phase_result(self.pattern_detector)
            events = get_events_from_phase(phase_result)
            tr = SignalExtractor.get_event_dict(events, 'trading_range')
            if tr.get('range_start_idx') is not None:
                return int(tr['range_start_idx'])
            tr = self.pattern_detector.detect_trading_range()
            if tr.get('range_start_idx') is not None:
                return int(tr['range_start_idx'])
        except Exception:
            pass
        return 0

    def analyze_cause_effect_law_enhanced(self) -> dict:
        if self.data is None or len(self.data) < 60:
            raise InsufficientDataError("因果分析", required=60, actual=len(self.data) if self.data is not None else 0)

        trading_range = self.pattern_detector.detect_trading_range()
        tr_story = self._build_tr_story()
        current_close = self.data['Close'].iloc[-1]

        # P3 修复：将原本仅在 facade.py 中的 invalidated_tr 判定规则收拢到底层
        tr_low = trading_range.get('low', 0.0)
        tr_high = trading_range.get('high', 0.0)
        recent_data = self.data.tail(60) if self.data is not None else pd.DataFrame()
        recent_low = recent_data['Low'].min() if not recent_data.empty else 0.0
        
        if tr_low > 0 and recent_low < tr_low and current_close >= tr_low * 1.03:
            basic_cause_effect = {
                'method': 'invalidated_tr',
                'cause_bars': 0,
                'volatility_contraction': 0.0,
                'contraction_factor': 0.0,
                'description': "🚨 原交易区间参考性已下降：价格曾跌破原支撑位且已大幅收回，表明市场已找到新的需求抵抗，当前正在重建结构。根据威科夫原则，原区间已失效，必须暂停目标测算，等待新的有效 TR 形成。",
                'targets': {'target_1': 0.0, 'target_2': 0.0, 'target_3': 0.0},
                'theory': "威科夫区间失效原则",
                'tr_low': tr_low,
                'tr_high': tr_high,
                'current_price': current_close
            }
            enhanced = {
                "accumulation_distribution_effort": {
                    "time_effort": trading_range.get("duration_days", 60),
                    "price_consolidation": 0.0,
                    "cause_size": round(tr_high - tr_low, 2),
                    "effort_quality": "INVALIDATED",
                },
                "projected_effects": {
                    "method": "invalidated_tr",
                    "current_situation": f"原TR({tr_low:.2f}-{tr_high:.2f})曾跌破后收回，参考性下降",
                    "effort_assessment": "原TR已失效",
                    "projected_direction": "UNKNOWN",
                    "target_projections": {
                        "status": "pending_recalculation",
                        "note": "原交易区间参考价格已失效，暂停目标测算",
                        "old_tr_range": {"low": round(tr_low, 2), "high": round(tr_high, 2)},
                        "current_price": round(current_close, 2),
                    },
                    "wyckoff_logic": "原交易区间参考性已下降：价格曾跌破原支撑位且已大幅收回，暂停目标测算",
                    "theory": "威科夫区间失效原则"
                },
                "tr_story": tr_story
            }
            return {"basic_analysis": basic_cause_effect, "enhanced_analysis": enhanced}

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

        if trading_range.get("is_broken"):
            # TR 已被突破失效，标记旧目标为待重新锚定
            direction = trading_range.get("breakout_direction", "unknown")
            basic_cause_effect["targets"] = {"status": "pending_recalculation",
                "note": f"原TR({trading_range.get('low',0):.2f}-{trading_range.get('high',0):.2f})已被价格{direction}突破，旧目标已失效，需等待新TR形成或使用P&F重算"}
            return self._analyze_cause_effect_broken(trading_range, phase, basic_cause_effect, tr_story, current_close)
        elif trading_range.get("is_consolidation"):
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

    def _analyze_cause_effect_broken(self, trading_range: dict, phase: str, basic_cause_effect: dict, tr_story: dict, current_close: float) -> dict:
        """TR 已被突破失效时的因果分析 — 不计算新目标，标记旧目标失效"""
        direction = trading_range.get("breakout_direction", "unknown")
        old_low = trading_range.get("low", 0)
        old_high = trading_range.get("high", 0)
        cause_pct = (old_high - old_low) / old_low * 100 if old_low > 0 else 0

        trend_analysis = {
            "current_trend": phase,
            "current_price": current_close,
            "old_tr_range": f"{old_low:.2f} - {old_high:.2f}",
            "old_tr_width_pct": round(cause_pct, 2),
            "breakout_direction": direction,
            "cause_effect_status": "TR_BROKEN",
            "interpretation": f"原TR({old_low:.2f}-{old_high:.2f})已被{direction}突破，"
                             f"旧因果目标已失效。系统正在等待新TR形成以重新锚定目标。"
                             f"威科夫理论要求：TR被突破后，原区间不再作为因果测算基准。"
        }

        enhanced = {
            "accumulation_distribution_effort": {
                "time_effort": trading_range.get("duration_days", 60),
                "price_consolidation": round(cause_pct / 100, 4),
                "cause_size": round(old_high - old_low, 2),
                "effort_quality": "BROKEN",
            },
            "projected_effects": {
                "method": "tr_broken",
                "current_situation": f"原TR({old_low:.2f}-{old_high:.2f})已被{direction}突破，目标待重新锚定",
                "effort_assessment": "原TR已失效",
                "projected_direction": direction.upper(),
                "target_projections": {
                    "status": "pending_recalculation",
                    "note": "威科夫理论：TR被突破后原有目标立即失效，需等待新TR形成或P&F重算",
                    "old_tr_range": {"low": round(old_low, 2), "high": round(old_high, 2)},
                    "current_price": round(current_close, 2),
                },
                "wyckoff_logic": f"原TR({old_low:.2f}-{old_high:.2f})幅度{cause_pct:.1f}%，"
                                 f"已被价格{direction}突破至{current_close:.2f}，旧因果目标不再适用",
                "theory": "威科夫因果法则：TR被突破后原目标立即失效，需在新TR中重新水平计数",
            },
            "tr_story": tr_story,
            "trend_mode_cause_effect": trend_analysis,
        }
        return {"basic_analysis": basic_cause_effect, "enhanced_analysis": enhanced}

    def _try_pnf_cause_effect(self, phase, range_high, range_low, tr_story, accumulation_effort, basic_cause_effect, current_position):
        pnf_result = calculate_cause_effect_from_pnf(
            self.data, box_size_pct=1.0, reversal_boxes=3, phase=phase,
            known_tr_high=range_high, known_tr_low=range_low,
            tr_col_start_idx=self._pnf_tr_col_start_idx(),
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

        # 动态评估达成概率
        prob_res = self._calculate_breakout_probability_enhanced(phase, projected_direction.lower())
        
        cause_effect_interpretation = {
            "method": "volatility_contraction",
            "current_situation": f"当前处于{phase}，波动率收缩{volatility_contraction*100:.1f}%",
            "effort_assessment": f"积累/派发努力质量为{accumulation_effort['effort_quality']}",
            "projected_direction": projected_direction,
            "breakout_probability": prob_res['label'],
            "probability_value": prob_res['probability'],
            "probability_note": prob_res['note'],
            "target_projections": targets,
            "wyckoff_logic": f"基于波动率收缩{volatility_contraction*100:.1f}%和{range_duration}天积累，预计{cause:.2f}点的积累/派发努力",
            "theory": "因果定律进阶：基于突破质量的动态概率预测"
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
        # 因果监控路径：读缓存 phase，避免与 identify_phase 结论不一致
        events = get_events_from_phase(
            get_cached_phase_result(self.pattern_detector) if self.pattern_detector else None
        )
        upthrust = SignalExtractor.get_event_dict(events, 'upthrust')
        spring = SignalExtractor.get_event_dict(events, 'spring')
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

    def _calculate_breakout_probability_enhanced(self, phase: str, direction: str) -> dict:
        """
        P2 优化：基于突破质量动态评估因果目标达成概率
        """
        # 1. 基础概率 (基于威科夫阶段常态)
        base_prob = 0.6
        if ("Accumulation" in phase or "吸筹" in phase) and direction in ("up", "upside"):
            base_prob = 0.75
        elif ("Distribution" in phase or "派发" in phase) and direction in ("down", "downside"):
            base_prob = 0.75
            
        # 2. 突破质量加权 (JOC/FTI 质量)
        quality_score = 0
        joc = self.pattern_detector.detect_joc_menhongtao() if self.pattern_detector and hasattr(self.pattern_detector, 'detect_joc_menhongtao') else {}

        if joc.get('detected'):
            #  Weis Wave 波段累加量评估（替换原单K线降级方案）
            weis_quality = self._get_weis_wave_breakout_quality(joc.get('date'))
            quality_score = weis_quality.get('quality_score', 0)
                
        final_prob = base_prob + quality_score
        
        if final_prob >= 0.85:
            label = "高 (85-95%)"
        elif final_prob >= 0.7:
            label = "较高 (70-85%)"
        elif final_prob >= 0.5:
            label = "中 (50-70%)"
        else:
            label = "低 (<50%)"
            
        return {
            "probability": round(final_prob, 2),
            "label": label,
            "note": "基于突破波段质量(降级至单K线)动态评估" if quality_score != 0 else "基于阶段常态评估"
        }

    def _calculate_breakout_probability(self, phase: str, direction: str) -> str:
        res = self._calculate_breakout_probability_enhanced(phase, direction)
        return res['label']

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
                    tr_col_start_idx=self._pnf_tr_col_start_idx(),
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

            # P1 修复：派发/下跌阶段计算向下目标
            is_downside = 'Distribution' in phase or 'Markdown' in phase
            if is_downside:
                breakdown_point = trading_range_low
                targets = {
                    "target_1": round(breakdown_point - potential * 0.618, 2),
                    "target_2": round(breakdown_point - potential, 2),
                    "target_3": round(breakdown_point - potential * 1.618, 2)
                }
                description = f"派发/下跌因果：基于波动率收缩{volatility_contraction*100:.1f}%和{duration}天派发"
            else:
                breakout_point = trading_range_high
                targets = {
                    "target_1": round(breakout_point + potential * 0.618, 2),
                    "target_2": round(breakout_point + potential, 2),
                    "target_3": round(breakout_point + potential * 1.618, 2)
                }
                description = f"基于波动率收缩{volatility_contraction*100:.1f}%和{duration}天积累"
            return {
                "method": "volatility_contraction",
                "cause_size": cause_size,
                "volatility_contraction": round(volatility_contraction * 100, 1),
                "contraction_factor": round(contraction_factor, 2),
                "breakout_point": breakout_point if not is_downside else breakdown_point,
                "breakout_direction": "down" if is_downside else "up",
                "targets": targets,
                "current_position": (self.data['Close'].iloc[-1] - trading_range_low) / cause_size if cause_size > 0 else 0,
                "consolidation_duration_days": duration,
                "description": description,
                "theory": "威科夫因果法则：水平计数决定垂直目标" if not is_downside else "威科夫因果法则：派发期向下目标需破位激活"
            }
        except Exception as e:
            raise LawAnalysisError("因果分析", str(e)) from e


    def _get_weis_wave_breakout_quality(self, breakout_date: pd.Timestamp) -> dict:
        """
        使用 Weis Wave 波段累加量评估 JOC 突破质量

        威科夫理论（David Weis）：
        - 突破的质量应由整个波段的努力（累加量）决定，而非单根K线
        - 真正的突破需要波段量能配合

        Returns:
            {
                'wave_volume_ratio': 波段量比（相对于平均量）,
                'wave_thrust': 波段推力百分比,
                'quality_score': 质量得分 (-0.2 到 +0.15)
            }
        """
        try:
            # 生成 Weis Wave 波段
            wave_gen = WeisWaveGenerator(self.data, atr_multiplier=2.0, fallback_pct=0.03)
            waves = wave_gen.generate()

            if not waves:
                # 无波段数据，使用降级方案
                return {'quality_score': 0, 'note': 'no_waves_fallback'}

            # 找到包含突破日期的波段
            breakout_wave = None
            for wave in waves:
                if isinstance(wave.start_idx, pd.Timestamp) and isinstance(wave.end_idx, pd.Timestamp):
                    if wave.start_idx <= breakout_date <= wave.end_idx:
                        breakout_wave = wave
                        break
                else:
                    # 处理整数索引情况
                    if hasattr(self.data, 'loc'):
                        try:
                            wave_data = self.data.loc[wave.start_idx:wave.end_idx]
                            if breakout_date in wave_data.index:
                                breakout_wave = wave
                                break
                        except Exception:
                            pass

            if not breakout_wave:
                return {'quality_score': 0, 'note': 'breakout_not_in_wave'}

            # 计算波段量比
            avg_volume = self.data['Volume'].mean()
            wave_volume_ratio = breakout_wave.volume / avg_volume if avg_volume > 0 else 1.0

            # 波段推力已是百分比形式
            wave_thrust = breakout_wave.thrust

            # 质量评分逻辑（David Weis标准）
            quality_score = 0

            # 优质突破：大推力 + 放量
            if wave_thrust > 0.03 and wave_volume_ratio > 1.5:
                quality_score = 0.15
            # 中等突破
            elif wave_thrust > 0.02 and wave_volume_ratio > 1.2:
                quality_score = 0.08
            # 弱突破：推力不足 或 缩量
            elif wave_thrust < 0.01 or wave_volume_ratio < 0.8:
                quality_score = -0.15
            # 危险突破：缩量虚破
            elif wave_thrust < 0.015 and wave_volume_ratio < 0.6:
                quality_score = -0.2

            return {
                'wave_volume_ratio': round(wave_volume_ratio, 2),
                'wave_thrust': round(wave_thrust, 4),
                'quality_score': quality_score,
                'wave_direction': breakout_wave.direction,
                'wave_duration': breakout_wave.duration
            }

        except Exception as e:
            logger.warning(f"Weis Wave 质量评估失败，使用降级方案: {e}")
            return {'quality_score': 0, 'note': 'weis_fallback'}
