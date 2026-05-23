"""Phase 7：语义级测试 — SOS 1.5x / LPS Creek 锚定 / 报告一致性 / 三大定律同源"""
import os
import unittest

import numpy as np
import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.strength_weakness_detector import StrengthWeaknessDetector
from wyckoff.core.law_analyzer import WyckoffLawAnalyzer
from wyckoff.core.signal_extractor import SignalExtractor, set_cached_phase_result


def _make_sos_df(*, vol_ratio: float = 1.55, n: int = 80) -> pd.DataFrame:
    """构造末根 K 线满足 SOS 条件（1.5x 放量、>2% 涨幅、收盘高位）的合成数据。"""
    dates = pd.date_range('2024-01-01', periods=n, freq='D')
    base_vol = 1_000_000.0

    df = pd.DataFrame({
        'Open': [100.0] * n,
        'High': [101.0] * n,
        'Low': [99.0] * n,
        'Close': [100.0] * n,
        'Volume': [base_vol] * n,
    }, index=dates)

    prev = n - 2
    last = n - 1
    df.iloc[prev, df.columns.get_loc('Close')] = 100.0
    df.iloc[last, df.columns.get_loc('Open')] = 100.0
    df.iloc[last, df.columns.get_loc('Close')] = 103.5
    df.iloc[last, df.columns.get_loc('High')] = 103.8
    df.iloc[last, df.columns.get_loc('Low')] = 100.2
    df.iloc[last, df.columns.get_loc('Volume')] = base_vol * vol_ratio

    df['Volume_MA20'] = df['Volume'].rolling(20, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['ATR'] = (df['High'] - df['Low']).rolling(14, min_periods=1).mean()
    return df


def _make_lps_df() -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    """SOS/JOC 后缩量回测 Creek 的合成序列。"""
    n = 80
    dates = pd.date_range('2024-01-01', periods=n, freq='D')
    base = 1_000_000.0
    creek = 100.0

    opens, highs, lows, closes, vols = [], [], [], [], []
    for i in range(n):
        if i < 50:
            c = 99.0 + (i % 4) * 0.25
            o, h, l, v = c - 0.2, c + 0.3, c - 0.4, base
        elif i == 60:
            o, h, l, c, v = 101.0, 104.5, 100.5, 104.0, base * 1.6
        elif i == 65:
            o, h, l, c, v = 103.0, 104.0, 101.5, 103.5, base * 0.9
        elif i >= 75 and i < n - 1:
            c = 104.0 - (i - 75) * 0.15
            o, h, l, v = c - 0.2, c + 0.3, c - 0.4, base * 0.95
        elif i == n - 1:
            o, h, l, c, v = 103.0, 104.5, creek + 0.05, 104.2, base * 0.5
        elif i > 60:
            c = 102.5 + (i - 60) * 0.15
            o, h, l, v = c - 0.2, c + 0.4, c - 0.5, base * 0.95
        else:
            o, h, l, c, v = 99.0, 99.5, 98.5, 99.0, base
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(v)

    df = pd.DataFrame(
        {'Open': opens, 'High': highs, 'Low': lows, 'Close': closes, 'Volume': vols},
        index=dates,
    )
    df['Volume_MA20'] = df['Volume'].rolling(20, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['ATR'] = (df['High'] - df['Low']).rolling(14, min_periods=1).mean()
    return df, dates[60], dates[65]


def _make_law_df(n: int = 80) -> pd.DataFrame:
    dates = pd.date_range('2024-01-01', periods=n, freq='D')
    closes = np.linspace(95, 105, n)
    df = pd.DataFrame({
        'Open': closes - 0.3,
        'High': closes + 0.5,
        'Low': closes - 0.5,
        'Close': closes,
        'Volume': [1_200_000.0] * n,
    }, index=dates)
    df['Volume_MA20'] = df['Volume'].rolling(20, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['MA200'] = df['Close'].rolling(200, min_periods=1).mean()
    df['ATR'] = (df['High'] - df['Low']).rolling(14, min_periods=1).mean()
    return df


class _MockPatternDetector:
    """仅缓存 phase 结果，用于验证定律层不重复 detect_spring。"""

    def __init__(self, phase_result: dict):
        self._cached_phase_result = phase_result
        self.spring_detect_called = False

    def detect_spring(self):
        self.spring_detect_called = True
        return {'detected': False}

    def detect_trading_range(self):
        tr = self._cached_phase_result.get('events_detected', {}).get('trading_range', {})
        return tr or {'is_consolidation': True, 'high': 110.0, 'low': 90.0}

    def identify_phase(self):
        return self._cached_phase_result


class TestSosVolumeThreshold(unittest.TestCase):
    def setUp(self):
        self.config = WyckoffConfig()
        self.thresholds = WyckoffThresholds()

    def test_sos_detected_at_moderate_volume(self):
        df = _make_sos_df(vol_ratio=1.55)
        det = StrengthWeaknessDetector(df, self.config, self.thresholds)
        det.update_analysis_context('Accumulation Phase C')

        if os.environ.get('WYCKOFF_VECTORIZED', '1') == '1':
            result = det._detect_sos_vectorized(window=40)
        else:
            result = det._detect_sos_iterative(window=40)

        self.assertTrue(result.get('detected'), result)
        self.assertGreaterEqual(result.get('volume_ratio', 0), 1.5)

    def test_sos_not_detected_below_moderate_volume(self):
        df = _make_sos_df(vol_ratio=1.49)
        det = StrengthWeaknessDetector(df, self.config, self.thresholds)
        det.update_analysis_context('Accumulation Phase C')

        if os.environ.get('WYCKOFF_VECTORIZED', '1') == '1':
            result = det._detect_sos_vectorized(window=40)
        else:
            result = det._detect_sos_iterative(window=40)

        self.assertFalse(result.get('detected'))


class TestLpsCreekAnchor(unittest.TestCase):
    def setUp(self):
        self.config = WyckoffConfig()
        self.thresholds = WyckoffThresholds()

    def test_lps_after_breakout_anchors_to_joc_creek(self):
        df, sos_date, joc_date = _make_lps_df()
        creek = 100.0
        det = StrengthWeaknessDetector(df, self.config, self.thresholds)
        det.update_analysis_context('Accumulation Phase C')
        det.set_phase_a_events({
            'climax': {'detected': True, 'type': 'selling_climax'},
            'ar': {'detected': True},
            'st': {'detected': True},
        })

        sos_result = {
            'detected': True,
            'date': sos_date,
            'latest': {'date': sos_date, 'breakthrough_level': {'value': 104.0}},
        }
        joc_result = {
            'detected': True,
            'date': joc_date,
            'creek_level': creek,
            'latest': {'date': joc_date, 'creek_level': creek},
        }
        tr = {'high': 104.0, 'low': 98.0}

        result = det.detect_lps(
            window=40,
            spring_res={'detected': False},
            trading_range=tr,
            sos_result=sos_result,
            joc_result=joc_result,
        )

        self.assertTrue(result.get('detected'), result)
        latest = result.get('latest') or {}
        self.assertEqual(latest.get('signal_type'), 'lps')
        self.assertEqual(latest.get('anchor_type'), 'JOC Creek')
        self.assertAlmostEqual(latest.get('lps_anchor', latest.get('support_level')), creek, places=1)


class TestReportEventsConsistency(unittest.TestCase):
    def test_build_report_context_matches_events_detected(self):
        events_detected = {
            'spring': {'detected': True, 'confidence': 85, 'total_score': 82},
            'sos': {
                'detected': True,
                'volume_ratio': 1.75,
                'latest': {'volume_ratio': 1.75, 'price': 110.0, 'date': '2024-06-01'},
            },
            'joc': {'detected': True, 'creek_level': 100.0, 'test_detected': True},
            'trading_range': {'is_consolidation': True, 'high': 110.0, 'low': 90.0},
        }
        phase_result = {'phase': 'Accumulation Phase D', 'events_detected': events_detected}
        ctx = SignalExtractor.build_report_context(phase_result)

        self.assertTrue(ctx['spring']['detected'])
        self.assertEqual(ctx['sos']['volume_ratio'], 1.75)
        self.assertEqual(ctx['sos']['price'], 110.0)
        self.assertEqual(ctx['joc']['creek_level'], 100.0)

        payload = SignalExtractor.build_patterns_payload(ctx)
        for key in ('spring', 'sos', 'joc', 'trading_range'):
            self.assertEqual(payload['events_detected'][key], ctx[key])


class TestLawsUseCachedEvents(unittest.TestCase):
    def test_supply_demand_and_effort_result_read_same_spring(self):
        phase_result = {
            'phase': 'Accumulation Phase C',
            'phase_enum': 'Accumulation Phase C',
            'events_detected': {
                'trading_range': {'is_consolidation': True, 'high': 110.0, 'low': 90.0},
                'spring': {'detected': True, 'confidence': 0.85, 'total_score': 82},
                'sos': {'detected': False},
                'sow': {'detected': False},
                'upthrust': {'detected': False},
            },
        }
        mock_detector = _MockPatternDetector(phase_result)
        set_cached_phase_result(mock_detector, phase_result)

        df = _make_law_df()
        analyzer = WyckoffLawAnalyzer(df, WyckoffConfig(), mock_detector)

        sd = analyzer.analyze_supply_demand_law()
        spring_status = sd['accumulation_analysis']['details']['spring_status']
        self.assertEqual(spring_status, 'detected')
        self.assertFalse(mock_detector.spring_detect_called)

        follow = analyzer._analyze_signal_follow_through()
        self.assertTrue(follow['spring_follow_through']['tracked'])


if __name__ == '__main__':
    unittest.main()
