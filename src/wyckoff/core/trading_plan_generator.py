"""
威科夫分析系统 - 交易计划生成器
从report_generator.py中提取，负责生成交易计划
"""
import pandas as pd
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class TradingPlanGenerator:
    """
    交易计划生成器
    根据技术分析结果生成交易计划
    """
    
    # 默认仓位比例
    DEFAULT_POSITION = {
        'conservative': 2.5,
        'moderate': 5.0,
        'aggressive': 10.0
    }
    
    # 情绪调整系数
    SENTIMENT_ADJUSTMENT = {
        'extreme_fear': 0.5,
        'fear': 0.8,
        'neutral': 1.0,
        'greed': 1.2
    }
    
    def __init__(self, data: pd.DataFrame, pattern_detector):
        """
        初始化交易计划生成器
        
        Args:
            data: K线数据
            pattern_detector: 形态检测器
        """
        self.data = data
        self.pattern_detector = pattern_detector
        self.is_a_stock = False
        if hasattr(pattern_detector, 'data_fetcher'): # PatternDetector doesn't have it usually, but analyzer does.
             pass
    
    def generate(self, sentiment_data: Optional[Dict[str, Any]] = None, 
                 phase_str: str = "", is_a_stock: bool = False) -> Dict[str, Any]:
        """
        生成交易计划
        
        Args:
            sentiment_data: 市场情绪数据
            phase_str: 当前阶段字符串
            is_a_stock: 是否为A股
            
        Returns:
            交易计划字典
        """
        self.is_a_stock = is_a_stock
        if self.data is None:
            return {}
        
        current_price = self.data['Close'].iloc[-1]
        atr = self.data['ATR'].iloc[-1]
        
        # 获取交易区间
        tr = self.pattern_detector.detect_trading_range()
        high = tr.get("high", current_price * 1.1)
        low = tr.get("low", current_price * 0.9)
        
        # 获取阶段
        if not phase_str:
            phase_res = self.pattern_detector.identify_phase()
            phase_str = phase_res.get('phase', 'Unknown') if isinstance(phase_res, dict) else phase_res
        
        is_bullish = "Accumulation" in phase_str or "Markup" in phase_str
        
        # 计算入场、止损、目标
        entry_zone, stop_loss, targets = self._calculate_levels(
            current_price, atr, high, low, is_bullish
        )
        
        # 情绪调整仓位
        pos_sizing, dynamic_warning = self._adjust_position_with_sentiment(
            sentiment_data, phase_str, is_bullish
        )
        
        # 计算分批建仓触发条件
        scale_in_triggers = self._calculate_scale_in_triggers(
            current_price, high, low, atr, is_bullish
        )
        
        # 退出规则
        exit_rules = self._calculate_exit_rules(atr)
        
        # 方向判定与市场约束
        if is_bullish:
            direction = "做多"
        else:
            direction = "减仓/观望" if self.is_a_stock else "做空"

        return {
            "direction": direction,
            "entry_zone": entry_zone,
            "stop_loss": stop_loss,
            "targets": targets,
            "position_sizing": pos_sizing,
            "scale_in_triggers": scale_in_triggers,
            "exit_rules": exit_rules,
            "holding_period": "中期（2-8周）" if "Markup" in phase_str or "Markdown" in phase_str else "短期（1-3周）",
            "atr_value": round(atr, 2),
            "dynamic_warning": dynamic_warning,
            "market_constraint": "A股无法直接做空，建议以减仓或对冲替代" if self.is_a_stock and not is_bullish else None
        }
    
    def _calculate_levels(self, current_price: float, atr: float, 
                          high: float, low: float, is_bullish: bool) -> tuple:
        """
        计算入场、止损、目标价位
        
        Args:
            current_price: 当前价格
            atr: ATR值
            high: 区间高点
            low: 区间低点
            is_bullish: 是否看涨
            
        Returns:
            (入场区间, 止损, 目标)
        """
        entry_zone = f"{round(current_price * 0.99, 2)} - {round(current_price * 1.01, 2)}"
        
        if is_bullish:
            # 止损修复：使用 ATR 倍数 + TR 下沿兜底，避免全局下沿导致~20%止损
            # 保守：2.5倍ATR（约6-8%），激进：1.5倍ATR（约4-5%）
            conservative_stop = round(max(current_price - 2.5 * atr, low), 2)
            aggressive_stop = round(max(current_price - 1.5 * atr, low), 2)
            stop_loss = {
                "conservative": conservative_stop,
                "aggressive": aggressive_stop,
                "atr_dynamic_stop": round(current_price - 1.5 * atr, 2)
            }
            targets = {
                "target_1": round(high, 2) if current_price < high else round(current_price + atr * 2, 2),
                "target_2": round(high + atr * 3, 2)
            }
        else:
            conservative_stop = round(min(high, current_price + 2.5 * atr), 2)
            aggressive_stop = round(min(high, current_price + 1.5 * atr), 2)
            stop_loss = {
                "conservative": conservative_stop,
                "aggressive": aggressive_stop,
                "atr_dynamic_stop": round(current_price + 1.5 * atr, 2)
            }
            targets = {
                "target_1": round(low, 2) if current_price > low else round(current_price - atr * 2, 2),
                "target_2": round(low - atr * 3, 2)
            }
        
        return entry_zone, stop_loss, targets
    
    def _adjust_position_with_sentiment(self, sentiment_data: Optional[Dict[str, Any]], 
                                         phase_str: str, is_bullish: bool) -> tuple:
        """
        根据市场情绪调整仓位
        
        Args:
            sentiment_data: 市场情绪数据
            phase_str: 当前阶段
            is_bullish: 是否看涨
            
        Returns:
            (仓位配置, 动态预警)
        """
        pos_conservative = self.DEFAULT_POSITION['conservative']
        pos_moderate = self.DEFAULT_POSITION['moderate']
        pos_aggressive = self.DEFAULT_POSITION['aggressive']
        
        dynamic_warning = None
        
        if sentiment_data:
            sentiment = sentiment_data.get("market_sentiment", "neutral")
            adjustment = self.SENTIMENT_ADJUSTMENT.get(sentiment, 1.0)
            
            pos_conservative *= adjustment
            pos_moderate *= adjustment
            pos_aggressive *= adjustment
            
            # 情绪背离预警
            if sentiment == "greed" and ("Distribution" in phase_str or "Markdown" in phase_str):
                dynamic_warning = "⚠️ 极度危险：大盘贪婪 + 个股派发 = 暴跌前兆，禁止盲目接刀！"
            elif sentiment == "extreme_fear" and ("Accumulation" in phase_str or "Markup" in phase_str):
                dynamic_warning = "💡 黄金坑预警：大盘极度恐慌 + 个股筑底 = 绝佳击球区，请重点关注抗跌表现！"
        
        pos_sizing = {
            "conservative": f"{round(pos_conservative, 1)}%总仓",
            "moderate": f"{round(pos_moderate, 1)}%总仓",
            "aggressive": f"{round(pos_aggressive, 1)}%总仓"
        }
        
        return pos_sizing, dynamic_warning
    
    def _calculate_scale_in_triggers(self, current_price: float, high: float, 
                                      low: float, atr: float, is_bullish: bool) -> Dict[str, Dict[str, Any]]:
        """
        计算分批建仓触发条件
        
        Args:
            current_price: 当前价格
            high: 区间高点
            low: 区间低点
            atr: ATR值
            is_bullish: 是否看涨
            
        Returns:
            分批建仓触发条件
        """
        if is_bullish:
            return {
                "entry_1_30pct": {
                    "condition": "当前信号出现 (如 Spring/SOS)",
                    "price": round(current_price, 2)
                },
                "entry_2_50pct": {
                    "condition": "价格突破关键阻力位或回踩支撑不破",
                    "price": round(high, 2)
                },
                "entry_3_20pct": {
                    "condition": "创出新高或确认进入强势上涨阶段 (Phase E)",
                    "price": round(high + atr, 2)
                }
            }
        else:
            return {
                "entry_1_30pct": {
                    "condition": "当前做空信号出现",
                    "price": round(current_price, 2)
                },
                "entry_2_50pct": {
                    "condition": "跌破关键支撑位或反抽阻力不破",
                    "price": round(low, 2)
                },
                "entry_3_20pct": {
                    "condition": "创出新低或确认进入强势下跌阶段 (Phase E)",
                    "price": round(low - atr, 2)
                }
            }
    
    def _calculate_exit_rules(self, atr: float) -> list:
        """
        计算退出规则
        
        Args:
            atr: ATR值
            
        Returns:
            退出规则列表
        """
        return [
            {
                "type": "trailing_stop",
                "trigger": "1ATR_profit",
                "description": f"浮盈达到1个ATR ({round(atr, 2)}元)",
                "action": "move_to_cost"
            },
            {
                "type": "trailing_stop",
                "trigger": "2ATR_profit",
                "description": f"浮盈达到2个ATR ({round(atr * 2, 2)}元)",
                "action": "move_to_1ATR_profit"
            },
            {
                "type": "time_stop",
                "trigger": "5-8_days_no_profit",
                "description": "建仓后 5-8 个交易日未脱离成本区",
                "action": "exit_position"
            }
        ]
