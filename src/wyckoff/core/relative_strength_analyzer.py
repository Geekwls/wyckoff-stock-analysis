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

            if current_rs_ma20 > current_rs_ma50:
                rs_trend = 'rising'
            elif current_rs_ma20 < current_rs_ma50:
                rs_trend = 'falling'
            else:
                rs_trend = 'flat'

            rs_change_20d = (rs.iloc[-1] / rs.iloc[-20] - 1) * 100 if len(rs) >= 20 else 0

            #  问题三修复：检测RS异常值
            # 对于成熟股票，20日RS变化超过±30%极其罕见
            # 可能原因：除权除息未调整、数据断点、极端行情
            rs_anomaly_warning = None
            if abs(rs_change_20d) > 30:
                rs_anomaly_warning = (
                    f"⚠️ RS值异常警告：20日RS变化为{rs_change_20d:.2f}%，"
                    f"对于成熟股票此数值极为罕见。可能原因："
                    f"1) 除权除息未调整导致价格断点；"
                    f"2) 数据源存在质量问题；"
                    f"3) 近期确实发生极端行情（并购、拆分等）。"
                    f"建议：核查原始数据或使用复权价格。"
                )
                logger.warning(f"[{self.stock_symbol}] {rs_anomaly_warning}")

            divergence_flag = rs_change_20d < -3
            market_confirmed_weak = (b_data['Close'].iloc[-1] / b_data['Close'].iloc[-20] - 1) * 100 < -2

            result = {
                'rs_trend': rs_trend,
                'rs_value': round(rs.iloc[-1], 6),
                'rs_change_20d': round(rs_change_20d, 2),
                'is_outperforming': rs_trend == 'rising',
                'divergence_alert': divergence_flag,
                'short_priority_adjustment': 'decrease' if divergence_flag and not market_confirmed_weak else 'increase' if market_confirmed_weak and rs_trend == 'falling' else 'neutral',
                'description': f"相对强度{ '走强' if rs_trend == 'rising' else '走弱'}，20日相对涨幅 {round(rs_change_20d, 2)}%"
            }

            # 添加异常警告（如果有）
            if rs_anomaly_warning:
                result['rs_anomaly_warning'] = rs_anomaly_warning

            return result
        except Exception as e:
            logger.error(f"Error calculating RS for {self.stock_symbol}: {e}")
            return {'rs_trend': 'unknown', 'error': str(e)}
