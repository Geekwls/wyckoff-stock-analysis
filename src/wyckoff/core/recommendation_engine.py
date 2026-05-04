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
        
        # 主要信号权重分配
        important_signals = [
            ('joc', 40),
            ('spring', 35),
            ('sos', 25),
            ('upthrust', 35),
            ('sow', 25),
            ('fti', 40)
        ]
        
        bullish_count = 0
        bearish_count = 0
        
        for key, max_weight in important_signals:
            info = events.get(key)
            if not info or not info.get('detected'): continue
            
            # 判断方向
            if key in ['joc', 'spring', 'sos', 'lps']: bullish_count += 1
            elif key in ['fti', 'upthrust', 'sow', 'lpsy']: bearish_count += 1
            
            # 质量因子 (0.5 - 1.2)
            quality_factor = 0.8
            
            # 1. 成交量因子
            vol_ratio = info.get('volume_ratio', 1.0)
            if vol_ratio > 1.5: 
                quality_factor += weights['volume_ratio']
                reasons.append(f"{key.upper()} 成交量强力确认")
            
            # 2. 置信度因子
            conf = info.get('confidence', 0.5)
            quality_factor += (conf - 0.5) * weights['confidence']
            
            # 3. 时间衰减 (Time Decay)
            sig_date = info.get('date')
            if sig_date:
                if isinstance(sig_date, str):
                    try: sig_date = datetime.strptime(sig_date, '%Y-%m-%d')
                    except: pass
                
                if isinstance(sig_date, datetime):
                    days_ago = (datetime.now() - sig_date).days
                    decay = np.exp(-0.693 * max(0, days_ago) / self.thresholds.TIME_DECAY_HALF_LIFE)
                    quality_factor *= decay
                    if decay < 0.7: reasons.append(f"{key.upper()} 信号已过最佳期 (衰减)")

            base_score += max_weight * min(quality_factor, 1.5)

        # --- 孟洪涛进阶信号：枯燥区与死角突破 ---
        boring = pattern_results.get('boring_zone', {})
        if boring.get('detected'):
            base_score += 10
            reasons.append(f"检测到“枯燥区” (得分:{boring['score']})，主力可能正在吸筹")
            if boring.get('high_alert'):
                reasons.append("🔥 高能预警：系统已进入“死角突破”严密监控模式")

        dead_corner = pattern_results.get('dead_corner_breakout', {})
        if dead_corner.get('detected'):
            base_score += 25
            reasons.append("🎯 发现“死角突破”信号！从枯燥区放量跃起，极具爆发力")

        # 冲突惩罚
        if bullish_count > 0 and bearish_count > 0:
            base_score -= self.thresholds.CONFLICT_PENALTY
            reasons.append(f"检测到多空信号冲突 (惩罚 -{self.thresholds.CONFLICT_PENALTY}分)")

        # 市场环境加成
        phase_str = pattern_results.get('phase', 'Unknown')
        current_side = PhaseAdapter.get_market_side(phase_str)
        is_market_bullish = market_env in [MarketEnvironment.STRONG_BULL, MarketEnvironment.BULL]
        
        if is_market_bullish and current_side == MarketSide.BULLISH:
            base_score += 15
            reasons.append("顺应大盘多头环境 (+15分)")
        elif not is_market_bullish and current_side == MarketSide.BULLISH:
            base_score -= 10
            reasons.append("大盘环境不利于做多 (-10分)")

        final_score = int(max(0, min(base_score, 100)))
        
        # 针对枯燥区 85 分以上的特殊提升
        if boring.get('score', 0) >= 85 and final_score < 85:
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
            if events.get(key, {}).get('detected'):
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

    def generate_risk_advice(self, quality: SignalQualityModel, plan: TradingPlanModel) -> RiskAdviceModel:
        """
        生成分层风险建议 (Enhanced with volatility check)
        """
        score = quality.score
        direction = plan.direction
        
        def get_item(mode: str) -> RiskAdviceItem:
            if direction == "观望":
                return RiskAdviceItem(action="观望", reason="无清晰信号")
            
            if mode == "conservative":
                action = "稳步参与" if score >= 70 else "绝对观望"
                return RiskAdviceItem(action=action, reason=f"信号得分 {score}/100")
            elif mode == "moderate":
                action = "按计划参与" if score >= 50 else "观望"
                return RiskAdviceItem(action=action, reason=f"信号得分 {score}/100")
            else: # aggressive
                action = "激进试错" if score >= 30 else "极轻仓试错"
                return RiskAdviceItem(action=action, reason=f"评分较低，严控止损")

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
