import yfinance as yf
import pandas as pd
import logging
from ..datasource_strategy import DataSourceStrategy
from ...exceptions import DataFetchError

logger = logging.getLogger(__name__)

class YFinanceStrategy(DataSourceStrategy):
    """Yahoo Finance 数据源策略 (全球/加密)"""

    def is_available(self) -> bool:
        # yfinance 通常总是可用的，除非网络问题
        return True

    def fetch(self, symbol: str, period: str, frequency: str = "1d") -> pd.DataFrame:
        try:
            # yfinance 频率映射
            yf_interval = frequency
            
            stock = yf.Ticker(symbol)
            # 对于 intraday，period 可能需要调整，但 yfinance 比较灵活
            data = stock.history(period=period, interval=yf_interval)
            
            if data.empty:
                raise DataFetchError(symbol, f"YFinance 未返回数据 (interval={yf_interval})")
                
            # 标准化列名
            data.index.name = 'Date'
            return data
        except Exception as e:
            logger.error(f"YFinance 获取失败 {symbol}: {e}")
            raise DataFetchError(symbol, str(e))
