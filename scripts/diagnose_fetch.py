#!/usr/bin/env python3
"""诊断各数据源拉取失败原因"""
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wyckoff.core.data_fetcher import WyckoffDataFetcher
from wyckoff.core.symbol_resolver import SymbolResolver
from wyckoff.config.settings import WyckoffConfig

CASES = [
    ("AAPL", "1d"),
    ("sh.600519", "1d"),
    ("sz.000001", "1d"),
    ("0700.HK", "1d"),
    ("hk.00700", "1d"),
    ("600519", "1d"),
    ("AAPL", "1w"),  # orchestrator 会拉周线
    ("0700.HK", "1w"),
]


def try_fetch(symbol: str, freq: str):
    fetcher = WyckoffDataFetcher(WyckoffConfig())
    resolver = SymbolResolver()
    print(f"\n--- {symbol} freq={freq} ---")
    try:
        info = resolver.resolve(symbol)
        print(f"  resolve: market={info.market.value} normalized={info.normalized} source={info.source}")
    except Exception as e:
        print(f"  resolve FAIL: {e}")
        return
    try:
        norm, df = fetcher.fetch_data(symbol, "1y", frequency=freq)
        print(f"  fetch OK: {norm} rows={len(df)}")
    except Exception as e:
        print(f"  fetch FAIL: {type(e).__name__}: {e}")


def try_akshare_direct():
    print("\n=== AkShare 直连测试 ===")
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol="600519", period="daily", start_date="20250101", end_date="20250523", adjust="qfq")
        print(f"  akshare direct OK rows={len(df)}")
    except Exception as e:
        print(f"  akshare direct FAIL: {type(e).__name__}: {e}")
        if "Proxy" in str(e) or "proxy" in str(e):
            print("  → 疑似本地 HTTP 代理导致 eastmoney 连接失败")


def try_yfinance_interval(symbol: str, interval: str):
    print(f"\n--- yfinance {symbol} interval={interval} ---")
    try:
        import yfinance as yf
        data = yf.Ticker(symbol).history(period="1y", interval=interval)
        print(f"  rows={len(data)} empty={data.empty}")
    except Exception as e:
        print(f"  FAIL: {e}")


if __name__ == "__main__":
    print("Proxy env:", {k: os.environ[k] for k in os.environ if "proxy" in k.lower()})
    for sym, freq in CASES:
        try_fetch(sym, freq)
    try_akshare_direct()
    for iv in ("1w", "1wk", "1d"):
        try_yfinance_interval("0700.HK", iv)
    fetcher = WyckoffDataFetcher(WyckoffConfig())
    fetcher.logout_baostock()
