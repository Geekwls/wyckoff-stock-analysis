"""
共享测试夹具 (fixtures)
"""
import pytest
import pandas as pd
import numpy as np

from wyckoff.config.settings import WyckoffConfig


def _make_ohlcv(n: int = 300, trend: str = "flat", seed: int = 42) -> pd.DataFrame:
    """生成用于测试的模拟 OHLCV 数据"""
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.ones(n) * 100.0

    if trend == "up":
        close += np.linspace(0, 30, n)
    elif trend == "down":
        close -= np.linspace(0, 30, n)
    elif trend == "spring":
        # 前60天横盘，然后急跌再快速回升
        close[60:65] -= 8
        close[65:] += 0.1

    noise = np.random.randn(n) * 0.5
    close += noise

    high  = close + np.abs(np.random.randn(n)) * 0.8
    low   = close - np.abs(np.random.randn(n)) * 0.8
    open_ = close + np.random.randn(n) * 0.3
    volume = np.random.randint(500_000, 2_000_000, n).astype(float)

    df = pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": volume,
    }, index=dates)

    # 预计算均线（和 data_fetcher.prepare_data 保持一致）
    df["MA20"]  = df["Close"].rolling(20, min_periods=1).mean()
    df["MA50"]  = df["Close"].rolling(50, min_periods=1).mean()
    df["MA200"] = df["Close"].rolling(200, min_periods=1).mean()
    df["Volume_MA20"] = df["Volume"].rolling(20, min_periods=1).mean()
    df["ATR"] = (df["High"] - df["Low"]).rolling(14, min_periods=1).mean()

    return df


@pytest.fixture
def flat_data():
    return _make_ohlcv(300, "flat")

@pytest.fixture
def uptrend_data():
    return _make_ohlcv(300, "up")

@pytest.fixture
def downtrend_data():
    return _make_ohlcv(300, "down")

@pytest.fixture
def spring_data():
    return _make_ohlcv(300, "spring")

@pytest.fixture
def default_config():
    return WyckoffConfig()
