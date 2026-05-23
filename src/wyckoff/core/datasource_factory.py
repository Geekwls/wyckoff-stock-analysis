from importlib import import_module
from typing import Dict, Tuple, Type
from .datasource_strategy import DataSourceStrategy
from ..config.settings import WyckoffConfig

class DataSourceFactory:
    """数据源工厂 (P1 #2)"""

    _strategy_paths: Dict[str, Tuple[str, str]] = {
        'baostock': ('.strategies.baostock_strategy', 'BaoStockStrategy'),
        'yfinance': ('.strategies.yfinance_strategy', 'YFinanceStrategy'),
        'akshare': ('.strategies.akshare_strategy', 'AkShareStrategy'),
    }
    _strategy_cache: Dict[str, Type[DataSourceStrategy]] = {}

    @staticmethod
    def _load_strategy(source_name: str) -> Type[DataSourceStrategy]:
        key = source_name.lower()
        if key in DataSourceFactory._strategy_cache:
            return DataSourceFactory._strategy_cache[key]

        strategy_path = DataSourceFactory._strategy_paths.get(key)
        if not strategy_path:
            raise ValueError(f"不支持的数据源类型: {source_name}")

        module_name, class_name = strategy_path
        try:
            module = import_module(module_name, package=__package__)
            strategy_cls = getattr(module, class_name)
        except ImportError as exc:
            raise ImportError(f"数据源 {source_name} 的依赖未安装: {exc}") from exc

        DataSourceFactory._strategy_cache[key] = strategy_cls
        return strategy_cls

    @staticmethod
    def create(source_name: str, config: WyckoffConfig = None) -> DataSourceStrategy:
        strategy_cls = DataSourceFactory._load_strategy(source_name)
        return strategy_cls(config)
