"""
AkShare 数据源策略 (A股)
替代 baostock，速度更快，无限流问题
"""
import akshare as ak
import pandas as pd
import logging
from ..datasource_strategy import DataSourceStrategy
from ...exceptions import DataFetchError

logger = logging.getLogger(__name__)


class AkShareStrategy(DataSourceStrategy):
    """AkShare 数据源策略 (A股)"""
    
    def is_available(self) -> bool:
        return True
    
    def fetch(self, symbol: str, period: str, frequency: str = "1d") -> pd.DataFrame:
        """
        使用 akshare 获取 A 股历史数据
        
        Args:
            symbol: 股票代码（如 "sh.600519" 或 "sz.000977"）
            period: 数据周期（如 "1y", "2y"）
            frequency: 数据频率（如 "d", "w", "m"）
        """
        try:
            # 转换为纯代码格式（akshare 需要）
            if '.' in symbol:
                parts = symbol.split('.')
                code = parts[1]
            else:
                code = symbol
            
            # 计算日期范围
            period_days = {"1y": 365, "2y": 730, "3y": 1095, "5y": 1825}
            days = period_days.get(period, 365)
            
            from datetime import datetime, timedelta
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
            
            # akshare 频率映射
            freq_lower = str(frequency).lower()
            if freq_lower in ("d", "1d", "daily"):
                ak_period = "daily"
            elif freq_lower in ("w", "1w", "weekly"):
                ak_period = "weekly"
            elif freq_lower in ("m", "1m", "monthly"):
                ak_period = "monthly"
            else:
                ak_period = "daily"
            
            # 获取历史数据
            df = ak.stock_zh_a_hist(
                symbol=code,
                period=ak_period,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )
            
            if df is None or df.empty:
                raise DataFetchError(symbol, f"AkShare 未返回数据")
            
            # 标准化列名
            column_mapping = {
                '日期': 'Date',
                '开盘': 'Open',
                '收盘': 'Close',
                '最高': 'High',
                '最低': 'Low',
                '成交量': 'Volume',
                '成交额': 'Amount',
                '振幅': 'Amplitude',
                '涨跌幅': 'PctChange',
                '涨跌额': 'Change',
                '换手率': 'Turnover',
            }
            
            df = df.rename(columns=column_mapping)
            
            # 设置日期索引
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.set_index('Date')
            
            # 确保数值类型
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 保留 Amount 列
            if 'Amount' in df.columns:
                df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
            
            return df.dropna(subset=['Open', 'High', 'Low', 'Close'])
            
        except DataFetchError:
            raise
        except Exception as e:
            logger.error(f"AkShare 获取 {symbol} 失败: {e}")
            raise DataFetchError(symbol, f"AkShare 获取失败: {str(e)}")
