import yfinance as yf
import baostock as bs
import pandas as pd
import json
import os
import logging
from typing import Optional

from ..exceptions import DataFetchError, InsufficientDataError, WyckoffError
from ..config.settings import WyckoffConfig

logger = logging.getLogger(__name__)

def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算ATR（Average True Range）"""
    high = pd.to_numeric(data['High'], errors='coerce')
    low = pd.to_numeric(data['Low'], errors='coerce')
    close = pd.to_numeric(data['Close'], errors='coerce').shift(1)

    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=1).mean()

    return pd.Series(atr, index=data.index, name='ATR')

def prepare_data(data: pd.DataFrame, config: WyckoffConfig = None) -> pd.DataFrame:
    """预计算常用指标"""
    cfg = config or WyckoffConfig()
    df = data.copy()

    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['High', 'Low', 'Close', 'Volume'])

    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['MA50'] = df['Close'].rolling(50, min_periods=1).mean()
    df['MA200'] = df['Close'].rolling(200, min_periods=1).mean()
    df['Volume_MA20'] = df['Volume'].rolling(cfg.volume_ma_period, min_periods=1).mean()

    df['ATR'] = calculate_atr(df, cfg.atr_period)

    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
    rs = gain / loss.replace(0, float('nan'))
    df['RSI'] = 100 - (100 / (1 + rs.fillna(0)))

    # 新增常用滚动极值，减少各检测器重复计算
    for w in [20, 60, 120]:
        df[f'High_Max_{w}'] = df['High'].rolling(w, min_periods=1).max()
        df[f'Low_Min_{w}'] = df['Low'].rolling(w, min_periods=1).min()

    return df

class WyckoffDataFetcher:
    """威科夫数据获取器"""
    _bs_logged_in: bool = False

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stock_cache.json")

    def _is_a_stock(self, symbol: str) -> bool:
        symbol_upper = symbol.upper()
        if symbol.isdigit():
            return True
        if symbol_upper.endswith(('.SH', '.SZ')):
            return True
        if symbol_upper.startswith(('SH.', 'SZ.')):
            return True
        # 港股（.HK）通过 yfinance 获取，不走 baostock
        if symbol_upper.endswith('.HK'):
            return False
        return False

    def _resolve_stock_name(self, name: str) -> Optional[str]:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if name in cache:
                    return cache[name]
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"读取股票缓存失败: {e}")

        code = self._search_from_baostock(name)
        if code:
            self._update_cache(name, code)
            return code
        return None

    def _ensure_bs_login(self) -> bool:
        if WyckoffDataFetcher._bs_logged_in:
            return True
        try:
            lg = bs.login()
            if lg.error_code == '0':
                WyckoffDataFetcher._bs_logged_in = True
                return True
            logger.warning(f"baostock登录失败: {lg.error_msg}")
            return False
        except (ConnectionError, OSError) as e:
            logger.exception(f"baostock登录网络异常: {e}")
            return False

    @classmethod
    def logout_baostock(cls):
        if cls._bs_logged_in:
            try:
                bs.logout()
            except (ConnectionError, OSError):
                pass
            cls._bs_logged_in = False

    def _search_from_baostock(self, keyword: str) -> Optional[str]:
        if not self._ensure_bs_login():
            return None
        try:
            rs = bs.query_stock_basic()
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())

            if data_list:
                df = pd.DataFrame(data_list, columns=rs.fields)
                match = df[df['code_name'].str.contains(keyword, na=False)]
                if not match.empty:
                    return match.iloc[0]['code']
        except (ConnectionError, OSError) as e:
            logger.exception(f"baostock查询网络异常 keyword={keyword}: {e}")
        return None

    def _update_cache(self, name: str, code: str):
        cache = {}
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            except Exception:
                pass

        cache[name] = code
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logger.warning(f"缓存写入失败: {e}")

    def fetch_data(self, symbol: str, period: str) -> tuple[str, pd.DataFrame]:
        try:
            original_symbol = symbol
            if any('\u4e00' <= char <= '\u9fff' for char in symbol):
                resolved = self._resolve_stock_name(symbol)
                if resolved:
                    symbol = resolved
                else:
                    raise DataFetchError(original_symbol, f"无法识别股票名称: {original_symbol}")

            if self._is_a_stock(symbol):
                data = self._fetch_a_stock_data(symbol, period)
            else:
                data = self._fetch_global_stock_data(symbol, period)
            
            if data is None or len(data) < self.config.min_data_length:
                raise InsufficientDataError(
                    symbol, 
                    self.config.min_data_length, 
                    len(data) if data is not None else 0
                )
            
            return symbol, prepare_data(data, self.config)

        except WyckoffError:
            raise
        except Exception as e:
            logger.exception(f"获取数据异常 symbol={symbol}")
            raise DataFetchError(symbol, str(e)) from e

    def _fetch_a_stock_data(self, symbol: str, period: str) -> pd.DataFrame:
        if '.' in symbol:
            parts = symbol.split('.')
            code = f"{parts[1].lower()}.{parts[0]}"
        else:
            prefix = 'sh' if symbol.startswith('6') else 'sz'
            code = f"{prefix}.{symbol}"

        end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
        period_days = {"1y": 365, "2y": 730, "3y": 1095, "5y": 1825}
        days = period_days.get(period, 365)
        start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')

        if not self._ensure_bs_login():
            raise DataFetchError(symbol, "baostock登录失败")

        rs = bs.query_history_k_data_plus(
            code, "date,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="3"
        )

        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            raise DataFetchError(symbol, "未获取到数据")

        df = pd.DataFrame(data_list, columns=rs.fields)
        df = df.rename(columns={
            'date': 'Date', 'open': 'Open', 'high': 'High',
            'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'amount']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 移除含有空价格的行
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
        return df

    def _fetch_global_stock_data(self, symbol: str, period: str) -> pd.DataFrame:
        stock = yf.Ticker(symbol)
        data = stock.history(period=period)

        if data.empty:
            raise DataFetchError(symbol, "未获取到数据")

        return data
