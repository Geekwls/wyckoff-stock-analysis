import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from ..config.settings import WyckoffConfig
from .utils import PhaseAdapter
from ..exceptions import InsufficientDataError, LawAnalysisError
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

        return {
            "overall_assessment": overall_assessment,
            "wyckoff_guidance": wyckoff_guidance,
            "timeframe_analysis": effort_result_analysis
        }

    def analyze_cause_effect_law_enhanced(self) -> dict:
        """Wyckoff第三定律：因果定律增强分析"""
        if self.data is None or len(self.data) < 60:
            raise InsufficientDataError("因果分析", required=60, actual=len(self.data) if self.data is not None else 0)

        # 获取基础因果分析 - 使用内置分析方法
        basic_cause_effect = self._basic_cause_effect_analysis()

        # 增强因果分析
        trading_range = self.pattern_detector.detect_trading_range()
        
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

            # 2. 预测"效果" - 基于Wyckoff理论的目标计算
            current_position = trading_range.get("position", 0.5)

            if current_position > 0.5:
                # 向上突破的因果预测
                breakout_point = range_high
                cause = range_high - range_low

                targets = {
                    "minimum_target": breakout_point + cause * 1.0,    # 保守目标
                    "likely_target": breakout_point + cause * 1.618,   # 黄金分割目标
                    "maximum_target": breakout_point + cause * 2.618    # 激进目标
                }

                projected_direction = "UPSIDE"
                effect_probability = self._calculate_breakout_probability(phase, "up")

            else:
                # 向下突破的因果预测
                breakdown_point = range_low
                cause = range_high - range_low

                targets = {
                    "minimum_target": breakdown_point - cause * 1.0,
                    "likely_target": breakdown_point - cause * 1.618,
                    "maximum_target": breakdown_point - cause * 2.618
                }

                projected_direction = "DOWNSIDE"
                effect_probability = self._calculate_breakout_probability(phase, "down")

            # 3. Wyckoff因果关系的解读
            cause_effect_interpretation = {
                "current_situation": f"当前处于{phase}，因果幅度为{cause:.2f}点",
                "effort_assessment": f"积累/派发努力质量为{accumulation_effort['effort_quality']}",
                "projected_direction": projected_direction,
                "breakout_probability": effect_probability,
                "target_projections": targets,
                "wyckoff_logic": f"根据Wyckoff因果定律，{cause:.2f}点的积累/派发努力，预计产生{targets['likely_target']:.2f}点的效果"
            }

            return {
                "basic_analysis": basic_cause_effect,
                "enhanced_analysis": {
                    "accumulation_distribution_effort": accumulation_effort,
                    "projected_effects": cause_effect_interpretation
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
                    "trend_mode_cause_effect": trend_analysis
                }
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

    def _basic_cause_effect_analysis(self) -> dict:
        """基础因果分析 - 作为fallback方法"""
        try:
            # 计算交易区间
            recent_data = self.data.tail(60)
            trading_range_high = recent_data['High'].max()
            trading_range_low = recent_data['Low'].min()
            cause_size = trading_range_high - trading_range_low

            # 计算目标位
            breakout_point = trading_range_high
            targets = {
                "target_1": breakout_point + cause_size * 0.618,
                "target_2": breakout_point + cause_size * 1.0,
                "target_3": breakout_point + cause_size * 1.618
            }

            return {
                "cause_size": cause_size,
                "breakout_point": breakout_point,
                "targets": targets,
                "current_position": (self.data['Close'].iloc[-1] - trading_range_low) / cause_size if cause_size > 0 else 0,
                "consolidation_duration_days": 60
            }
        except Exception as e:
            raise LawAnalysisError("因果分析", str(e)) from e
