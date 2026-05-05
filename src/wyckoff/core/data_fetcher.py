import pandas as pd
import logging
from typing import Tuple, Optional

from ..exceptions import DataFetchError, InsufficientDataError, WyckoffError
from ..config.settings import WyckoffConfig
from .symbol_resolver import SymbolResolver, MarketType
from .datasource_factory import DataSourceFactory

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
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    
    # 使用 Wilder's Smoothing (EMA based)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, float('nan'))
    df['RSI'] = 100 - (100 / (1 + rs.fillna(0)))

    # 滚动极值
    for w in [20, 60, 120]:
        df[f'High_Max_{w}'] = df['High'].rolling(w, min_periods=1).max()
        df[f'Low_Min_{w}'] = df['Low'].rolling(w, min_periods=1).min()

    return df

class WyckoffDataFetcher:
    """威科夫数据获取器 - Facade (P1 #2)"""

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.resolver = SymbolResolver()

    def fetch_data(self, symbol: str, period: str, frequency: str = "d") -> Tuple[str, pd.DataFrame]:
        """
        统一获取数据入口
        1. 解析代码 (SymbolResolver)
        2. 获取策略 (DataSourceFactory)
        3. 执行获取 (DataSourceStrategy)
        4. 数据准备 (prepare_data)
        """
        try:
            # 1. 解析代码
            info = self.resolver.resolve(symbol)
            
            # 2. 特殊处理：中文名称如果未中缓存，尝试在 A 股库中搜索一次
            if info.market == MarketType.US_STOCK and any('\u4e00' <= char <= '\u9fff' for char in symbol):
                # 这是一个回退逻辑，如果 Resolver 没识别出 A 股且带中文，可能是还没入库的代码
                from .strategies.baostock_strategy import BaoStockStrategy
                bs_search = BaoStockStrategy(self.config)
                # 借用旧逻辑中的搜索
                code = self._search_a_share_name(symbol)
                if code:
                    self.resolver.update_name_cache(symbol, code)
                    info = self.resolver.resolve(code)

            # 3. 获取对应策略并抓取
            strategy = DataSourceFactory.create(info.source, self.config)
            data = strategy.fetch(info.normalized, period, frequency=frequency)

            if data is None or (frequency == "d" and len(data) < self.config.min_data_length):
                raise InsufficientDataError(
                    info.normalized, 
                    self.config.min_data_length, 
                    len(data) if data is not None else 0
                )

            return info.normalized, prepare_data(data, self.config)

        except WyckoffError:
            raise
        except Exception as e:
            logger.exception(f"获取数据异常 symbol={symbol}")
            raise DataFetchError(symbol, str(e)) from e

    def _search_a_share_name(self, name: str) -> Optional[str]:
        """搜索 A 股名称的辅助逻辑 (兼容旧功能)"""
        try:
            import baostock as bs
            if bs.login().error_code == '0':
                rs = bs.query_stock_basic()
                while (rs.error_code == '0') & rs.next():
                    row = rs.get_row_data()
                    if name in row[1]: # code_name
                        return row[0] # code
                bs.logout()
        except Exception:
            pass
        return None

    def _is_a_stock(self, symbol: str) -> bool:
        """检查是否为 A 股（委派至 resolver）"""
        info = self.resolver.resolve(symbol)
        return info.market == MarketType.A_SHARE

    def logout_baostock(self):
        """释放资源"""
        from .strategies.baostock_strategy import BaoStockStrategy
        BaoStockStrategy.logout()
