"""批量扫描功能测试"""

import pytest

from wyckoff.services.screener_service import ScreenerService
from wyckoff.wyckoff_analyzer import batch_scan


MOCK_SCAN_RESULTS = [
    {
        "symbol": "AAPL",
        "phase": "Accumulation Phase D",
        "strength": 4,
        "weighted_score": 72,
        "is_entry": True,
    },
    {
        "symbol": "MSFT",
        "phase": "Accumulation Phase C",
        "strength": 3,
        "weighted_score": 58,
        "is_entry": False,
    },
]

BATCH_SCAN_REQUIRED_KEYS = {"results", "summary", "top_picks", "failed", "scan_mode"}
SUMMARY_REQUIRED_KEYS = {
    "total_scanned",
    "signal_count",
    "entry_count",
    "high_score_count",
    "failed_count",
    "phase_distribution",
}


@pytest.fixture
def mock_batch_scan(monkeypatch):
    def _mock_quick_scan(self, symbols, period, **kwargs):
        return [
            dict(result, symbol=symbol)
            for symbol, result in zip(symbols, MOCK_SCAN_RESULTS)
        ]

    monkeypatch.setattr(ScreenerService, "quick_scan", _mock_quick_scan)


def _assert_batch_result_shape(result):
    assert BATCH_SCAN_REQUIRED_KEYS <= set(result.keys())
    assert SUMMARY_REQUIRED_KEYS <= set(result["summary"].keys())
    assert result["scan_mode"] == "quick"
    assert len(result["results"]) == result["summary"]["total_scanned"]


def test_batch_scan_function(mock_batch_scan):
    result = batch_scan(
        ["AAPL", "MSFT"],
        period="1y",
        scan_mode="quick",
        show_progress=False,
        max_workers=2,
    )

    _assert_batch_result_shape(result)
    assert result["summary"]["total_scanned"] == 2
    assert result["summary"]["signal_count"] >= 1
    assert len(result["top_picks"]) <= 10


def test_screener_service_batch_scan(mock_batch_scan):
    screener = ScreenerService()
    result = screener.batch_scan(
        ["AAPL", "MSFT"],
        period="1y",
        scan_mode="quick",
        show_progress=False,
    )

    _assert_batch_result_shape(result)
    symbols = {item["symbol"] for item in result["results"]}
    assert symbols == {"AAPL", "MSFT"}


def test_batch_scan_accumulation_mode_rejected():
    with pytest.raises(ValueError, match="不支持的扫描模式"):
        batch_scan(["AAPL"], period="1y", scan_mode="accumulation", show_progress=False)


@pytest.mark.parametrize(
    ("scan_mode", "should_succeed"),
    [
        ("quick", True),
        ("accumulation", False),
        ("distribution", False),
    ],
)
def test_batch_scan_mode_support(scan_mode, should_succeed, mock_batch_scan):
    if should_succeed:
        result = batch_scan(["AAPL"], period="1y", scan_mode=scan_mode, show_progress=False)
        _assert_batch_result_shape(result)
    else:
        with pytest.raises(ValueError, match="不支持的扫描模式"):
            batch_scan(["AAPL"], period="1y", scan_mode=scan_mode, show_progress=False)


def test_batch_scan_result_structure(mock_batch_scan):
    result = batch_scan(["AAPL"], scan_mode="quick", show_progress=False)
    _assert_batch_result_shape(result)
    assert result["results"][0]["symbol"] == "AAPL"
