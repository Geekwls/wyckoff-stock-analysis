import logging
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional
from .enums import MarketEnvironment, MarketSide, WyckoffPhase
from .utils import PhaseAdapter
from ..schemas import (
    TradingPlanModel, StopLossModel, TargetsModel, 
    PositionSizingModel, RiskAdviceModel, RiskAdviceItem,
    SignalQualityModel
)
from ..config.settings import WyckoffConfig, WyckoffThresholds

logger = logging.getLogger(__name__)

class RecommendationEngine:
    """
    威科夫交易建议引擎 (P2 #2 - Enhanced)
    负责从检测结果中推导出交易计划和风险建议

    孟洪涛《新威科夫操盘法》核心原则：
    - 70% 等待：保持耐心，不强行交易
    - 20% 分析：深入研究市场结构
    - 10% 交易：只在高质量信号时行动
    """

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.thresholds = WyckoffThresholds()
        
        # 耐心状态追踪（实例级别，确保多标的并发沙箱隔离）
        self._patience_state = {
            'consecutive_weak_signals': 0,
            'last_signal_quality': None,
            'waiting_mode_active': False,
            'waiting_since': None,
        }

    def _calculate_patience_score(self, detected_keys: List[str], base_score: float, market_env: MarketEnvironment) -> tuple:
        """
        计算耐心评分（孟洪涛70%等待原则）

        Returns:
            (patience_penalty: float, patience_reasons: List[str], should_wait: bool)
        """
        patience_penalty = 0
        patience_reasons = []
        should_wait = False

        # 1. 检查是否有主要高质量信号
        high_quality_signals = {'spring', 'joc', 'fti'}
        medium_quality_signals = {'sos', 'sow', 'lps', 'lpsy'}
        has_high_quality = bool(detected_keys & high_quality_signals)
        has_medium_quality = bool(detected_keys & medium_quality_signals)

        # 2. 检查信号数量是否过少
        if len(detected_keys) == 0:
            patience_penalty = 0
            patience_reasons.append("无检测信号，保持耐心等待")
        elif len(detected_keys) == 1 and not has_high_quality:
            patience_penalty = -15
            patience_reasons.append("单一信号且非高质量，建议等待更多确认")
            should_wait = True
        elif len(detected_keys) <= 2 and not has_high_quality:
            patience_penalty = -8
            patience_reasons.append("信号数量不足且缺少核心信号，耐心等待")
            should_wait = True

        # 3. 检查基础分数是否过低
        if base_score < 25:
            patience_penalty -= 10
            patience_reasons.append(f"基础分数{base_score}较低，不符合孟洪涛10%交易原则")
            should_wait = True
        elif base_score < 40:
            patience_penalty -= 5
            patience_reasons.append("信号质量中等，建议提高入场门槛")

        # 4. 检查市场环境是否适合交易
        if market_env == MarketEnvironment.RANGE_BOUND:
            if not has_high_quality:
                patience_penalty -= 5
                patience_reasons.append("震荡市场且无高质量信号，建议等待")
                should_wait = True
        elif market_env == MarketEnvironment.UNKNOWN:
            patience_penalty -= 8
            patience_reasons.append("多空信号混杂，建议等待市场明确方向")
            should_wait = True

        # 5. 检查是否处于等待期（连续弱信号）
        if base_score < 50:
            self._patience_state['consecutive_weak_signals'] += 1
            if self._patience_state['consecutive_weak_signals'] >= 3:
                patience_penalty -= 10
                patience_reasons.append(f"连续{self._patience_state['consecutive_weak_signals']}次低质量分析，进入耐心等待模式")
                self._patience_state['waiting_mode_active'] = True
                if self._patience_state['waiting_since'] is None:
                    from datetime import datetime
                    self._patience_state['waiting_since'] = datetime.now()
                should_wait = True
        else:
            # 高质量信号重置计数器
            self._patience_state['consecutive_weak_signals'] = 0
            if has_high_quality:
                self._patience_state['waiting_mode_active'] = False

        # 6. 检查是否处于等待激活期
        if self._patience_state['waiting_mode_active']:
            patience_penalty -= 15
            patience_reasons.append("系统处于耐心等待模式，只接受Spring/JOC级别的超高质量信号")
            should_wait = True

        return patience_penalty, patience_reasons, should_wait

    @staticmethod
    def _get_attr(obj: Any, key: str, default=None):
        """
        安全获取属性，支持字典和Pydantic模型

        Args:
            obj: 对象（字典或Pydantic模型）
            key: 属性名
            default: 默认值

        Returns:
            属性值或默认值
        """
        if obj is None:
            return default
        # 如果是Pydantic模型，使用getattr
        if hasattr(obj, 'model_dump'):
            return getattr(obj, key, default)
        # 如果是字典，使用get方法
        if isinstance(obj, dict):
            return obj.get(key, default)
        # 其他情况，使用getattr
        return getattr(obj, key, default)

    @staticmethod
    def _is_bearish_signal_absorbed(signal_type: str, signal_info: Any, data: Any) -> bool:
        """
        检查看空信号是否已被价格吸收（失效）

        威科夫理论：如果价格突破看空信号的价格位一定幅度（如15%），
        且保持在该水平上方，则说明该看空信号已被需求吸收，不再有效。

        Args:
            signal_type: 信号类型 ('sow', 'lpsy', 'upthrust')
            signal_info: 信号信息
            data: 价格数据

        Returns:
            True表示信号已被吸收，不应计入冲突评分
        """
        try:
            # 获取信号价格
            signal_price = RecommendationEngine._get_attr(signal_info, 'price', 0)
            if signal_price <= 0:
                return False

            # 获取当前价格
            if not hasattr(data, 'Close'):
                return False
            current_price = data['Close'].iloc[-1]

            # 计算价格上涨幅度
            price_gain_pct = (current_price / signal_price) - 1

            #  修复：降低阈值，15%上涨即认为信号已被吸收
            if price_gain_pct > 0.15:  # 上涨超过15%
                # 进一步检查：是否真正突破（不仅仅是短暂上冲）
                # 检查最近N天的收盘价，大部分维持在信号价格上方即可
                lookback = min(20, len(data))
                recent_closes = data['Close'].iloc[-lookback:]

                #  修复：改为80%的天数在信号价格上方即可（更宽松）
                days_above = (recent_closes > signal_price * 1.02).sum()  # 102%信号价格以上
                pct_above = days_above / len(recent_closes)

                if pct_above >= 0.80:  # 80%的天数在上方
                    logger.info(
                        f"Bearish signal {signal_type} at {signal_price:.2f} ABSORBED: "
                        f"current {current_price:.2f} (+{price_gain_pct*100:.1f}%), "
                        f"{days_above}/{lookback} days above, {pct_above*100:.0f}%"
                    )
                    return True

            return False
        except Exception as e:
            logger.debug(f"Error checking if signal absorbed: {e}")
            return False

    def calculate_weighted_score(self, data: Any, pattern_results: Dict[str, Any], market_env: MarketEnvironment) -> SignalQualityModel:
        """
        计算高级加权评分 (v2.1校准：修正Phase E冲突惩罚，提升基础分)
        """
        # 兼容性转换：如果 pattern_results 是字典，且包含 'events_detected'，则从中提取核心事件和属性
        if isinstance(pattern_results, dict):
            events = pattern_results.get('events_detected') or pattern_results
            seq_val = pattern_results.get('sequence_validation')
            boring = pattern_results.get('boring_zone')
        else:
            events = pattern_results
            seq_val = getattr(pattern_results, 'sequence_validation', None)
            boring = getattr(pattern_results, 'boring_zone', None)

        if not events:
            return SignalQualityModel(score=0, max_score=100, confidence="低", reasons=["未检测到有效信号"])
            
        base_score = 0.0
        reasons = []
        weights = self.thresholds.QUALITY_WEIGHTS
        
        important_signals = [
            ('joc', 40),
            ('spring', 35),
            ('sos', 25),
            ('lps', 15),
            ('upthrust', 35),
            ('sow', 25),
            ('lpsy', 15),
            ('fti', 40),
            ('secondary_test', 20),
            ('automatic_reaction', 15)
        ]

        bullish_count = 0
        bearish_count = 0
        has_major_signal = False  # 是否至少有1个主要交易信号
        detected_keys = []

        for key, max_weight in important_signals:
            info = getattr(events, key, None)

            if not info or not self._get_attr(info, 'detected'): continue

            detected_keys.append(key)
            if key in ('spring', 'sos', 'sow', 'joc', 'fti', 'upthrust'):
                has_major_signal = True

            if key in ['sow', 'lpsy', 'upthrust']:
                if self._is_bearish_signal_absorbed(key, info, data):
                    reasons.append(f"过时信号{key.upper()}已失效不计入冲突")
                    continue

            if key in ['joc', 'spring', 'sos', 'lps', 'automatic_reaction']:
                bullish_count += 1
            elif key in ['fti', 'upthrust', 'sow', 'lpsy', 'secondary_test']:
                phase_str = getattr(pattern_results, 'phase', None) or 'Unknown'
                if 'Distribution' in phase_str or '派发' in phase_str:
                    bearish_count += 1
                elif 'Accumulation' in phase_str or '吸筹' in phase_str:
                    bullish_count += 1

            quality_factor = 1.0

            if key == 'secondary_test':
                st_vol_ratio = self._get_attr(info, 'st_vol_ratio', None)
                supply_exhausted = self._get_attr(info, 'supply_exhausted', False)
                if supply_exhausted:
                    quality_factor += 0.3
                    reasons.append(f"ST确认需求耗尽（量为高潮量的{st_vol_ratio:.0%}）")
                elif st_vol_ratio and st_vol_ratio < 0.6:
                    quality_factor += 0.1
                    reasons.append(f"ST接近确认（量为高潮量的{st_vol_ratio:.0%}）")
            elif key == 'automatic_reaction':
                rebound_pct = self._get_attr(info, 'rebound_pct', None)
                decline_pct = self._get_attr(info, 'decline_pct', None)
                if rebound_pct and rebound_pct > 0.03:
                    quality_factor += 0.15
                    reasons.append(f"AR自然反弹强劲（{rebound_pct*100:.1f}%）")
                elif decline_pct and decline_pct < -0.03:
                    quality_factor += 0.15
                    reasons.append(f"AR自然回落充分（{decline_pct*100:.1f}%）")
            else:
                vol_ratio = self._get_attr(info, 'volume_ratio', 1.0)
                if vol_ratio > 1.5:
                    quality_factor += weights['volume_ratio']
                    reasons.append(f"{key.upper()} 成交量强力确认")

            conf = self._get_attr(info, 'confidence', 0.5)
            quality_factor += (conf - 0.5) * weights['confidence']

            sig_date = self._get_attr(info, 'date')
            if sig_date:
                if isinstance(sig_date, str):
                    try: sig_date = datetime.strptime(sig_date, '%Y-%m-%d')
                    except Exception:
                        pass

                if isinstance(sig_date, datetime):
                    from datetime import timezone
                    now = datetime.now(timezone.utc) if sig_date.tzinfo else datetime.now()
                    try:
                        days_ago = (now - sig_date).days
                    except Exception:
                        if sig_date.tzinfo:
                            sig_date = sig_date.replace(tzinfo=None)
                        now = datetime.now()
                        days_ago = (now - sig_date).days

                    decay = np.exp(-0.693 * max(0, days_ago) / self.thresholds.TIME_DECAY_HALF_LIFE)
                    quality_factor *= decay
                    if decay < 0.7: reasons.append(f"{key.upper()} 信号已过最佳期 (衰减)")

            base_score += max_weight * min(quality_factor, 1.5)

        # --- 事件序列验证加成 ---
        seq_score = RecommendationEngine._get_attr(seq_val, 'sequence_score', {}) or {}
        seq_rating = seq_score.get('rating', '') if isinstance(seq_score, dict) else getattr(seq_score, 'rating', '')
        if seq_rating == 'A':
            base_score += 15
            reasons.append("事件序列完整(评级A)：SC→AR→ST→Spring→SOS→LPS→JOC 链条完整 (+15分)")
        elif seq_rating == 'B':
            base_score += 10
            reasons.append("事件序列较完整(评级B)：大部分关键事件已检测到 (+10分)")
        elif seq_rating == 'C':
            base_score += 5
            reasons.append("事件序列部分检测(评级C)：存在部分事件但链条不完整 (+5分)")

        # Spring 前置结构质量加分
        spring_val = RecommendationEngine._get_attr(seq_val, 'spring', {}) or {}
        if (spring_val.get('quality') if isinstance(spring_val, dict) else getattr(spring_val, 'quality', None)) == 'high':
            base_score += 10
            reasons.append("Spring有完整SC→AR→ST前置结构，信号质量高 (+10分)")
        elif (spring_val.get('quality') if isinstance(spring_val, dict) else getattr(spring_val, 'quality', None)) == 'medium':
            base_score += 5
            reasons.append("Spring有部分前置结构，质量中等 (+5分)")

        # 多次ST递减量缩加分 (Phase B积累确认)
        st_res = RecommendationEngine._get_attr(events, 'secondary_test')
        if st_res and self._get_attr(st_res, 'detected'):
            test_count = self._get_attr(st_res, 'test_count', 1)
            st_trend = self._get_attr(st_res, 'st_sequence_trend', 'stable')
            if test_count >= 3 and st_trend == 'declining':
                base_score += 10
                reasons.append(f"多次ST({test_count}次)量递减：供应被持续吸收 (+10分)")
            elif test_count >= 2:
                base_score += 3
                reasons.append(f"多次ST({test_count}次)确认区间 (+3分)")

        # PS→SC序列确认加分 (Phase A完整结构)
        ps_res = RecommendationEngine._get_attr(events, 'preliminary_support')
        if ps_res and self._get_attr(ps_res, 'detected'):
            sc_after = self._get_attr(ps_res, 'sc_confirmed_after', False)
            if sc_after:
                base_score += 8
                reasons.append("PS→SC链条确认：初次支撑后有效恐慌抛售，Phase A结构完整 (+8分)")

        # 序列矛盾扣分
        seq_conflicts = (RecommendationEngine._get_attr(seq_val, 'conflicts', []) or []) if seq_val else []
        for conflict in seq_conflicts:
            base_score -= 10
            reasons.append(f"序列矛盾: {conflict} (-10分)")

        # --- 孟洪涛进阶信号：枯燥区与死角突破 ---
        boring_score = self._get_attr(boring, 'score', 0)
        if self._get_attr(boring, 'detected'):
            base_score += 10
            reasons.append(f"检测到「枯燥区」(得分:{boring_score})，主力可能正在吸筹")

            # Boring Zone 联动加权 (P2 #3.1)
            if boring_score > 85:
                for key in ['spring', 'joc']:
                    info = getattr(events, key, None)
                    if info and self._get_attr(info, 'detected'):
                        base_score += 15 # 高质量枯燥区后的突破极具爆发力
                        reasons.append(f"🔥 高价值突破：{key.upper()} 紧随高质量枯燥区出现，爆发潜力极大")

            if self._get_attr(boring, 'high_alert'):
                reasons.append("🔥 高能预警：系统已进入「死角突破」严密监控模式")

        dead_corner = RecommendationEngine._get_attr(events, 'dead_corner_breakout') or {}
        skip_conflict_penalty = False
        if dead_corner.get('detected'):
            base_score += 25
            skip_conflict_penalty = True
            reasons.append("🎯 发现“死角突破”信号！从枯燥区放量跃起，极具爆发力，豁免历史冲突惩罚")

        # SOS/Upthrust 交叉验证（模糊区间）
        has_sos = 'sos' in detected_keys
        has_upthrust = 'upthrust' in detected_keys
        if has_sos and has_upthrust and not skip_conflict_penalty:
            is_uncertain = market_env in (MarketEnvironment.RANGE_BOUND, MarketEnvironment.UNKNOWN)
            if is_uncertain:
                base_score -= 15
                reasons.append("模糊区间内SOS与Upthrust同时出现，信号冲突 (-15分)")
            else:
                base_score -= 8
                reasons.append("SOS与Upthrust信号冲突 (-8分)")

        # --- 孟洪涛耐心评分（70%等待原则） ---
        patience_penalty, patience_reasons, should_wait = self._calculate_patience_score(
            set(detected_keys), base_score, market_env
        )
        base_score += patience_penalty
        reasons.extend(patience_reasons)
        if should_wait and base_score < 50:
            reasons.append("🕰️ 孟洪涛原则：当前处于70%等待期，建议耐心等待高质量信号")

        # --- 冲突惩罚 (v2.1校准) ---
        if bullish_count > 0 and bearish_count > 0 and not skip_conflict_penalty:
            phase_str = getattr(pattern_results, 'phase', None) or 'Unknown'

            # Phase E/Markup中SOW是正常回调，不应惩罚
            is_phase_e = ('Phase E' in phase_str or 'Markup' in phase_str or 'Markdown' in phase_str)
            dominant_ratio = max(bullish_count, bearish_count) / max(1, min(bullish_count, bearish_count))

            if is_phase_e:
                reasons.append(f"Phase E/M趋势推进中，混合信号属于正常回调 (+0分)")
            elif dominant_ratio >= 2:
                base_score -= 5
                reasons.append(f"主力方向明确(比例{dominant_ratio:.0f}:1)，混合信号轻微扣分 (-5分)")
            elif ('Phase A' in phase_str or 'Phase B' in phase_str or
                  ('Accumulation' in phase_str and bullish_count > bearish_count) or
                  ('Distribution' in phase_str and bearish_count > bullish_count)):
                base_score -= 10
                reasons.append(f"阶段过渡期信号混合 (轻微扣分 -10分，符合威科夫理论)")
            else:
                base_score -= self.thresholds.CONFLICT_PENALTY
                reasons.append(f"检测到多空信号冲突 (惩罚 -{self.thresholds.CONFLICT_PENALTY}分)")

        # --- 市场环境加成 (v2.1校准：仅极端不匹配扣分) ---
        phase_str = getattr(pattern_results, 'phase', None) or 'Unknown'
        current_side = PhaseAdapter.get_market_side(phase_str)
        is_market_strong_bullish = market_env == MarketEnvironment.STRONG_BULL
        is_market_strong_bearish = market_env == MarketEnvironment.STRONG_BEAR
        is_market_bullish = market_env in [MarketEnvironment.STRONG_BULL, MarketEnvironment.BULL]
        is_market_bearish = market_env in [MarketEnvironment.STRONG_BEAR, MarketEnvironment.BEAR]

        # 多头方向
        if is_market_strong_bullish and current_side == MarketSide.BULLISH:
            base_score += 15
            reasons.append("顺应大盘强势多头环境 (+15分)")
        elif is_market_bullish and current_side == MarketSide.BULLISH:
            base_score += 8
            reasons.append("顺应大盘多头环境 (+8分)")
        elif is_market_strong_bearish and current_side == MarketSide.BULLISH:
            base_score -= 10
            reasons.append("大盘强势空头环境不利于做多 (-10分)")

        # 空头方向
        if is_market_strong_bearish and current_side == MarketSide.BEARISH:
            base_score += 15
            reasons.append("顺应大盘强势空头环境 (+15分)")
        elif is_market_bearish and current_side == MarketSide.BEARISH:
            base_score += 8
            reasons.append("顺应大盘空头环境 (+8分)")
        elif is_market_strong_bullish and current_side == MarketSide.BEARISH:
            base_score -= 10
            reasons.append("大盘强势多头环境不利于做空 (-10分)")

        # --- v2.1校准：保底分 ---
        final_score = int(max(0, min(base_score, 100)))

        # 保底：至少有一个主要信号(Spring/SOS/SOW/JOC/FTI/Upthrust) + 有AR+ST结构 = 不低于15分
        if final_score < 15 and has_major_signal and len(detected_keys) >= 3:
            final_score = 15
            reasons.append("检测到主要Wyckoff信号及完整前置结构 (校准保底 15分)")

        # 保底：有Spring/JOC/SOS且有完整序列 → 不低于25
        has_primary_entry = any(k in detected_keys for k in ['spring', 'joc', 'sos', 'sow', 'fti', 'upthrust'])
        if final_score < 25 and has_primary_entry and seq_rating in ['A', 'B']:
            final_score = 25
            reasons.append("主要入场信号+完整序列结构 (校准保底 25分)")

        if final_score < 10 and seq_rating in ['A', 'B'] and not has_primary_entry:
            missing_signals = []
            phase_str = getattr(pattern_results, 'phase', None) or 'Unknown'

            if 'Accumulation' in phase_str or '吸筹' in phase_str:
                if not self._get_attr(events.spring, 'detected'):
                    missing_signals.append('Spring震仓')
                if not self._get_attr(events.sos, 'detected'):
                    missing_signals.append('SOS强势信号')
            elif 'Distribution' in phase_str or '派发' in phase_str:
                if not self._get_attr(events.sow, 'detected'):
                    missing_signals.append('SOW弱势信号')
                if not self._get_attr(events.lpsy, 'detected'):
                    missing_signals.append('LPSY最后支撑')

            if missing_signals:
                reasons.append(f"虽有完整{seq_rating}级序列结构，但缺少核心交易信号：{', '.join(missing_signals)}。当前处于{phase_str}，信号尚未成熟，建议等待关键确认出现。")

        if self._get_attr(boring, 'score', 0) >= 85 and final_score < 85:
            final_score = 85
            reasons.append("触发高能预警阈值，综合评分上调至 85 (死角突破临界)")
            
        if dead_corner.get('detected') and final_score < 85:
            final_score = 85
            reasons.append("🎯 死角突破确立，综合评分强制托底至 85 (极高置信度)")

        return SignalQualityModel(
            score=final_score,
            max_score=100,
            confidence="极高" if final_score >= 80 else "高" if final_score >= 55 else "中" if final_score >= 25 else "低",
            reasons=reasons
        )

    def calculate_signal_quality(self, data: Any, pattern_results: Dict[str, Any], market_env: MarketEnvironment) -> SignalQualityModel:
        """兼容旧接口，内部调用加权评分"""
        return self.calculate_weighted_score(data, pattern_results, market_env)

    @staticmethod
    def calculate_signal_strength(pattern_results: Dict[str, Any]) -> int:
        """计算基础信号强度 (简单计数，仅为兼容性保留)"""
        events = pattern_results  # EventsModel — 直接使用属性访问
        count = 0
        for key in ['joc', 'spring', 'sos', 'lps', 'upthrust', 'sow', 'lpsy', 'fti']:
            event = getattr(events, key, None)
            if event and RecommendationEngine._get_attr(event, 'detected'):
                count += 1
        return count

    def generate_trading_plan(self, data: Any, pattern_results: Dict[str, Any], targets: Dict[str, Any]) -> TradingPlanModel:
        """
        生成具体交易计划 (威科夫结构导向止损 + Phase风险导向仓位)

        止损原则 (Wyckoff 操盘法):
          - 做多保守止损 = Spring低点下方, 激进止损 = 最近摆动低点下方
          - 做空保守止损 = Upthrust高点上方, 激进止损 = 最近摆动高点上方

        仓位原则 (Wyckoff 操盘法):
          - Phase A-B: 25-35% 常规仓位 (早期高风险)
          - Phase D:   75-100% 常规仓位 (最优入场区)
          - Phase E:   50-75% 常规仓位 (趋势已确立但部分走完)
          - Re-accumulation/Re-distribution: 50-75% (较短区间的较小因果)
        """
        # 兼容性处理：如果 pattern_results 是字典，且包含 'events_detected'，则从中提取核心事件
        if isinstance(pattern_results, dict):
            events = pattern_results.get('events_detected') or pattern_results
        else:
            events = pattern_results

        current_price = data['Close'].iloc[-1]
        joc = RecommendationEngine._get_attr(events, 'joc') or {}
        spring = RecommendationEngine._get_attr(events, 'spring') or {}
        upthrust = RecommendationEngine._get_attr(events, 'upthrust') or {}
        fti = RecommendationEngine._get_attr(events, 'fti') or {}
        sow = RecommendationEngine._get_attr(events, 'sow') or {}
        sos = RecommendationEngine._get_attr(events, 'sos') or {}
        tr = RecommendationEngine._get_attr(events, 'trading_range') or {}

        # 提前提取 ATR 供所有分支使用
        atr_val = float(data['ATR'].iloc[-1]) if 'ATR' in data.columns else current_price * 0.03

        def _get_swing_low(window: int = 20) -> float:
            return float(data['Low'].tail(window).min())

        def _get_swing_high(window: int = 20) -> float:
            return float(data['High'].tail(window).max())

        def _get_spring_low(sp_obj) -> float:
            if not sp_obj: return 0.0
            latest = getattr(sp_obj, 'latest_spring', None)
            if not latest:
                signals = getattr(sp_obj, 'signals', [])
                latest = signals[-1] if signals else None
            if not latest: return 0.0
            return float(getattr(latest, 'breakdown_price', None) or getattr(latest, 'price', 0))

        def _get_upthrust_high(ut_obj) -> float:
            if not ut_obj: return 0.0
            latest = getattr(ut_obj, 'latest_upthrust', None)
            if not latest:
                signals = getattr(ut_obj, 'upthrusts', [])
                latest = signals[-1] if signals else None
            if not latest: return 0.0
            return float(getattr(latest, 'breakout_price', None) or getattr(latest, 'price', 0))

        direction = "观望"
        zone = "等待形态确认"
        stop = StopLossModel(conservative=0.0, aggressive=0.0)
        phase_str = getattr(pattern_results, 'phase', None) or 'Unknown'

        def _get_lps_low(window: int = 15) -> float:
            return float(data['Low'].tail(window).min())
            
        def _get_lpsy_high(window: int = 15) -> float:
            return float(data['High'].tail(window).max())

        # ── 方向判断 (结构导向刚性止损) ──
        if joc.get('detected'):
            direction = "做多"
            creek = joc.get('creek_level', current_price)
            zone = f"{creek:.2f} 附近 (JOC突破)"
            lps_low = _get_lps_low(15)
            # 刚性锚定 Creek 下沿或 LPS 支撑低点
            cons_stop = min(lps_low, creek * 0.99)
            stop = StopLossModel(
                conservative=round(cons_stop, 2),
                aggressive=round(creek * 0.995, 2), # 紧贴小溪下沿，一旦漏水立刻止损
                atr_dynamic_stop=round(cons_stop - atr_val * 0.5, 2),
            )
        elif spring.get('detected'):
            direction = "做多"
            spring_low = _get_spring_low(spring)
            if spring_low <= 0:
                spring_low = current_price * 0.95
            zone = f"{current_price:.2f} 附近 (Spring震仓)"
            # 刚性止损：跌破 Spring 极值点则结构失效
            stop = StopLossModel(
                conservative=round(spring_low * 0.99, 2),
                aggressive=round(spring_low * 0.995, 2),
                atr_dynamic_stop=round(spring_low - atr_val * 0.5, 2),
            )
        elif sos.get('detected') and not joc.get('detected') and not spring.get('detected'):
            direction = "做多"
            sos_price = getattr(sos, 'price', current_price) or current_price
            zone = f"{sos_price:.2f} 附近 (SOS突破)"
            lps_low = _get_lps_low(15)
            cons_stop = min(lps_low, sos_price * 0.99)
            stop = StopLossModel(
                conservative=round(cons_stop, 2),
                aggressive=round(sos_price * 0.995, 2),
                atr_dynamic_stop=round(cons_stop - atr_val * 0.5, 2),
            )
        elif fti.get('detected'):
            direction = "做空"
            ice = fti.get('ice_level', current_price)
            zone = f"{ice:.2f} 附近 (FTI跌破)"
            lpsy_high = _get_lpsy_high(15)
            cons_stop = max(lpsy_high, ice * 1.01)
            stop = StopLossModel(
                conservative=round(cons_stop, 2),
                aggressive=round(ice * 1.005, 2), # 紧贴冰层上沿，一旦涨回立刻止损
                atr_dynamic_stop=round(cons_stop + atr_val * 0.5, 2),
            )
        elif upthrust.get('detected'):
            direction = "做空"
            ut_high = _get_upthrust_high(upthrust)
            if ut_high <= 0:
                ut_high = current_price * 1.05
            zone = f"{current_price:.2f} 附近 (Upthrust诱多)"
            # 刚性止损：突破 Upthrust 极值点则结构失效
            stop = StopLossModel(
                conservative=round(ut_high * 1.01, 2),
                aggressive=round(ut_high * 1.005, 2),
                atr_dynamic_stop=round(ut_high + atr_val * 0.5, 2),
            )
        elif sow.get('detected') and not fti.get('detected') and not upthrust.get('detected'):
            direction = "做空"
            sow_price = getattr(sow, 'price', current_price) or current_price
            zone = f"{sow_price:.2f} 附近 (SOW跌破)"
            lpsy_high = _get_lpsy_high(15)
            cons_stop = max(lpsy_high, sow_price * 1.01)
            stop = StopLossModel(
                conservative=round(cons_stop, 2),
                aggressive=round(sow_price * 1.005, 2),
                atr_dynamic_stop=round(cons_stop + atr_val * 0.5, 2),
            )

        # ── 仓位建议 (Phase+风险导向) ──
        def _phase_position_sizing(phase_str: str, normal_position_pct: float = 10.0) -> tuple:
            is_reaccum = 'Reaccumulation' in phase_str or '再积累' in phase_str
            is_redistr = 'Redistribution' in phase_str or '再派发' in phase_str
            if 'Phase A' in phase_str or 'Phase B' in phase_str:
                factor = 0.30   # 25-35%: 早期高风险
            elif 'Phase D' in phase_str:
                factor = 0.875  # 75-100%: 最优入场区
            elif 'Phase E' in phase_str:
                factor = 0.625  # 50-75%: 趋势已确立
            elif is_reaccum or is_redistr:
                factor = 0.625
            else:
                factor = 0.50
            return (
                f"{normal_position_pct * factor:.0f}% (Phase导向)",
                f"{normal_position_pct * min(factor + 0.15, 1.0):.0f}% (Phase导向)",
                f"{normal_position_pct * min(factor + 0.30, 1.0):.0f}% (Phase导向)",
            )

        cons, mod, aggr = _phase_position_sizing(phase_str)
        pos_sizing = PositionSizingModel(
            conservative=cons, moderate=mod, aggressive=aggr
        )

        is_phase_ab = 'Phase A' in phase_str or 'Phase B' in phase_str
        is_phase_e = 'Phase E' in phase_str
        is_markup_markdown = 'Markup' in phase_str or 'Markdown' in phase_str
        if is_phase_ab:
            holding_period = "1-3个月 (波段)"
        elif is_phase_e:
            holding_period = "2-6周 (中线)"
        elif is_markup_markdown:
            holding_period = "2-8周 (中线)"
        else:
            holding_period = "1-2个月 (波段)"

        return TradingPlanModel(
            direction=direction,
            entry_zone=zone,
            stop_loss=stop,
            targets=TargetsModel(target_1=targets.get('target_1', 0), target_2=targets.get('target_2', 0)),
            position_sizing=pos_sizing,
            holding_period=holding_period,
        )

    def generate_risk_advice(self, quality: SignalQualityModel, plan: TradingPlanModel,
                             has_conflict: bool = False, conflict_details: str = "",
                             market_env: MarketEnvironment = None, data: Any = None) -> RiskAdviceModel:
        """
        生成分层风险建议 (Enhanced with volatility check and conflict detection)

        重要理论约束：
        - 当跨周期冲突时，所有方向的交易建议都应被抑制
        - 顺周线试错拿货（等Spring），优于逆周线试错砸盘（等LPSY）

        🔧 问题二修复：增加市场环境与交易方向的一致性检查
        - 做空 + 强多头环境 → 绝对观望
        - 做多 + 强多头环境 → 顺水推舟，降低观望阈值
        """
        score = getattr(quality, 'score', None) or (quality.get('score') if isinstance(quality, dict) else 0)
        direction = getattr(plan, 'direction', None) or (plan.get('direction') if isinstance(plan, dict) else "观望")

        #  新增：检查方向与环境的冲突
        direction_env_conflict = False
        direction_env_match = False
        if market_env:
            is_market_bullish = market_env in [MarketEnvironment.STRONG_BULL, MarketEnvironment.BULL]
            is_market_bearish = market_env in [MarketEnvironment.STRONG_BEAR, MarketEnvironment.BEAR]

            if direction == "做空" and is_market_bullish:
                direction_env_conflict = True  # 做空 + 强多头 = 冲突
            elif direction == "做多" and is_market_bearish:
                direction_env_conflict = True  # 做多 + 强空头 = 冲突
            elif direction == "做多" and is_market_bullish:
                direction_env_match = True  # 做多 + 强多头 = 匹配
            elif direction == "做空" and is_market_bearish:
                direction_env_match = True  # 做空 + 强空头 = 匹配

        # 安全获取属性辅助函数
        def _safe_get_stop(p_obj, field):
            stop_obj = getattr(p_obj, 'stop_loss', None) or (p_obj.get('stop_loss') if isinstance(p_obj, dict) else None)
            if not stop_obj: return 0.0
            if isinstance(stop_obj, dict):
                return float(stop_obj.get(field, 0.0))
            return float(getattr(stop_obj, field, 0.0))

        def _safe_get_pos(p_obj, field):
            pos_obj = getattr(p_obj, 'position_sizing', None) or (p_obj.get('position_sizing') if isinstance(p_obj, dict) else None)
            if not pos_obj: return "0%"
            if isinstance(pos_obj, dict):
                return str(pos_obj.get(field, "0%"))
            return str(getattr(pos_obj, field, "0%"))

        # 刚性止损提示说明
        stop_desc = "无明确止损"
        cons_stop_val = _safe_get_stop(plan, 'conservative')
        if direction == "做多" and cons_stop_val > 0:
            stop_desc = f"严格设于结构支撑/Spring极值点下方 {cons_stop_val:.2f} (结构失效位)"
        elif direction == "做空" and cons_stop_val > 0:
            stop_desc = f"严格设于结构阻力/Upthrust极值点上方 {cons_stop_val:.2f} (结构失效位)"

        def get_item(mode: str) -> RiskAdviceItem:
            # 获取或动态计算对应的仓位
            has_explicit_pos = False
            if plan and isinstance(plan, dict) and 'position_sizing' in plan:
                has_explicit_pos = True
            elif plan and hasattr(plan, 'position_sizing') and getattr(plan, 'position_sizing') is not None:
                has_explicit_pos = True

            if not has_explicit_pos:
                # 使用旧版默认基准仓位：保守 10%，稳健 15%，激进 20%
                base_pct = 10.0 if mode == "conservative" else 15.0 if mode == "moderate" else 20.0
                
                # 如果传入了 data，则进行波动率与流动性风控计算
                if data is not None and len(data) > 0:
                    current_price = data['Close'].iloc[-1]
                    atr = data['ATR'].iloc[-1] if 'ATR' in data.columns else current_price * 0.03
                    vol_ma20 = data['Volume_MA20'].iloc[-1] if 'Volume_MA20' in data.columns else (data['Volume'].iloc[-1] if 'Volume' in data.columns else 1000000)
                    
                    # 1. 波动率仓位控制 (ATR Cap)
                    atr_ratio = atr / current_price if current_price > 0 else 0.03
                    vol_cap = 0.04  # 4% 限制阈值
                    vol_multiplier = 1.0
                    if atr_ratio > vol_cap:
                        vol_multiplier = vol_cap / atr_ratio
                        
                    # 2. 流动性惩罚 (Volume MA20 Penalty)
                    liq_threshold = 1000000.0  # 100万阈值
                    liq_multiplier = 1.0
                    if vol_ma20 < liq_threshold:
                        liq_multiplier = vol_ma20 / liq_threshold
                        
                    # 复合调整 (取较小的乘数以保障安全)
                    adjusted_pct = base_pct * min(vol_multiplier, liq_multiplier)
                    
                    # 判断是否触发了任何风控惩罚
                    if vol_multiplier < 1.0 or liq_multiplier < 1.0:
                        pos_desc = f"{adjusted_pct:.1f}% 仓位上限"
                    else:
                        pos_desc = f"{adjusted_pct:.1f}%"
                else:
                    pos_desc = f"{base_pct:.0f}%"
            else:
                pos_desc = _safe_get_pos(plan, mode)

            #  问题二修复：方向与环境冲突时，强制观望
            if direction_env_conflict:
                env_name = market_env.value if hasattr(market_env, 'value') else str(market_env)
                if mode == "conservative":
                    return RiskAdviceItem(
                        action="绝对观望",
                        reason=f"方向与环境冲突：{direction}方向与{env_name}环境冲突，建议等待环境转弱或信号转向",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待大盘环境与交易方向一致"
                    )
                elif mode == "moderate":
                    return RiskAdviceItem(
                        action="观望",
                        reason=f"方向与环境冲突：{direction}方向与{env_name}环境冲突，建议等待",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待大盘环境转为中性或一致"
                    )
                else:  # aggressive
                    return RiskAdviceItem(
                        action="等待信号",
                        reason=f"方向与环境冲突：{direction}方向与{env_name}环境冲突，等待环境或信号明确",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待高置信度日线强反转形态"
                    )

            # 关键修复：跨周期冲突时，所有方向的交易建议都应被抑制
            if has_conflict:
                if mode == "conservative":
                    return RiskAdviceItem(
                        action="绝对观望", 
                        reason=f"跨周期冲突：{conflict_details}",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待高时间周期（周线/月线）趋势恢复一致"
                    )
                elif mode == "moderate":
                    return RiskAdviceItem(
                        action="观望", 
                        reason=f"跨周期冲突：{conflict_details}",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待周期共振或明确的次级折返测试成功"
                    )
                else:  # aggressive
                    #  修复：跨周期冲突下激进仓位上限从15-20%严格降至5-10%
                    return RiskAdviceItem(
                        action="极轻仓试错",
                        reason=(
                            f"跨周期冲突：{conflict_details}，等待日线级别明确信号。"
                            "⚠️ 风险警告：高时间框空头压制下，日线结构有失效风险（可能是下跌中继）。"
                            "如强行参与，仓位严格控制在5-10%，必须设好止损，极短线快进快出，不宜隔夜持仓。"
                        ),
                        position="5-10%",
                        stop_loss=stop_desc,
                        entry_condition="日线级 Spring/UT 得到小周期量价配合确认"
                    )

            if direction == "观望":
                return RiskAdviceItem(
                    action="观望", 
                    reason="无清晰信号",
                    position="0%",
                    stop_loss=stop_desc,
                    entry_condition="等待威科夫 Phase C 震仓或 Phase D 突破信号"
                )

            #  问题二修复：方向与环境匹配时，降低观望阈值
            if direction_env_match:
                if mode == "conservative":
                    action = "稳步参与" if score >= 60 else "观望"
                    reason = f"信号得分 {score}/100，且交易方向与市场环境一致（顺水推舟）"
                    return RiskAdviceItem(
                        action=action, 
                        reason=reason,
                        position=pos_desc if action != "观望" else "0%",
                        stop_loss=stop_desc,
                        entry_condition="回试 Creek 或 Spring/UT 低点不破 + 缩量确认"
                    )
                elif mode == "moderate":
                    action = "按计划参与" if score >= 40 else "观望"
                    reason = f"信号得分 {score}/100，且交易方向与市场环境一致（顺水推舟）"
                    return RiskAdviceItem(
                        action=action, 
                        reason=reason,
                        position=pos_desc if action != "观望" else "0%",
                        stop_loss=stop_desc,
                        entry_condition="结构内局部二测(ST)确认供应耗尽"
                    )
                else:  # aggressive
                    if score >= 20:
                        action = "激进试错"
                        reason = f"信号得分 {score}/100，方向与环境一致，顺水推舟"
                    else:
                        action = "极轻仓试错"
                        reason = f"评分较低，严控止损，等待日线级别明确信号"
                    return RiskAdviceItem(
                        action=action, 
                        reason=reason,
                        position=pos_desc,
                        stop_loss=stop_desc,
                        entry_condition="出现微观 VSA No-Supply/No-Demand 信号"
                    )

            # 原有逻辑（方向与环境不明确匹配时）
            if mode == "conservative":
                action = "稳步参与" if score >= 70 else "绝对观望"
                return RiskAdviceItem(
                    action=action, 
                    reason=f"信号得分 {score}/100",
                    position=pos_desc if action != "绝对观望" else "0%",
                    stop_loss=stop_desc,
                    entry_condition="Phase D 强势信号(SOS/JOC)放量突围且回踩不破"
                )
            elif mode == "moderate":
                action = "按计划参与" if score >= 50 else "观望"
                return RiskAdviceItem(
                    action=action, 
                    reason=f"信号得分 {score}/100",
                    position=pos_desc if action != "观望" else "0%",
                    stop_loss=stop_desc,
                    entry_condition="关键支撑/阻力位的 Spring/UT 震仓确认"
                )
            else: # aggressive
                if score >= 30:
                    action = "激进试错"
                    reason = f"信号得分 {score}/100，顺周线方向试错"
                else:
                    action = "极轻仓试错"
                    reason = f"评分较低，严控止损，等待日线级别明确信号"
                return RiskAdviceItem(
                    action=action, 
                    reason=reason,
                    position=pos_desc,
                    stop_loss=stop_desc,
                    entry_condition="短线突破高潮/恐慌低吸且紧扣极值点设防"
                )

        return RiskAdviceModel(
            conservative=get_item("conservative"),
            moderate=get_item("moderate"),
            aggressive=get_item("aggressive")
        )

    @staticmethod
    def get_execution_score(current_price: float, support: float, resistance: float, direction: str) -> float:
        """
        计算交易可执行性得分 (风盈比与距离支撑/阻力位的百分比)
        """
        if direction == "做多":
            if current_price <= support or current_price >= resistance: return 10.0
            dist_to_support = (current_price - support) / current_price
            
            # 越接近支撑位得分越高，理想距离在 1-5%
            if dist_to_support < 0.05:
                return round(100.0 * (1.0 - dist_to_support/0.05), 2)
            return 20.0
        else:
            if current_price >= resistance or current_price <= support: return 10.0
            dist_to_res = (resistance - current_price) / current_price
            if dist_to_res < 0.05:
                return round(100.0 * (1.0 - dist_to_res/0.05), 2)
            return 20.0

    @staticmethod
    def generate_phase_e_exit_strategy(data: Any, pattern_results: Dict[str, Any], targets: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成Phase E退出策略 (Wyckoff 操盘法)

        Wyckoff理论退出条件:
        1. 达到因果目标位 (基于P&F或波动率收缩)
        2. 量价背离 (Effort vs Result)
        3. Phase转换信号 (PSY/PS出现)
        4. 止损触发
        """
        current_price = data['Close'].iloc[-1]
        vol_ma20 = data['Volume_MA20'].iloc[-1] if 'Volume_MA20' in data.columns else data['Volume'].rolling(20).mean().iloc[-1]
        recent_vol = data['Volume'].iloc[-1]
        recent_close = data['Close'].iloc[-1]
        prev_close = data['Close'].iloc[-2]
        atr = data['ATR'].iloc[-1] if 'ATR' in data.columns else (data['High'] - data['Low']).rolling(14).mean().iloc[-1]

        exit_signals = []
        trailing_stop = 0.0

        # 1. 目标位检查
        target_2 = targets.get('target_2', targets.get('likely_target', 0))
        target_1 = targets.get('target_1', targets.get('minimum_target', 0))
        direction = getattr(pattern_results, 'direction', None) or '观望'

        if direction == '做多':
            if target_2 > 0 and current_price >= target_2:
                exit_signals.append(f"已触及第二目标位 {target_2:.2f}，建议全部止盈")
            elif target_1 > 0 and current_price >= target_1:
                exit_signals.append(f"已触及第一目标位 {target_1:.2f}，建议部分止盈(50%)")

            # Trailing stop: 最近摆动低点或 ATR 动态
            swing_low_10 = float(data['Low'].tail(10).min())
            atr_stop = current_price - atr * 3
            trailing_stop = max(swing_low_10, atr_stop)
        elif direction == '做空':
            if target_2 > 0 and current_price <= target_2:
                exit_signals.append(f"已触及第二目标位 {target_2:.2f}，建议全部止盈")
            elif target_1 > 0 and current_price <= target_1:
                exit_signals.append(f"已触及第一目标位 {target_1:.2f}，建议部分止盈(50%)")

            swing_high_10 = float(data['High'].tail(10).max())
            atr_stop = current_price + atr * 3
            trailing_stop = min(swing_high_10, atr_stop)

        # 2. 量价背离检查
        vol_ratio = recent_vol / vol_ma20 if vol_ma20 > 0 else 1.0
        price_change = (recent_close - prev_close) / prev_close

        if direction == '做多':
            # 缩量新高 = 需求枯竭
            if vol_ratio < 0.6 and price_change > 0:
                exit_signals.append(f"缩量创新高(量比{vol_ratio:.2f})：需求枯竭警告，建议减仓")
            # 高量滞涨 = 派发
            if vol_ratio > 1.5 and abs(price_change) < 0.005:
                exit_signals.append(f"高量滞涨(量比{vol_ratio:.2f})：供应进入，警惕Phase A派发信号")
        elif direction == '做空':
            if vol_ratio < 0.6 and price_change < 0:
                exit_signals.append(f"缩量创新低(量比{vol_ratio:.2f})：供应枯竭警告，建议减仓")
            if vol_ratio > 1.5 and abs(price_change) < 0.005:
                exit_signals.append(f"高量滞跌(量比{vol_ratio:.2f})：需求进入，警惕Phase A吸筹信号")

        # 3. SOT (Shortening of Thrust) 检测
        sot_detected, sot_desc = RecommendationEngine._detect_sot(data, direction)
        if sot_detected:
            exit_signals.append(sot_desc)

        # 兼容性处理：如果 pattern_results 是字典，且包含 'events_detected'，则从中提取核心事件
        if isinstance(pattern_results, dict):
            events = pattern_results.get('events_detected') or pattern_results
        else:
            events = pattern_results

        # 4. UTAD (终极推力) 检测 — Phase E 耗尽信号
        utad = RecommendationEngine._get_attr(events, 'utad')
        utad_detected = getattr(utad, 'detected', False) if utad else False
        if utad_detected:
            utad_type = getattr(utad, 'type', '')
            if direction == '做多' and utad_type == 'buying_climax':
                exit_signals.append("检测到UTAD(买入高潮)：最后的追高需求，上升动能耗尽，建议止盈")
            elif direction == '做空' and utad_type == 'selling_climax':
                exit_signals.append("检测到UTAD(抛售高潮)：最后的恐慌供应，下跌动能耗尽，建议止盈")

        # 5. LPSY/PSY 检测 — Phase A 反转信号
        lpsy = RecommendationEngine._get_attr(events, 'lpsy')
        if getattr(lpsy, 'detected', False) if lpsy else False:
            exit_signals.append("检测到LPSY(最后供应点)：供应重新出现，趋势面临反转风险，建议减仓")
        ps = RecommendationEngine._get_attr(events, 'preliminary_support')
        ps_detected = getattr(ps, 'detected', False) if ps else False
        if direction == '做空' and ps_detected:
            exit_signals.append("检测到PSY(初次支撑)：需求开始进入，下跌趋势可能终结，建议止盈")

        return {
            'exit_signals': exit_signals,
            'trailing_stop': round(trailing_stop, 2),
            'current_price': round(current_price, 2),
            'atr': round(atr, 2),
            'action': '部分止盈' if len(exit_signals) <= 1 else ('全部止盈' if len(exit_signals) >= 2 else '持仓观察'),
            'summary': '; '.join(exit_signals) if exit_signals else '无明确退出信号，继续按计划持有',
        }

    @staticmethod
    def _detect_sot(data: Any, direction: str) -> tuple:
        """
        SOT (Shortening of Thrust / 推力缩短) 检测

        Wyckoff Phase B→C 和 Phase E 的关键信号:
        - 上涨趋势中：当前浪比前浪幅度缩小但量能不减 = 需求衰竭
        - 下跌趋势中：当前浪比前浪幅度缩小但量能不减 = 供应衰竭

        Returns:
            (detected: bool, description: str)
        """
        df = data.tail(40)
        if len(df) < 20:
            return False, ""

        half = len(df) // 2
        wave1 = df.iloc[:half]
        wave2 = df.iloc[half:]

        wave1_range = wave1['High'].max() - wave1['Low'].min()
        wave2_range = wave2['High'].max() - wave2['Low'].min()
        wave1_vol = wave1['Volume'].mean()
        wave2_vol = wave2['Volume'].mean()

        safe_range1 = wave1_range if wave1_range > 0 else 1e-9
        thrust_shrinkage = wave2_range / safe_range1
        vol_change = wave2_vol / wave1_vol if wave1_vol > 0 else 1.0

        if direction == '做多':
            if thrust_shrinkage < 0.7 and vol_change > 0.9:
                return True, f"SOT检测：上涨浪幅度缩小至{thrust_shrinkage*100:.0f}%但量能维持(量比{vol_change:.2f})→需求衰竭，建议减仓"
        elif direction == '做空':
            if thrust_shrinkage < 0.7 and vol_change > 0.9:
                return True, f"SOT检测：下跌浪幅度缩小至{thrust_shrinkage*100:.0f}%但量能维持(量比{vol_change:.2f})→供应衰竭，建议减仓"

        return False, ""
