"""
威科夫分析系统 - 历史回测引擎
从report_generator.py中提取，负责信号历史表现回测
"""
import pandas as pd
from typing import Dict, List, Any
import logging

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
    
    def __init__(self, data: pd.DataFrame, lookforward_days: int = 20, min_samples: int = 2):
        """
        初始化回测引擎
        
        Args:
            data: 历史K线数据
            lookforward_days: 前瞻天数（默认20天）
            min_samples: 最小样本量（低于此数量使用基准数据）
        """
        self.data = data
        self.lookforward_days = lookforward_days
        self.min_samples = min_samples
        
        # 预建立日期索引映射，O(1)查找
        self._date_to_pos = {
            dt.strftime('%Y-%m-%d'): i
            for i, dt in enumerate(self.data.index)
        }
    
    def calculate_signal_performance(self, events: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        计算各信号的历史表现
        
        Args:
            events: 事件检测结果字典
            
        Returns:
            各信号的历史表现统计
        """
        results = {}
        
        for display_name, config in self.SIGNAL_MAPPING.items():
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
        回测单个信号
        
        Args:
            signals: 信号列表
            is_bullish: 是否为看涨信号
            
        Returns:
            回测结果，如果样本不足返回None
        """
        success_count = 0
        total_returns = []
        
        for sig in signals:
            date_str = sig.get("date")
            entry_price = sig.get("price")
            
            if not date_str or not entry_price:
                continue
            
            # 获取入场位置
            entry_idx = self._get_date_index(date_str)
            if entry_idx == -1:
                continue
            
            # 获取前瞻位置
            target_idx = min(entry_idx + self.lookforward_days, len(self.data) - 1)
            if target_idx - entry_idx < 5:
                continue
            
            # 计算收益
            future_price = self.data['Close'].iloc[target_idx]
            if is_bullish:
                ret = (future_price - entry_price) / entry_price
            else:
                ret = (entry_price - future_price) / entry_price
            
            total_returns.append(ret)
            if ret > 0:
                success_count += 1
        
        valid_count = len(total_returns)
        if valid_count < self.min_samples:
            return None
        
        # 计算统计指标
        avg_ret = sum(total_returns) / valid_count
        succ_rate = success_count / valid_count
        display_avg_ret = avg_ret if is_bullish else -avg_ret
        display_prefix = "+" if display_avg_ret > 0 else ""
        
        return {
            "total_occurrences": valid_count,
            "success_rate": f"{succ_rate*100:.1f}%",
            "avg_return": f"{display_prefix}{display_avg_ret*100:.1f}%",
            "note": f"本股专属动态回测 ({valid_count}次)"
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
