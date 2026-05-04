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

    def fetch(self, symbol: str, period: str) -> pd.DataFrame:
        try:
            stock = yf.Ticker(symbol)
            data = stock.history(period=period)
            
            if data.empty:
                raise DataFetchError(symbol, "YFinance 未返回数据")
                
            # 标准化列名
            data.index.name = 'Date'
            return data
        except Exception as e:
            logger.error(f"YFinance 获取失败 {symbol}: {e}")
            raise DataFetchError(symbol, str(e))
