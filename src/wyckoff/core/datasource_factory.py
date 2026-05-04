from typing import Dict, Type
from .datasource_strategy import DataSourceStrategy
from .strategies.baostock_strategy import BaoStockStrategy
from .strategies.yfinance_strategy import YFinanceStrategy
from ..config.settings import WyckoffConfig

class DataSourceFactory:
    """数据源工厂 (P1 #2)"""
    
    _strategies: Dict[str, Type[DataSourceStrategy]] = {
        'baostock': BaoStockStrategy,
        'yfinance': YFinanceStrategy
    }

    @staticmethod
    def create(source_name: str, config: WyckoffConfig = None) -> DataSourceStrategy:
        strategy_cls = DataSourceFactory._strategies.get(source_name.lower())
        if not strategy_cls:
            raise ValueError(f"不支持的数据源类型: {source_name}")
        return strategy_cls(config)
