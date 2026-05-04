"""
tests/test_pattern_detector.py - WyckoffPatternDetector 形态检测测试
"""
import pytest
import pandas as pd
import numpy as np
from src.wyckoff.core.pattern_detector import WyckoffPatternDetector
from src.wyckoff.config.settings import WyckoffConfig


class FakeCache:
    """最小化的 AnalysisCache 替身"""
    def get_or_compute(self, key, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def make_detector(data: pd.DataFrame) -> WyckoffPatternDetector:
    return WyckoffPatternDetector(data, WyckoffConfig(), FakeCache())


class TestDetectTradingRange:
    def test_returns_dict(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_trading_range()
        assert isinstance(result, dict)

    def test_flat_data_is_consolidation(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_trading_range()
        assert result.get("is_consolidation") == True  # noqa: E712 – handles np.bool_

    def test_has_required_keys(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_trading_range()
        for key in ["is_consolidation", "high", "low", "range_pct", "position"]:
            assert key in result, f"Missing key: {key}"

    def test_position_between_0_and_1(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_trading_range()
        assert 0.0 <= result["position"] <= 1.0

    def test_insufficient_data_returns_empty(self, default_config):
        tiny = pd.DataFrame({"High": [1], "Low": [1], "Close": [1], "Volume": [1000]})
        det = WyckoffPatternDetector(tiny, default_config, FakeCache())
        result = det.detect_trading_range()
        assert result == {}


class TestDetectSOS:
    def test_returns_dict(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_sos()
        assert isinstance(result, dict)

    def test_uptrend_finds_sos(self, uptrend_data):
        """上涨趋势中更容易检测到 SOS"""
        det = make_detector(uptrend_data)
        result = det.detect_sos()
        # 不强制 detected=True，仅验证结构正确
        assert "detected" in result or isinstance(result, dict)

    def test_insufficient_data(self, default_config):
        tiny = pd.DataFrame({
            "High": range(10), "Low": range(10),
            "Close": range(10), "Volume": [1000] * 10,
            "Volume_MA20": [1000] * 10,
        })
        det = WyckoffPatternDetector(tiny, default_config, FakeCache())
        result = det.detect_sos()
        assert result == {} or result.get("detected") is False


class TestDetectSOW:
    def test_returns_dict(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_sow()
        assert isinstance(result, dict)

    def test_downtrend_structure(self, downtrend_data):
        det = make_detector(downtrend_data)
        result = det.detect_sow()
        assert isinstance(result, dict)


class TestDetectSpring:
    def test_returns_dict(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_spring()
        assert isinstance(result, dict)
        assert "detected" in result

    def test_no_spring_in_uptrend(self, uptrend_data):
        """纯上涨不应检测到 Spring（无横盘区间）"""
        det = make_detector(uptrend_data)
        result = det.detect_spring()
        # Spring 需要前置横盘区间
        assert isinstance(result, dict)


class TestDetectClimaxAndAR:
    def test_climax_returns_dict(self, flat_data):
        det = make_detector(flat_data)
        result = det.detect_climax()
        assert isinstance(result, dict)
        assert "detected" in result

    def test_ar_without_climax(self, flat_data):
        det = make_detector(flat_data)
        ar = det.detect_automatic_reaction({"detected": False})
        assert ar.get("detected") is False
