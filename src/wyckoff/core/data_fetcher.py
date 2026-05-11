import pandas as pd
import logging
from typing import Tuple, Optional

from ..exceptions import DataFetchError, InsufficientDataError, WyckoffError
from ..config.settings import WyckoffConfig
from .symbol_resolver import SymbolResolver, MarketType
from .datasource_factory import DataSourceFactory
from .data_validator import DataValidator, ChineseSymbolHandler
from .technical_indicators import TechnicalIndicators, ATR

logger = logging.getLogger(__name__)

def prepare_data(data: pd.DataFrame, config: WyckoffConfig = None) -> pd.DataFrame:
    """
    预计算常用指标

    增强版本：
    1. 数据质量验证
    2. 数据清理
    3. 指标计算
    """
    cfg = config or WyckoffConfig()

    # 1. 数据质量验证
    report = DataValidator.validate_dataframe(data)
    if not report.ok:
        for issue in report.issues:
            logger.warning(f"[{issue.severity}] {issue.category}: {issue.message}")
        logger.info("尝试自动清理数据...")
        df = DataValidator.clean_dataframe(data)
    else:
        df = data.copy()

    # 2. 数据类型转换
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 3. 删除包含关键缺失值的行
    df = df.dropna(subset=['High', 'Low', 'Close', 'Volume'])

    # 4. 计算技术指标（使用统一的工具类）
    df['MA20'] = TechnicalIndicators.price_ma(df, 20)
    df['MA50'] = TechnicalIndicators.price_ma(df, 50)
    df['MA200'] = TechnicalIndicators.price_ma(df, 200)
    df['Volume_MA20'] = TechnicalIndicators.volume_ma(df, cfg.volume_ma_period)

    # ATR 和 RSI
    df['ATR'] = ATR(df, cfg.atr_period)
    df['RSI'] = TechnicalIndicators.rsi(df)

    # 滚动极值
    for w in [20, 60, 120]:
        df[f'High_Max_{w}'] = TechnicalIndicators.rolling_max(df, 'High', w)
        df[f'Low_Min_{w}'] = TechnicalIndicators.rolling_min(df, 'Low', w)

    return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    计算ATR的便捷函数（为了向后兼容）

    Args:
        df: 包含 High, Low, Close 列的 DataFrame
        period: ATR周期（默认14）

    Returns:
        ATR序列
    """
    return ATR(df, period)


class WyckoffDataFetcher:
    """威科夫数据获取器 - Facade (P1 #2)"""

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.resolver = SymbolResolver()

    def fetch_data(self, symbol: str, period: str, frequency: str = "1d") -> Tuple[str, pd.DataFrame]:
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

            # 2. 特殊处理：中文名称（使用改进的处理器）
            if info.market == MarketType.US_STOCK and ChineseSymbolHandler.is_chinese_name(symbol):
                # 规范化中文名称
                normalized_name = ChineseSymbolHandler.normalize_chinese_name(symbol)

                # 尝试在 A 股库中搜索
                from .strategies.baostock_strategy import BaoStockStrategy
                bs_search = BaoStockStrategy(self.config)

                # 借用旧逻辑中的搜索
                code = self._search_a_share_name(normalized_name)
                if code:
                    self.resolver.update_name_cache(symbol, code)
                    info = self.resolver.resolve(code)
                else:
                    logger.warning(f"无法找到中文名称 '{normalized_name}' 对应的股票代码")

            # 3. 获取对应策略并抓取
            strategy = DataSourceFactory.create(info.source, self.config)
            data = strategy.fetch(info.normalized, period, frequency=frequency)

            # 4. 数据质量验证
            if data is not None and len(data) > 0:
                report = DataValidator.validate_dataframe(data)
                if not report.ok:
                    for issue in report.issues:
                        logger.warning(f"[{issue.severity}] {issue.category}: {issue.message}")
                    logger.info("尝试自动清理数据...")
                    data = DataValidator.clean_dataframe(data)

            is_daily = frequency and "d" in str(frequency).lower()
            if data is None or (is_daily and len(data) < self.config.min_data_length):
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
        except Exception as e:
            logger.warning(f"A股名称搜索失败: {e}")
        return None

    def _is_a_stock(self, symbol: str) -> bool:
        """检查是否为 A 股（委派至 resolver）"""
        info = self.resolver.resolve(symbol)
        return info.market == MarketType.A_SHARE

    def logout_baostock(self):
        """释放资源"""
        from .strategies.baostock_strategy import BaoStockStrategy
        BaoStockStrategy.logout()
