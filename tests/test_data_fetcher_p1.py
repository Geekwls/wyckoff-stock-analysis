import unittest
import pandas as pd
from src.wyckoff.core.data_fetcher import WyckoffDataFetcher
from src.wyckoff.core.symbol_resolver import MarketType

class TestDataFetcherRefactoring(unittest.TestCase):
    def setUp(self):
        self.fetcher = WyckoffDataFetcher()

    def test_symbol_resolver_a_share(self):
        info = self.fetcher.resolver.resolve("600519")
        self.assertEqual(info.market, MarketType.A_SHARE)
        self.assertEqual(info.normalized, "SH.600519")
        self.assertEqual(info.source, "baostock")

    def test_symbol_resolver_us_stock(self):
        info = self.fetcher.resolver.resolve("AAPL")
        self.assertEqual(info.market, MarketType.US_STOCK)
        self.assertEqual(info.normalized, "AAPL")
        self.assertEqual(info.source, "yfinance")

    def test_symbol_resolver_crypto(self):
        info = self.fetcher.resolver.resolve("BTC/USDT")
        self.assertEqual(info.market, MarketType.CRYPTO)
        self.assertEqual(info.normalized, "BTC-USDT")
        self.assertEqual(info.source, "yfinance")

    def test_symbol_resolver_hk_stock(self):
        info = self.fetcher.resolver.resolve("0700.HK")
        self.assertEqual(info.market, MarketType.HK_STOCK)
        self.assertEqual(info.normalized, "0700.HK")

if __name__ == '__main__':
    unittest.main()
