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
    """

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.thresholds = WyckoffThresholds()

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

    def calculate_weighted_score(self, data: Any, pattern_results: Dict[str, Any], market_env: MarketEnvironment) -> SignalQualityModel:
        """
        计算高级加权评分 (包含时间衰减与冲突惩罚)
        """
        events = pattern_results.get('events_detected', {}) or pattern_results
        if not events:
            return SignalQualityModel(score=0, max_score=100, confidence="低", reasons=["未检测到有效信号"])
            
        base_score = 0.0
        reasons = []
        weights = self.thresholds.QUALITY_WEIGHTS
        
        # 🔧 问题四修复：主要信号权重分配（增加ST和AR）
        # ST（Secondary Test）和AR（Automatic Reaction）是威科夫Phase A的关键信号
        # 不应被忽略，特别是在派发/吸筹初期
        important_signals = [
            ('joc', 40),
            ('spring', 35),
            ('sos', 25),
            ('lps', 15),
            ('upthrust', 35),
            ('sow', 25),
            ('lpsy', 15),
            ('fti', 40),
            ('secondary_test', 20),  # 🔧 新增：ST是Phase A关键确认信号
            ('automatic_reaction', 15)  # 🔧 新增：AR定义TR边界
        ]

        bullish_count = 0
        bearish_count = 0

        for key, max_weight in important_signals:
            info = events.get(key)
            if not info or not self._get_attr(info, 'detected'): continue

            # 判断方向
            if key in ['joc', 'spring', 'sos', 'lps', 'automatic_reaction']:
                bullish_count += 1
            elif key in ['fti', 'upthrust', 'sow', 'lpsy', 'secondary_test']:
                # 🔧 修复：ST的方向判断需要根据上下文
                # 派发期的ST确认需求耗尽（看空），吸筹期的ST确认供应耗尽（看多）
                # 这里简化处理：ST归为中性，根据阶段判断
                phase_str = pattern_results.get('phase', 'Unknown')
                if 'Distribution' in phase_str or '派发' in phase_str:
                    bearish_count += 1  # 派发期的ST确认看空
                elif 'Accumulation' in phase_str or '吸筹' in phase_str:
                    bullish_count += 1  # 吸筹期的ST确认看多

            # 质量因子 (0.5 - 1.2)
            quality_factor = 0.8

            # 1. 成交量因子
            # 🔧 问题四修复：ST和AR使用特殊的volume_ratio处理
            if key == 'secondary_test':
                # ST的volume_ratio是相对climax的，不是相对MA的
                st_vol_ratio = self._get_attr(info, 'st_vol_ratio', None)
                supply_exhausted = self._get_attr(info, 'supply_exhausted', False)
                if supply_exhausted:
                    quality_factor += 0.3  # ST确认供应耗尽，加分
                    reasons.append(f"ST确认需求耗尽（量比{st_vol_ratio:.1%}）")
                elif st_vol_ratio and st_vol_ratio < 0.6:
                    quality_factor += 0.1  # ST接近确认，小幅加分
                    reasons.append(f"ST接近确认（量比{st_vol_ratio:.1%}）")
            elif key == 'automatic_reaction':
                # AR没有volume_ratio，用rebound_pct/decline_pct判断
                rebound_pct = self._get_attr(info, 'rebound_pct', None)
                decline_pct = self._get_attr(info, 'decline_pct', None)
                if rebound_pct and rebound_pct > 0.03:  # 反弹超过3%
                    quality_factor += 0.15
                    reasons.append(f"AR自然反弹强劲（{rebound_pct*100:.1f}%）")
                elif decline_pct and decline_pct < -0.03:  # 回落超过3%
                    quality_factor += 0.15
                    reasons.append(f"AR自然回落充分（{decline_pct*100:.1f}%）")
            else:
                vol_ratio = self._get_attr(info, 'volume_ratio', 1.0)
                if vol_ratio > 1.5:
                    quality_factor += weights['volume_ratio']
                    reasons.append(f"{key.upper()} 成交量强力确认")

            # 2. 置信度因子
            conf = self._get_attr(info, 'confidence', 0.5)
            quality_factor += (conf - 0.5) * weights['confidence']

            # 3. 时间衰减 (Time Decay)
            sig_date = self._get_attr(info, 'date')
            if sig_date:
                if isinstance(sig_date, str):
                    try: sig_date = datetime.strptime(sig_date, '%Y-%m-%d')
                    except Exception:
                        pass

                if isinstance(sig_date, datetime):
                    # 处理时区问题
                    from datetime import timezone
                    now = datetime.now(timezone.utc) if sig_date.tzinfo else datetime.now()
                    try:
                        days_ago = (now - sig_date).days
                    except Exception as e:
                        # 如果时区不兼容，转换为UTC
                        logger.debug(f"Timezone conversion fallback for {sig_date}: {e}")
                        if sig_date.tzinfo:
                            sig_date = sig_date.replace(tzinfo=None)
                        now = datetime.now()
                        days_ago = (now - sig_date).days

                    decay = np.exp(-0.693 * max(0, days_ago) / self.thresholds.TIME_DECAY_HALF_LIFE)
                    quality_factor *= decay
                    if decay < 0.7: reasons.append(f"{key.upper()} 信号已过最佳期 (衰减)")

            base_score += max_weight * min(quality_factor, 1.5)

        # --- 事件序列验证加成 ---
        seq_val = pattern_results.get('sequence_validation', {})
        seq_score = seq_val.get('sequence_score', {})
        seq_rating = seq_score.get('rating', '')
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
        spring_val = seq_val.get('spring', {})
        if spring_val.get('quality') == 'high':
            base_score += 10
            reasons.append("Spring有完整SC→AR→ST前置结构，信号质量高 (+10分)")
        elif spring_val.get('quality') == 'medium':
            base_score += 5
            reasons.append("Spring有部分前置结构，质量中等 (+5分)")

        # 序列矛盾扣分
        seq_conflicts = seq_val.get('conflicts', [])
        for conflict in seq_conflicts:
            base_score -= 10
            reasons.append(f"序列矛盾: {conflict} (-10分)")

        # --- 孟洪涛进阶信号：枯燥区与死角突破 ---
        boring = pattern_results.get('boring_zone', {})
        boring_score = self._get_attr(boring, 'score', 0)
        if self._get_attr(boring, 'detected'):
            base_score += 10
            reasons.append(f"检测到「枯燥区」(得分:{boring_score})，主力可能正在吸筹")

            # Boring Zone 联动加权 (P2 #3.1)
            if boring_score > 85:
                for key in ['spring', 'joc']:
                    info = events.get(key)
                    if info and self._get_attr(info, 'detected'):
                        base_score += 15 # 高质量枯燥区后的突破极具爆发力
                        reasons.append(f"🔥 高价值突破：{key.upper()} 紧随高质量枯燥区出现，爆发潜力极大")

            if self._get_attr(boring, 'high_alert'):
                reasons.append("🔥 高能预警：系统已进入「死角突破」严密监控模式")

        dead_corner = pattern_results.get('dead_corner_breakout', {})
        if dead_corner.get('detected'):
            base_score += 25
            reasons.append("🎯 发现“死角突破”信号！从枯燥区放量跃起，极具爆发力")

        # 🔧 问题四修复：冲突惩罚优化
        # 原逻辑：只要有多空信号就扣30分，过于严厉
        # 新逻辑：区分"严重冲突"和"阶段过渡信号"
        if bullish_count > 0 and bearish_count > 0:
            phase_str = pattern_results.get('phase', 'Unknown')

            # 检查是否是阶段过渡期的合理信号（如吸筹→上涨）
            is_phase_transition = (
                ('Accumulation' in phase_str and bullish_count > bearish_count) or
                ('Distribution' in phase_str and bearish_count > bullish_count)
            )

            if is_phase_transition:
                # 阶段过渡期的信号冲突是合理的，轻微扣分
                base_score -= 10
                reasons.append(f"阶段过渡期信号混合 (轻微扣分 -10分，符合威科夫理论)")
            else:
                # 严重的多空信号冲突，大幅扣分
                base_score -= self.thresholds.CONFLICT_PENALTY
                reasons.append(f"检测到多空信号冲突 (惩罚 -{self.thresholds.CONFLICT_PENALTY}分)")

        # 市场环境加成（双向对称：多头/空头都有加分和扣分）
        # 🔧 问题四修复：环境扣分优化
        # 原逻辑：非Strong Bull做多扣10分，非Strong Bear做空扣10分
        # 问题：中性环境（Bull、Bear、Neutral）也被扣分
        # 新逻辑：只在极端环境不匹配时扣分
        phase_str = pattern_results.get('phase', 'Unknown')
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
            base_score += 5  # 🔧 修复：普通多头环境也加分，但不多
            reasons.append("顺应大盘多头环境 (+5分)")
        elif is_market_strong_bearish and current_side == MarketSide.BULLISH:
            base_score -= 15  # 🔧 修复：只在极端环境不匹配时大幅扣分
            reasons.append("大盘强势空头环境不利于做多 (-15分)")

        # 空头方向
        if is_market_strong_bearish and current_side == MarketSide.BEARISH:
            base_score += 15
            reasons.append("顺应大盘强势空头环境 (+15分)")
        elif is_market_bearish and current_side == MarketSide.BEARISH:
            base_score += 5  # 🔧 修复：普通空头环境也加分
            reasons.append("顺应大盘空头环境 (+5分)")
        elif is_market_strong_bullish and current_side == MarketSide.BEARISH:
            base_score -= 15  # 🔧 修复：只在极端环境不匹配时大幅扣分
            reasons.append("大盘强势多头环境不利于做空 (-15分)")

        # 🔧 问题四修复：信号质量过低时的解释说明
        final_score = int(max(0, min(base_score, 100)))

        if final_score < 10 and seq_rating in ['A', 'B']:
            # 序列完整但评分极低，说明缺少主要交易信号
            missing_signals = []
            phase_str = pattern_results.get('phase', 'Unknown')

            if 'Accumulation' in phase_str or '吸筹' in phase_str:
                if not events.get('spring') or not self._get_attr(events.get('spring'), 'detected'):
                    missing_signals.append('Spring震仓')
                if not events.get('sos') or not self._get_attr(events.get('sos'), 'detected'):
                    missing_signals.append('SOS强势信号')
            elif 'Distribution' in phase_str or '派发' in phase_str:
                if not events.get('sow') or not self._get_attr(events.get('sow'), 'detected'):
                    missing_signals.append('SOW弱势信号')
                if not events.get('lpsy') or not self._get_attr(events.get('lpsy'), 'detected'):
                    missing_signals.append('LPSY最后支撑')

            if missing_signals:
                reasons.append(f"⚠️ 虽有完整{seq_rating}级序列结构，但缺少核心交易信号：{', '.join(missing_signals)}。当前处于{phase_str}，信号尚未成熟，建议等待关键确认出现。")

        # 针对枯燥区 85 分以上的特殊提升
        if self._get_attr(boring, 'score', 0) >= 85 and final_score < 85:
            final_score = 85
            reasons.append("触发高能预警阈值，综合评分上调至 85 (死角突破临界)")

        return SignalQualityModel(
            score=final_score,
            max_score=100,
            confidence="极高" if final_score >= 85 else "高" if final_score >= 70 else "中" if final_score >= 40 else "低",
            reasons=reasons
        )

    def calculate_signal_quality(self, data: Any, pattern_results: Dict[str, Any], market_env: MarketEnvironment) -> SignalQualityModel:
        """兼容旧接口，内部调用加权评分"""
        return self.calculate_weighted_score(data, pattern_results, market_env)

    @staticmethod
    def calculate_signal_strength(pattern_results: Dict[str, Any]) -> int:
        """计算基础信号强度 (简单计数，仅为兼容性保留)"""
        events = pattern_results.get('events_detected', {}) or pattern_results
        count = 0
        for key in ['joc', 'spring', 'sos', 'lps', 'upthrust', 'sow', 'lpsy', 'fti']:
            event = events.get(key)
            if event and RecommendationEngine._get_attr(event, 'detected'):
                count += 1
        return count

    def generate_trading_plan(self, data: Any, pattern_results: Dict[str, Any], targets: Dict[str, Any]) -> TradingPlanModel:
        """
        生成具体交易计划 (Enhanced with execution score)
        """
        current_price = data['Close'].iloc[-1]
        joc = pattern_results.get('joc', {})
        spring = pattern_results.get('spring', {})
        fti = pattern_results.get('fti', {})
        
        # 基础方向判断
        if joc.get('detected'):
            direction, zone = "做多", f"{joc['creek_level']:.2f} 附近 (JOC突破)"
            stop = StopLossModel(conservative=round(joc['creek_level']*0.97, 2), aggressive=round(joc['creek_level']*0.95, 2))
        elif spring.get('detected'):
            direction, zone = "做多", f"{current_price:.2f} 附近 (Spring震仓)"
            stop = StopLossModel(conservative=round(current_price*0.96, 2), aggressive=round(current_price*0.93, 2))
        elif fti.get('detected'):
            direction, zone = "做空", f"{fti['ice_level']:.2f} 附近 (FTI跌破)"
            stop = StopLossModel(conservative=round(fti['ice_level']*1.03, 2), aggressive=round(fti['ice_level']*1.05, 2))
        else:
            direction, zone = "观望", "等待形态确认"
            stop = StopLossModel(conservative=0, aggressive=0)

        # 仓位建议
        pos_sizing = PositionSizingModel(
            conservative="5% (信号弱)", moderate="10% (信号正常)", aggressive="20% (信号强)"
        )

        return TradingPlanModel(
            direction=direction,
            entry_zone=zone,
            stop_loss=stop,
            targets=TargetsModel(target_1=targets.get('target_1', 0), target_2=targets.get('target_2', 0)),
            position_sizing=pos_sizing,
            holding_period="1-3个月 (波段)"
        )

    def generate_risk_advice(self, quality: SignalQualityModel, plan: TradingPlanModel,
                            has_conflict: bool = False, conflict_details: str = "",
                            market_env: MarketEnvironment = None) -> RiskAdviceModel:
        """
        生成分层风险建议 (Enhanced with volatility check and conflict detection)

        重要理论约束：
        - 当跨周期冲突时，所有方向的交易建议都应被抑制
        - 顺周线试错拿货（等Spring），优于逆周线试错砸盘（等LPSY）

        🔧 问题二修复：增加市场环境与交易方向的一致性检查
        - 做空 + 强多头环境 → 绝对观望
        - 做多 + 强多头环境 → 顺水推舟，降低观望阈值
        """
        score = quality.score
        direction = plan.direction

        # 🔧 新增：检查方向与环境的冲突
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

        def get_item(mode: str) -> RiskAdviceItem:
            # 🔧 问题二修复：方向与环境冲突时，强制观望
            if direction_env_conflict:
                env_name = market_env.value if hasattr(market_env, 'value') else str(market_env)
                if mode == "conservative":
                    return RiskAdviceItem(
                        action="绝对观望",
                        reason=f"方向与环境冲突：做空方向与{env_name}环境冲突，建议等待环境转弱或信号转向"
                    )
                elif mode == "moderate":
                    return RiskAdviceItem(
                        action="观望",
                        reason=f"方向与环境冲突：做空方向与{env_name}环境冲突，建议等待"
                    )
                else:  # aggressive
                    return RiskAdviceItem(
                        action="等待信号",
                        reason=f"方向与环境冲突：做空方向与{env_name}环境冲突，等待环境或信号明确"
                    )

            # 关键修复：跨周期冲突时，所有方向的交易建议都应被抑制
            if has_conflict:
                if mode == "conservative":
                    return RiskAdviceItem(action="绝对观望", reason=f"跨周期冲突：{conflict_details}")
                elif mode == "moderate":
                    return RiskAdviceItem(action="观望", reason=f"跨周期冲突：{conflict_details}")
                else:  # aggressive
                    # 激进策略也应抑制，但可以给出等待方向
                    return RiskAdviceItem(action="等待信号", reason=f"跨周期冲突：{conflict_details}，等待日线级别明确信号")

            if direction == "观望":
                return RiskAdviceItem(action="观望", reason="无清晰信号")

            # 🔧 问题二修复：方向与环境匹配时，降低观望阈值
            if direction_env_match:
                if mode == "conservative":
                    # 原本需要>=70分，现在降低到>=60分
                    action = "稳步参与" if score >= 60 else "观望"
                    reason = f"信号得分 {score}/100，且交易方向与市场环境一致（顺水推舟）"
                    return RiskAdviceItem(action=action, reason=reason)
                elif mode == "moderate":
                    # 原本需要>=50分，现在降低到>=40分
                    action = "按计划参与" if score >= 40 else "观望"
                    reason = f"信号得分 {score}/100，且交易方向与市场环境一致（顺水推舟）"
                    return RiskAdviceItem(action=action, reason=reason)
                else:  # aggressive
                    # 激进策略：只要有20分以上就可以试错
                    if score >= 20:
                        action = "激进试错"
                        reason = f"信号得分 {score}/100，方向与环境一致，顺水推舟"
                    else:
                        action = "极轻仓试错"
                        reason = f"评分较低，严控止损，等待日线级别明确信号"
                    return RiskAdviceItem(action=action, reason=reason)

            # 原有逻辑（方向与环境不明确匹配时）
            if mode == "conservative":
                action = "稳步参与" if score >= 70 else "绝对观望"
                return RiskAdviceItem(action=action, reason=f"信号得分 {score}/100")
            elif mode == "moderate":
                action = "按计划参与" if score >= 50 else "观望"
                return RiskAdviceItem(action=action, reason=f"信号得分 {score}/100")
            else: # aggressive
                # 关键修复：激进策略的"试错"方向应在体系内设定优先级
                # 顺周线试错拿货（等Spring），优于逆周线试错砸盘（等LPSY）
                if score >= 30:
                    action = "激进试错"
                    reason = f"信号得分 {score}/100，顺周线方向试错"
                else:
                    action = "极轻仓试错"
                    reason = f"评分较低，严控止损，等待日线级别明确信号"
                return RiskAdviceItem(action=action, reason=reason)

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
