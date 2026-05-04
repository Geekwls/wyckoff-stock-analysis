"""
tests/test_config.py - WyckoffConfig 配置验证测试
"""
import pytest
from pydantic import ValidationError
from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds


class TestWyckoffConfig:
    def test_default_values(self):
        cfg = WyckoffConfig()
        assert cfg.confidence_threshold == 0.85
        assert cfg.min_data_length == 60
        assert cfg.atr_period == 14
        assert cfg.spring_range_threshold == 0.30

    def test_custom_values(self):
        cfg = WyckoffConfig(confidence_threshold=0.9, min_data_length=120)
        assert cfg.confidence_threshold == 0.9
        assert cfg.min_data_length == 120

    def test_invalid_confidence_threshold_too_high(self):
        with pytest.raises(ValidationError):
            WyckoffConfig(confidence_threshold=1.5)

    def test_invalid_confidence_threshold_negative(self):
        with pytest.raises(ValidationError):
            WyckoffConfig(confidence_threshold=-0.1)

    def test_invalid_min_data_length_too_small(self):
        with pytest.raises(ValidationError):
            WyckoffConfig(min_data_length=5)

    def test_invalid_min_data_length_too_large(self):
        with pytest.raises(ValidationError):
            WyckoffConfig(min_data_length=9999)

    def test_spring_lookback_bounds(self):
        cfg = WyckoffConfig(spring_lookback=252)
        assert cfg.spring_lookback == 252
        with pytest.raises(ValidationError):
            WyckoffConfig(spring_lookback=10)


class TestWyckoffThresholds:
    def test_threshold_keys_present(self):
        t = WyckoffThresholds()
        assert "spring_breakdown" in t.VOLATILITY_THRESHOLDS
        assert "low" in t.VOLATILITY_THRESHOLDS['spring_breakdown']
        assert "medium" in t.VOLATILITY_THRESHOLDS['spring_breakdown']
        assert "high" in t.VOLATILITY_THRESHOLDS['spring_breakdown']

    def test_volume_confirmation_keys(self):
        t = WyckoffThresholds()
        assert "strong" in t.VOLUME_CONFIRMATION
        assert t.VOLUME_CONFIRMATION["strong"] > 1.0
