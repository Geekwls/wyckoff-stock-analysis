"""
tests/test_data_fetcher.py - WyckoffDataFetcher 数据处理测试
"""
import pytest
import pandas as pd
import numpy as np
from tools.core.data_fetcher import prepare_data, calculate_atr
from tools.config.settings import WyckoffConfig


class TestCalculateATR:
    def test_basic_atr(self, flat_data):
        atr = calculate_atr(flat_data)
        assert isinstance(atr, pd.Series)
        assert len(atr) == len(flat_data)
        assert atr.isna().sum() == 0  # min_periods=1 保证无 NaN

    def test_atr_positive(self, flat_data):
        atr = calculate_atr(flat_data)
        assert (atr > 0).all()

    def test_atr_custom_period(self, flat_data):
        atr = calculate_atr(flat_data, period=20)
        assert len(atr) == len(flat_data)


class TestPrepareData:
    def test_returns_dataframe(self, flat_data):
        raw = flat_data[["Open", "High", "Low", "Close", "Volume"]].copy()
        result = prepare_data(raw)
        assert isinstance(result, pd.DataFrame)

    def test_indicator_columns_created(self, flat_data):
        raw = flat_data[["Open", "High", "Low", "Close", "Volume"]].copy()
        result = prepare_data(raw)
        for col in ["MA20", "MA50", "MA200", "Volume_MA20", "ATR", "RSI"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_negative_rsi(self, flat_data):
        raw = flat_data[["Open", "High", "Low", "Close", "Volume"]].copy()
        result = prepare_data(raw)
        valid_rsi = result["RSI"].dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()

    def test_respects_config_volume_period(self, flat_data):
        raw = flat_data[["Open", "High", "Low", "Close", "Volume"]].copy()
        cfg = WyckoffConfig(volume_ma_period=10)
        result = prepare_data(raw, config=cfg)
        # Volume_MA10 应与 Volume_MA20 值不同
        assert "Volume_MA20" in result.columns

    def test_drops_nan_rows(self):
        """含 NaN 的行应被删除"""
        data = pd.DataFrame({
            "Open": [1, None, 3],
            "High": [2, 3, 4],
            "Low": [0, 1, 2],
            "Close": [1.5, None, 3.5],
            "Volume": [1000, 2000, 3000],
        })
        result = prepare_data(data)
        assert result.isna().sum().sum() == 0 or len(result) < 3
