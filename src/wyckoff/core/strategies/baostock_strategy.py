import baostock as bs
import pandas as pd
import logging
from ..datasource_strategy import DataSourceStrategy
from ...exceptions import DataFetchError

logger = logging.getLogger(__name__)

class BaoStockStrategy(DataSourceStrategy):
    """BaoStock 数据源策略 (A股)"""
    
    _logged_in: bool = False

    def is_available(self) -> bool:
        if BaoStockStrategy._logged_in:
            return True
        try:
            lg = bs.login()
            if lg.error_code == '0':
                BaoStockStrategy._logged_in = True
                return True
            logger.warning(f"baostock登录失败: {lg.error_msg}")
            return False
        except Exception as e:
            logger.error(f"baostock连接异常: {e}")
            return False

    def fetch(self, symbol: str, period: str) -> pd.DataFrame:
        if not self.is_available():
            raise DataFetchError(symbol, "BaoStock 服务不可用")

        # 归一化代码格式 (sh.600519)
        if '.' in symbol:
            parts = symbol.split('.')
            code = f"{parts[0].lower()}.{parts[1]}"
        else:
            prefix = 'sh' if symbol.startswith('6') else 'sz'
            code = f"{prefix}.{symbol}"

        end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
        period_days = {"1y": 365, "2y": 730, "3y": 1095, "5y": 1825}
        days = period_days.get(period, 365)
        start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')

        rs = bs.query_history_k_data_plus(
            code, "date,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="3"
        )

        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            raise DataFetchError(symbol, "未获取到历史数据")

        df = pd.DataFrame(data_list, columns=rs.fields)
        df = df.rename(columns={
            'date': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df.dropna(subset=['Open', 'High', 'Low', 'Close'])

    @classmethod
    def logout(cls):
        if cls._logged_in:
            bs.logout()
            cls._logged_in = False
