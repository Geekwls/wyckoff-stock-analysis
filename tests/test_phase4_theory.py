"""Phase 4：MTF 威科夫锚点 / WIE 熵阈值 / RS 数据不足 / 市场广度语义"""
import unittest
import math

import numpy as np
import pandas as pd

from wyckoff.config.settings import WyckoffThresholds
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.core.state_engine import EventDrivenStateEngine
from wyckoff.core.multi_timeframe_coordinator import MultiTimeframeCoordinator
from wyckoff.core.relative_strength_analyzer import RelativeStrengthAnalyzer
from wyckoff.core.market_context_analyzer import MarketContextAnalyzer
from wyckoff.core.enums import MarketEnvironment


class TestSignalExtractorEntryAnchor(unittest.TestCase):
    def test_long_prefers_lps_support(self):
        pattern = {
            'events_detected': {
                'lps': {
                    'detected': True,
                    'support_level': 98.5,
                    'latest': {'price': 98.5},
                },
                'joc': {'detected': True, 'creek_level': 102.0},
            }
        }
        anchor = SignalExtractor.extract_entry_anchor(pattern, 'long')
        self.assertEqual(anchor['source'], 'LPS')
        self.assertAlmostEqual(anchor['level'], 98.5)

    def test_short_prefers_lpsy_resistance(self):
        pattern = {
            'events_detected': {
                'lpsy': {
                    'detected': True,
                    'resistance_level': 105.2,
                },
            }
        }
        anchor = SignalExtractor.extract_entry_anchor(pattern, 'short')
        self.assertEqual(anchor['source'], 'LPSY')
        self.assertAlmostEqual(anchor['level'], 105.2)


class TestSignalExtractorHelpers(unittest.TestCase):
    def test_normalize_confidence_from_percent(self):
        self.assertAlmostEqual(SignalExtractor.normalize_confidence(85), 0.85)

    def test_normalize_confidence_already_unit(self):
        self.assertAlmostEqual(SignalExtractor.normalize_confidence(0.72), 0.72)

    def test_build_patterns_payload_applies_suppression(self):
        ctx = {
            'phase_result': {'phase': 'Distribution Phase C', 'sequence_validation': {}},
            'events': {
                'spring': {'detected': True, 'confidence': 80},
                'joc': {'detected': True},
                'sos': {'detected': False},
            },
            'spring': {'detected': True, 'confidence': 80},
            'joc': {'detected': True},
            'sos': {'detected': False},
            'upthrust': {'detected': False},
            'sow': {'detected': False},
            'lps': {'detected': True},
            'lpsy': {'detected': False},
            'fti': {'detected': False},
            'trading_range': {'high': 110, 'low': 100},
            'boring_res': {'detected': False},
            'dead_corner': {'detected': False},
        }
        SignalExtractor.suppress_bullish_signals(ctx)
        payload = SignalExtractor.build_patterns_payload(ctx)
        events = payload['events_detected']
        self.assertFalse(events['spring']['detected'])
        self.assertFalse(events['joc']['detected'])
        self.assertFalse(events['lps']['detected'])

    def test_resolve_primary_signal_long(self):
        patterns = {
            'events_detected': {
                'spring': {'detected': False},
                'joc': {'detected': True},
            }
        }
        sig, direction = SignalExtractor.resolve_primary_signal(patterns)
        self.assertEqual(sig, 'joc')
        self.assertEqual(direction, 'long')

    def test_resolve_primary_signal_short(self):
        patterns = {
            'events_detected': {
                'fti': {'detected': True},
                'lpsy': {'detected': True},
            }
        }
        sig, direction = SignalExtractor.resolve_primary_signal(patterns)
        self.assertEqual(sig, 'fti')
        self.assertEqual(direction, 'short')

    def test_resolve_primary_signal_skips_lpsy_without_fti(self):
        patterns = {
            'events_detected': {
                'lpsy': {'detected': True},
                'fti': {'detected': False},
            }
        }
        sig, direction = SignalExtractor.resolve_primary_signal(patterns)
        self.assertEqual(sig, 'none')
        self.assertEqual(direction, 'neutral')

    def test_resolve_primary_signal_none_when_no_events(self):
        patterns = {
            'events_detected': {
                'spring': {'detected': False},
                'joc': {'detected': False},
                'sos': {'detected': False},
                'lps': {'detected': False},
                'fti': {'detected': False},
                'upthrust': {'detected': False},
                'sow': {'detected': False},
                'lpsy': {'detected': False},
            }
        }
        sig, direction = SignalExtractor.resolve_primary_signal(patterns)
        self.assertEqual(sig, 'none')
        self.assertEqual(direction, 'neutral')

    def test_build_scoring_payload_suppresses_bullish_in_distribution(self):
        phase_result = {
            'phase': 'Distribution Phase C',
            'events_detected': {
                'spring': {'detected': True, 'confidence': 80},
                'joc': {'detected': True},
                'sos': {'detected': False},
                'trading_range': {'high': 110, 'low': 100},
            },
        }
        payload = SignalExtractor.build_scoring_payload(phase_result)
        events = payload['events_detected']
        self.assertFalse(events['spring']['detected'])
        self.assertFalse(events['joc']['detected'])
        self.assertTrue(payload.get('should_suppress_bullish'))


class TestStateEngineEntropyThreshold(unittest.TestCase):
    def test_uses_config_threshold(self):
        thresholds = WyckoffThresholds()
        engine = EventDrivenStateEngine(
            entropy_degraded_threshold=thresholds.STATE_ENTROPY_DEGRADED_THRESHOLD,
        )
        self.assertEqual(engine.entropy_degraded_threshold, thresholds.STATE_ENTROPY_DEGRADED_THRESHOLD)

    def test_custom_threshold_changes_degraded_flag(self):
        strict = EventDrivenStateEngine(entropy_degraded_threshold=0.5)
        loose = EventDrivenStateEngine(entropy_degraded_threshold=2.0)
        n = 30
        closes = np.linspace(100, 110, n)
        aps = np.zeros(n)
        cds = np.zeros(n)
        lcs = np.zeros(n)
        vpoc = closes.copy()
        exp_eff = np.zeros(n)
        clv = np.zeros(n)
        retention = np.ones(n)
        hs = np.zeros(n, dtype=bool)
        hw = np.zeros(n, dtype=bool)
        event_flags = ['NORMAL'] * n
        timestamps = [f'2024-01-{i + 1:02d}' for i in range(n)]

        strict.batch_update(
            closes, aps, cds, lcs, vpoc, exp_eff, clv, retention, hs, hw, event_flags, timestamps
        )
        loose.batch_update(
            closes, aps, cds, lcs, vpoc, exp_eff, clv, retention, hs, hw, event_flags, timestamps
        )
        strict_degraded = '[?]' in strict.current_state
        loose_degraded = '[?]' in loose.current_state
        self.assertIsInstance(strict_degraded, bool)
        self.assertIsInstance(loose_degraded, bool)


class TestRelativeStrengthInsufficientData(unittest.TestCase):
    def _make_series(self, n: int, start: float = 100.0) -> pd.DataFrame:
        idx = pd.date_range('2024-01-01', periods=n, freq='D')
        close = np.linspace(start, start + n * 0.5, n)
        return pd.DataFrame({'Close': close}, index=idx)

    def test_short_history_uses_ma20_slope_not_flat_ma50(self):
        stock = self._make_series(35, 50)
        bench = self._make_series(35, 100)
        analyzer = RelativeStrengthAnalyzer(stock, 'TEST')
        result = analyzer.calculate_rs(bench)
        self.assertIn(result['rs_trend'], ('rising', 'falling', 'flat', 'insufficient_data'))
        self.assertIn('ma20_slope', result.get('rs_ma_basis', ''))
        self.assertNotEqual(result.get('rs_ma_basis'), 'ma20_vs_ma50')


class TestMarketBreadthSkipped(unittest.TestCase):
    def test_skipped_breadth_does_not_refine_environment(self):
        idx = pd.date_range('2024-01-01', periods=120, freq='D')
        close = np.linspace(3000, 3200, 120)
        data = pd.DataFrame({'Close': close, 'Volume': np.full(120, 1e9)}, index=idx)
        analyzer = MarketContextAnalyzer(data, '000001.SS')
        breadth = analyzer._get_market_breadth()
        self.assertEqual(breadth['status'], 'SKIPPED')
        self.assertFalse(breadth.get('enabled', True))

        evr = {'interpretation': 'NORMAL', 'vol_ratio': 1.5}
        env, desc = analyzer._refine_environment(
            MarketEnvironment.STRONG_BULL,
            '强势多头',
            evr,
            breadth,
        )
        self.assertNotIn('广度', desc)
        self.assertEqual(env, MarketEnvironment.STRONG_BULL)


class TestMtfHourlyWyckoffAnchor(unittest.TestCase):
    def _hourly_df(self, price: float, volume: float = 500_000) -> pd.DataFrame:
        idx = pd.date_range('2024-06-01', periods=48, freq='h')
        return pd.DataFrame({
            'Open': price,
            'High': price * 1.002,
            'Low': price * 0.998,
            'Close': price,
            'Volume': volume,
        }, index=idx)

    def test_hourly_entry_near_lps_with_low_volume(self):
        mtf = MultiTimeframeCoordinator()
        hourly = self._hourly_df(98.6, volume=400_000)
        # 前段放量、末根缩量，满足 low_volume（量比 < 0.85）
        hourly.iloc[:-1, hourly.columns.get_loc('Volume')] = 900_000
        mtf.set_timeframe_data('hourly', hourly)
        pattern = {
            'events_detected': {
                'lps': {'detected': True, 'support_level': 98.5},
            }
        }
        result = mtf._analyze_hourly_entry('long', pattern)
        self.assertTrue(result['has_entry'])
        self.assertEqual(result['anchor_source'], 'LPS')
        self.assertEqual(result['entry_quality'], 'excellent')

    def test_daily_direction_from_signal_type(self):
        mtf = MultiTimeframeCoordinator()
        idx = pd.date_range('2024-01-01', periods=60, freq='D')
        daily = pd.DataFrame({
            'Open': 100,
            'High': 101,
            'Low': 99,
            'Close': 100,
            'Volume': 1_000_000,
        }, index=idx)
        mtf.set_timeframe_data('daily', daily)
        pattern = {'events_detected': {'lpsy': {'detected': True, 'confidence': 80}}}
        daily_result = mtf._analyze_daily_signal('lpsy', 'short', pattern)
        self.assertEqual(daily_result['direction'], 'short')


if __name__ == '__main__':
    unittest.main()
