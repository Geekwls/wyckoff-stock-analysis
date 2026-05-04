import os
import json
import logging
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class MarketType(str, Enum):
    A_SHARE = "A_SHARE"
    US_STOCK = "US_STOCK"
    HK_STOCK = "HK_STOCK"
    CRYPTO = "CRYPTO"
    INDEX = "INDEX"
    UNKNOWN = "UNKNOWN"

class SymbolInfo(BaseModel):
    """解析后的代码信息"""
    original: str
    normalized: str
    market: MarketType
    source: str  # 'baostock' or 'yfinance'
    name: Optional[str] = None

class SymbolResolver:
    """代码解析器 (P1 #3)"""
    
    def __init__(self, cache_file: str = None):
        if cache_file is None:
            self.cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stock_cache.json")
        else:
            # 安全增强：防止路径穿越，强制限定在当前项目的合理目录下，或者仅接受文件名
            base_filename = os.path.basename(cache_file)
            if not base_filename.endswith('.json'):
                base_filename += '.json'
            self.cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), base_filename)
            
        self._name_cache: Dict[str, str] = self._load_cache()

    def _load_cache(self) -> Dict[str, str]:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载代码缓存失败: {e}")
        return {}

    def resolve(self, symbol: str) -> SymbolInfo:
        """解析输入的代码/名称"""
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol type")
            
        # 基础安全性校验：限制长度和特殊字符，防止注入攻击
        if len(symbol) > 50 or not all(c.isalnum() or c in '.-_/\u4e00-\u9fff' for c in symbol):
             logger.warning(f"检测到潜在的非法代码输入: {symbol}")
             # 对于明显非法的输入，直接抛出异常或返回 UNKNOWN
             return SymbolInfo(original=symbol, normalized="UNKNOWN", market=MarketType.UNKNOWN, source="none")

        original = symbol
        
        # 1. 处理中文名称解析
        if any('\u4e00' <= char <= '\u9fff' for char in symbol):
            if symbol in self._name_cache:
                symbol = self._name_cache[symbol]
            else:
                # 注意：这里可能需要调用 Baostock 获取，但 Resolver 应该是无副作用的
                # 如果缓存没中，我们暂时标记为 A_SHARE 等待 Fetcher 处理
                pass

        symbol_upper = symbol.upper()
        
        # 2. 识别市场与归一化
        # A股逻辑
        if symbol_upper.startswith(('SH.', 'SZ.')) or (symbol.isdigit() and len(symbol) == 6):
            normalized = symbol_upper
            if symbol.isdigit():
                prefix = 'SH' if symbol.startswith('6') else 'SZ'
                normalized = f"{prefix}.{symbol}"
            return SymbolInfo(
                original=original,
                normalized=normalized,
                market=MarketType.A_SHARE,
                source='baostock'
            )
        
        # 港股逻辑
        if symbol_upper.endswith('.HK'):
            return SymbolInfo(
                original=original,
                normalized=symbol_upper,
                market=MarketType.HK_STOCK,
                source='yfinance'
            )
            
        # 加密货币逻辑 (如 BTC-USD, ETH/USDT)
        if '-' in symbol_upper or '/' in symbol_upper or symbol_upper in ['BTC', 'ETH', 'SOL']:
            normalized = symbol_upper.replace('/', '-')
            if '-' not in normalized: normalized += "-USD"
            return SymbolInfo(
                original=original,
                normalized=normalized,
                market=MarketType.CRYPTO,
                source='yfinance'
            )

        # 默认视为美股
        return SymbolInfo(
            original=original,
            normalized=symbol_upper,
            market=MarketType.US_STOCK,
            source='yfinance'
        )

    def update_name_cache(self, name: str, code: str):
        self._name_cache[name] = code
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._name_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"更新代码缓存失败: {e}")
