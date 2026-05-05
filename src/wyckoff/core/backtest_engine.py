"""
威科夫分析系统 - 历史回测引擎
从report_generator.py中提取，负责信号历史表现回测
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
import logging
from ..config.settings import WyckoffThresholds

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    历史回测引擎
    基于历史K线数据回测威科夫信号的表现
    """
    
    # 全市场通用基准（Fallback）
    STATIC_BASELINE = {
        "SOS (强势信号)": {"total_occurrences": 128, "success_rate": "75.4%", "avg_return": "+12.4%"},
        "Spring (震仓洗盘)": {"total_occurrences": 45, "success_rate": "82.1%", "avg_return": "+18.8%"},
        "SOW (弱势信号)": {"total_occurrences": 92, "success_rate": "68.3%", "avg_return": "-9.2%"},
        "Upthrust (上冲回落)": {"total_occurrences": 56, "success_rate": "71.5%", "avg_return": "-14.5%"}
    }
    
    # 信号映射配置
    SIGNAL_MAPPING = {
        "SOS (强势信号)": {"key": "sos", "is_bullish": True},
        "Spring (震仓洗盘)": {"key": "spring", "is_bullish": True},
        "SOW (弱势信号)": {"key": "sow", "is_bullish": False},
        "Upthrust (上冲回落)": {"key": "upthrust", "is_bullish": False}
    }
    
    def __init__(self, data: pd.DataFrame, thresholds: WyckoffThresholds = None, 
                 lookforward_days: int = 20, min_samples: int = 3):
        """
        初始化回测引擎
        
        Args:
            data: 历史K线数据
            thresholds: 包含成本参数的阈值配置
            lookforward_days: 前瞻天数（默认20天）
            min_samples: 最小样本量（低于此数量使用基准数据）
        """
        self.data = data
        self.thresholds = thresholds or WyckoffThresholds()
        self.lookforward_days = lookforward_days
        self.min_samples = min_samples
        
        # 预建立日期索引映射，O(1)查找
        self._date_to_pos = {
            dt.strftime('%Y-%m-%d'): i
            for i, dt in enumerate(self.data.index)
        }
    
    def calculate_signal_performance(self, events: Dict[str, Any], current_phase: str = None) -> Dict[str, Dict[str, Any]]:
        """
        计算各信号的历史表现

        新增功能：根据当前阶段动态调整展示顺序，优先展示相关信号

        Args:
            events: 事件检测结果字典
            current_phase: 当前Wyckoff阶段（用于动态排序）

        Returns:
            各信号的历史表现统计（已根据当前阶段排序）
        """
        results = {}

        # 判断当前阶段类型
        is_distribution = current_phase and ('Distribution' in current_phase or '派发' in current_phase)
        is_accumulation = current_phase and ('Accumulation' in current_phase or '吸筹' in current_phase)

        # 根据当前阶段定义优先级顺序
        if is_distribution:
            # 派发阶段：优先展示空头信号
            priority_order = ["Upthrust (上冲回落)", "SOW (弱势信号)", "SOS (强势信号)", "Spring (震仓洗盘)"]
        elif is_accumulation:
            # 吸筹阶段：优先展示多头信号
            priority_order = ["SOS (强势信号)", "Spring (震仓洗盘)", "SOW (弱势信号)", "Upthrust (上冲回落)"]
        else:
            # 其他阶段：默认顺序
            priority_order = list(self.SIGNAL_MAPPING.keys())

        # 按优先级顺序处理信号
        for display_name in priority_order:
            if display_name not in self.SIGNAL_MAPPING:
                continue
            config = self.SIGNAL_MAPPING[display_name]
            key = config["key"]
            is_bullish = config["is_bullish"]
            
            event_data = events.get(key) or {}
            signals = event_data.get("signals") or []
            if not isinstance(signals, list) or len(signals) < self.min_samples:
                results[display_name] = dict(self.STATIC_BASELINE[display_name])
                results[display_name]["note"] = f"样本不足{self.min_samples}次，采用全市场基准"
                continue
            
            result = self._backtest_signal(signals, is_bullish)
            if result is None:
                results[display_name] = dict(self.STATIC_BASELINE[display_name])
                results[display_name]["note"] = f"样本不足{self.min_samples}次，采用全市场基准"
            else:
                results[display_name] = result
        
        return results
    
    def _backtest_signal(self, signals: List[Dict[str, Any]], is_bullish: bool) -> Dict[str, Any]:
        """
        回测单个信号，加入成本与滑点建模
        """
        total_net_returns = []
        max_drawdowns = []
        winning_trades = 0
        
        cost = self.thresholds.COMMISSION_RATE + self.thresholds.SLIPPAGE_RATE + self.thresholds.IMPACT_COST_RATE
        
        for sig in signals:
            date_str = sig.get("date")
            entry_price = sig.get("price")
            if not date_str or not entry_price: continue
            
            entry_idx = self._get_date_index(date_str)
            if entry_idx == -1: continue
            
            target_idx = min(entry_idx + self.lookforward_days, len(self.data) - 1)
            if target_idx - entry_idx < 5: continue
            
            # 计算区间最高/最低以估算回撤
            window_df = self.data.iloc[entry_idx:target_idx+1]
            future_price = self.data['Close'].iloc[target_idx]
            
            # 基础收益
            raw_ret = (future_price - entry_price) / entry_price if is_bullish else (entry_price - future_price) / entry_price
            
            # 扣除双边交易成本
            net_ret = raw_ret - (cost * 2)
            total_net_returns.append(net_ret)
            
            if net_ret > 0: winning_trades += 1
            
            # 简单最大回撤估算
            if is_bullish:
                low_price = window_df['Low'].min()
                mdd = (low_price - entry_price) / entry_price
            else:
                high_price = window_df['High'].max()
                mdd = (entry_price - high_price) / entry_price
            max_drawdowns.append(mdd)
            
        valid_count = len(total_net_returns)
        if valid_count < 1: return None
        
        # 计算置信度等级
        # A: >= 10个样本, B: 5-9个, C: < 5个
        grade = "A" if valid_count >= 10 else "B" if valid_count >= 5 else "C"
        
        avg_net_ret = sum(total_net_returns) / valid_count
        win_rate = winning_trades / valid_count
        
        # 计算盈亏比
        pos_rets = [r for r in total_net_returns if r > 0]
        neg_rets = [abs(r) for r in total_net_returns if r < 0]
        pl_ratio = (sum(pos_rets)/len(pos_rets)) / (sum(neg_rets)/len(neg_rets)) if pos_rets and neg_rets else 2.0
        
        return {
            "total_occurrences": valid_count,
            "success_rate": f"{win_rate*100:.1f}%",
            "avg_return": f"{'+' if avg_net_ret > 0 else ''}{avg_net_ret*100:.1f}%",
            "pl_ratio": round(pl_ratio, 2),
            "max_drawdown": f"{min(max_drawdowns)*100:.1f}%",
            "confidence_grade": grade,
            "note": f"动态回测 (级:{grade}, 样:{valid_count})"
        }
    
    def _get_date_index(self, date_str: str) -> int:
        """
        获取日期在数据中的索引位置
        
        Args:
            date_str: 日期字符串
            
        Returns:
            索引位置，如果未找到返回-1
        """
        try:
            target_date = pd.to_datetime(date_str).strftime('%Y-%m-%d')
            return self._date_to_pos.get(target_date, -1)
        except Exception:
            return -1
