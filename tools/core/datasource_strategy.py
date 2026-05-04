from abc import ABC, abstractmethod
import pandas as pd
from typing import Tuple
from ..config.settings import WyckoffConfig

class DataSourceStrategy(ABC):
    """数据源策略基类 (P1 #2)"""
    
    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()

    @abstractmethod
    def fetch(self, symbol: str, period: str) -> pd.DataFrame:
        """
        获取原始数据
        
        Args:
            symbol: 已解析的标准代码
            period: 时间范围 (如 '1y', '2y')
            
        Returns:
            pd.DataFrame: OHLCV 数据框
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用（如登录状态、API Key）"""
        pass
