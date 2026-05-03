import pandas as pd
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class RelativeStrengthAnalyzer:
    """
    相对强度分析器
    提取自 WyckoffAnalyzer，负责个股与基准指数的对比分析
    """
    def __init__(self, stock_data: pd.DataFrame, stock_symbol: str):
        self.stock_data = stock_data
        self.stock_symbol = stock_symbol

    def calculate_rs(self, benchmark_data: pd.DataFrame) -> Dict:
        """计算相对强度趋势"""
        try:
            if self.stock_data is None or benchmark_data is None:
                return {'rs_trend': 'unknown', 'rs_value': None}

            common_dates = self.stock_data.index.intersection(benchmark_data.index)
            if len(common_dates) < 20:
                return {'rs_trend': 'unknown', 'rs_value': None}

            s_data = self.stock_data.loc[common_dates]
            b_data = benchmark_data.loc[common_dates]
            
            rs = s_data['Close'] / b_data['Close']
            rs_ma20 = rs.rolling(20).mean()
            rs_ma50 = rs.rolling(50).mean()
            
            current_rs_ma20 = rs_ma20.iloc[-1]
            current_rs_ma50 = rs_ma50.iloc[-1]
            
            if current_rs_ma20 > current_rs_ma50: rs_trend = 'rising'
            elif current_rs_ma20 < current_rs_ma50: rs_trend = 'falling'
            else: rs_trend = 'flat'
            
            rs_change_20d = (rs.iloc[-1] / rs.iloc[-20] - 1) * 100 if len(rs) >= 20 else 0
            
            return {
                'rs_trend': rs_trend,
                'rs_value': round(rs.iloc[-1], 6),
                'rs_change_20d': round(rs_change_20d, 2),
                'is_outperforming': rs_trend == 'rising',
                'description': f"相对强度{ '走强' if rs_trend == 'rising' else '走弱'}，20日相对涨幅 {round(rs_change_20d, 2)}%"
            }
        except Exception as e:
            logger.error(f"Error calculating RS for {self.stock_symbol}: {e}")
            return {'rs_trend': 'unknown', 'error': str(e)}
