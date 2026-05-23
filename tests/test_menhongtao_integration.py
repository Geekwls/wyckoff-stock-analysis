"""孟洪涛增强模块集成测试（使用 mock 数据，无网络依赖）"""

import numpy as np
import pandas as pd
import pytest

from wyckoff.core.law_analyzer import WyckoffLawAnalyzer
from wyckoff.core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from wyckoff.core.pattern_detector import WyckoffPatternDetector
from wyckoff.core.relative_strength_analyzer import RelativeStrengthAnalyzer
from wyckoff.wyckoff_analyzer import WyckoffAnalyzer


def _build_menhongtao_mock_df() -> pd.DataFrame:
    dates = pd.date_range(start="2024-01-01", periods=200, freq="D")
    prices = []
    volumes = []

    for i in range(200):
        if i < 100:
            prices.append(20.0 + np.sin(i * 0.1) * 0.5)
            volumes.append(1_000_000 + (i % 3) * 100_000)
        elif i < 106:
            prices.append(19.0 + (i - 100) * 0.2)
            volumes.append(2_500_000)
        elif i < 151:
            prices.append(20.0 + (i - 106) * 0.005)
            volumes.append(800_000)
        elif i < 156:
            prices.append(20.5 + (i - 150) * 0.4)
            volumes.append(3_000_000)
        else:
            prices.append(22.0 + np.sin(i * 0.1) * 0.1)
            volumes.append(1_200_000)

    df = pd.DataFrame(
        {
            "Open": [p * 0.99 for p in prices],
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.98 for p in prices],
            "Close": prices,
            "Volume": volumes,
        },
        index=dates,
    )
    df["Volume_MA20"] = df["Volume"].rolling(20).mean().fillna(1_000_000.0)
    df["MA20"] = df["Close"].rolling(20).mean().fillna(20.0)
    df["MA50"] = df["Close"].rolling(50).mean().fillna(20.0)
    df["MA200"] = df["Close"].rolling(200).mean().fillna(20.0)
    df["ATR"] = (df["High"] - df["Low"]).rolling(14).mean().fillna(0.4)
    return df


@pytest.fixture
def menhongtao_analyzer(monkeypatch):
    mock_df = _build_menhongtao_mock_df()

    def mock_fetch_data(self, frequency: str = "1d") -> pd.DataFrame:
        self.data = mock_df.copy()
        self.pattern_detector = WyckoffPatternDetector(
            self.data, self.config, self._analysis_cache
        )
        self.law_analyzer = WyckoffLawAnalyzer(
            self.data, self.config, self.pattern_detector
        )
        self.mtf_analyzer = MultiTimeframeAnalyzer(self.data, self.pattern_detector)
        self.rs_analyzer = RelativeStrengthAnalyzer(self.data, self.symbol)
        return self.data

    monkeypatch.setattr(WyckoffAnalyzer, "fetch_data", mock_fetch_data)
    analyzer = WyckoffAnalyzer("TEST", "2y")
    data = analyzer.fetch_data()
    assert data is not None
    return analyzer


def _assert_detection_payload(result: dict):
    assert "detected" in result
    if result.get("detected"):
        assert isinstance(result.get("latest") or result.get("latest_spring"), dict)


def test_spring_enhanced(menhongtao_analyzer):
    result = menhongtao_analyzer.pattern_detector.detect_spring_menhongtao()
    _assert_detection_payload(result)
    if result.get("detected"):
        latest = result["latest_spring"]
        assert latest.get("confidence", 0) >= 0
        assert "breakdown_price" in latest


def test_joc_enhanced(menhongtao_analyzer):
    result = menhongtao_analyzer.pattern_detector.detect_joc_menhongtao()
    _assert_detection_payload(result)
    if result.get("detected"):
        latest = result["latest"]
        assert "creek_level" in latest
        assert "close_price" in latest


def test_vsa_signals(menhongtao_analyzer):
    result = menhongtao_analyzer.pattern_detector.detect_vsa_menhongtao()
    assert isinstance(result, dict)
    for key in ("no_supply", "no_demand", "stopping_vol"):
        assert key in result
        assert "detected" in result[key]


def test_integration_pipeline(menhongtao_analyzer):
    spring = menhongtao_analyzer.pattern_detector.detect_spring_menhongtao()
    joc = menhongtao_analyzer.pattern_detector.detect_joc_menhongtao()
    vsa = menhongtao_analyzer.pattern_detector.detect_vsa_menhongtao()

    assert len(menhongtao_analyzer.data) == 200
    assert isinstance(spring, dict)
    assert isinstance(joc, dict)
    assert isinstance(vsa, dict)

    vsa_hits = sum(
        1
        for key in ("no_supply", "no_demand", "stopping_vol")
        if vsa.get(key, {}).get("detected")
    )
    assert isinstance(vsa_hits, int)
