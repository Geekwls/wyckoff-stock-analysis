import os
import time
import pickle
import logging
from pathlib import Path

import yfinance as yf
import pandas as pd

from ..datasource_strategy import DataSourceStrategy
from ...exceptions import DataFetchError

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {
    'd': '1d', '1d': '1d', 'daily': '1d', '5d': '5d',
    'w': '1wk', '1w': '1wk', 'weekly': '1wk', '1wk': '1wk',
    'm': '1mo', '1m': '1mo', 'monthly': '1mo', '1mo': '1mo',
    '1h': '1h', '60m': '1h', '60': '1h', 'hourly': '1h',
    '30m': '30m', '30': '30m',
    '15m': '15m', '15': '15m',
    '5m': '5m', '5': '5m',
}

_DEFAULT_TTL = 6 * 3600
_STALE_TTL = 7 * 24 * 3600


class YFinanceStrategy(DataSourceStrategy):
    """Yahoo Finance 数据源策略 (全球/加密)"""

    def is_available(self) -> bool:
        return True

    @staticmethod
    def normalize_interval(frequency: str) -> str:
        key = str(frequency).lower()
        return _INTERVAL_MAP.get(key, frequency)

    @staticmethod
    def _is_rate_limited(exc: Exception) -> bool:
        msg = str(exc).lower()
        return 'rate limit' in msg or 'too many requests' in msg

    @classmethod
    def _cache_dir(cls) -> Path:
        override = os.environ.get('WYCKOFF_CACHE_DIR')
        if override:
            root = Path(override)
        else:
            root = Path(__file__).resolve().parents[4] / '.cache'
        path = root / 'yfinance'
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _cache_path(cls, symbol: str, period: str, interval: str) -> Path:
        safe = symbol.replace('/', '-').replace('^', 'idx-')
        return cls._cache_dir() / f"{safe}_{period}_{interval}.pkl"

    @classmethod
    def _read_cache(cls, symbol: str, period: str, interval: str, max_age: int) -> pd.DataFrame | None:
        path = cls._cache_path(symbol, period, interval)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > max_age:
            return None
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            if isinstance(data, pd.DataFrame) and not data.empty:
                logger.debug(f"YFinance 缓存命中 {symbol} ({age:.0f}s)")
                return data
        except Exception as e:
            logger.debug(f"读取 YFinance 缓存失败 {path}: {e}")
        return None

    @classmethod
    def _write_cache(cls, symbol: str, period: str, interval: str, data: pd.DataFrame) -> None:
        try:
            path = cls._cache_path(symbol, period, interval)
            with open(path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.debug(f"写入 YFinance 缓存失败 {symbol}: {e}")

    def fetch(self, symbol: str, period: str, frequency: str = "1d") -> pd.DataFrame:
        yf_interval = self.normalize_interval(frequency)
        max_retries = getattr(self.config, 'max_retries', 3) if self.config else 3

        if os.environ.get('WYCKOFF_DISABLE_YF_CACHE', '').lower() not in ('1', 'true', 'yes'):
            cached = self._read_cache(symbol, period, yf_interval, _DEFAULT_TTL)
            if cached is not None:
                return cached

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                stock = yf.Ticker(symbol)
                data = stock.history(period=period, interval=yf_interval)

                if data.empty:
                    raise DataFetchError(symbol, f"YFinance 未返回数据 (interval={yf_interval})")

                data.index.name = 'Date'
                self._write_cache(symbol, period, yf_interval, data)
                return data
            except DataFetchError:
                raise
            except Exception as e:
                last_err = e
                if self._is_rate_limited(e) and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"YFinance 限流 {symbol}，{wait}s 后重试 ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    continue
                stale = self._read_cache(symbol, period, yf_interval, _STALE_TTL)
                if stale is not None and self._is_rate_limited(e):
                    logger.warning(f"YFinance 限流 {symbol}，使用过期本地缓存")
                    return stale
                logger.error(f"YFinance 获取失败 {symbol}: {e}")
                raise DataFetchError(symbol, str(e), retriable=self._is_rate_limited(e)) from e

        stale = self._read_cache(symbol, period, yf_interval, _STALE_TTL)
        if stale is not None:
            logger.warning(f"YFinance 重试耗尽 {symbol}，使用过期本地缓存")
            return stale
        raise DataFetchError(symbol, str(last_err), retriable=True)
