import os
import json
import logging
import re
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_US_HYPHEN_TICKER = re.compile(r'^[A-Z]{1,5}-[A-Z]$')
_CRYPTO_QUOTE_CURRENCIES = frozenset({'USD', 'USDT', 'USDC', 'BTC', 'ETH', 'EUR', 'GBP', 'JPY'})

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
    is_st: bool = Field(default=False, description="是否为ST股")

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
        if len(symbol) > 50 or not all(c.isalnum() or c in '* .-_/\u4e00-\u9fff' for c in symbol):
             logger.warning(f"检测到潜在的非法代码输入: {symbol}")
             # 对于明显非法的输入，直接抛出异常或返回 UNKNOWN
             return SymbolInfo(original=symbol, normalized="UNKNOWN", market=MarketType.UNKNOWN, source="none")

        original = symbol
        is_st = "ST" in original.upper() or "*ST" in original.upper()
        
        # 1. 处理中文名称解析
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in symbol)
        if has_chinese:
            if symbol in self._name_cache:
                symbol = self._name_cache[symbol]
            else:
                # 如果包含中文且包含 ST，基本确定是 A 股
                if is_st:
                    return SymbolInfo(
                        original=original,
                        normalized=original,
                        market=MarketType.A_SHARE,
                        source='akshare',
                        is_st=True
                    )
        
        symbol_upper = symbol.upper()
        
        # 2. 识别市场与归一化
        # A股逻辑
        if symbol_upper.startswith(('SH.', 'SZ.', 'BJ.')) or (symbol.isdigit() and len(symbol) == 6):
            normalized = symbol_upper
            if symbol.isdigit():
                if symbol.startswith(('60', '68')):
                    prefix = 'SH'
                elif symbol.startswith(('43', '83', '87', '88')):
                    prefix = 'BJ'
                else:
                    prefix = 'SZ'
                normalized = f"{prefix}.{symbol}"
            return SymbolInfo(
                original=original,
                normalized=normalized,
                market=MarketType.A_SHARE,
                source='akshare',
                is_st=is_st
            )
        
        # 港股逻辑
        if symbol_upper.endswith('.HK'):
            return SymbolInfo(
                original=original,
                normalized=symbol_upper,
                market=MarketType.HK_STOCK,
                source='yfinance',
                is_st=is_st
            )

        # 带连字符的美股（如 BRK-B、BF-B）优先于 crypto 判定
        if _US_HYPHEN_TICKER.match(symbol_upper):
            return SymbolInfo(
                original=original,
                normalized=symbol_upper,
                market=MarketType.US_STOCK,
                source='yfinance',
                is_st=is_st
            )

        # 加密货币 (如 BTC-USD, ETH/USDT)
        if '/' in symbol_upper:
            normalized = symbol_upper.replace('/', '-')
            return SymbolInfo(
                original=original,
                normalized=normalized,
                market=MarketType.CRYPTO,
                source='yfinance',
                is_st=is_st
            )

        if '-' in symbol_upper:
            parts = symbol_upper.split('-', 1)
            if len(parts) == 2 and parts[1] in _CRYPTO_QUOTE_CURRENCIES:
                return SymbolInfo(
                    original=original,
                    normalized=symbol_upper,
                    market=MarketType.CRYPTO,
                    source='yfinance',
                    is_st=is_st
                )
            if _US_HYPHEN_TICKER.match(symbol_upper):
                return SymbolInfo(
                    original=original,
                    normalized=symbol_upper,
                    market=MarketType.US_STOCK,
                    source='yfinance',
                    is_st=is_st
                )

        if symbol_upper in ['BTC', 'ETH', 'SOL']:
            return SymbolInfo(
                original=original,
                normalized=f"{symbol_upper}-USD",
                market=MarketType.CRYPTO,
                source='yfinance',
                is_st=is_st
            )

        # 默认视为美股
        return SymbolInfo(
            original=original,
            normalized=symbol_upper,
            market=MarketType.US_STOCK,
            source='yfinance',
            is_st=is_st
        )

    def update_name_cache(self, name: str, code: str):
        self._name_cache[name] = code
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._name_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"更新代码缓存失败: {e}")
