"""Phase 16：Phase A ST 门槛 / MTF 空头共振 / 报告旁路 / Upthrust 门控"""
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.enums import WyckoffPhase
from wyckoff.core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.schemas import ClimaxModel, WyckoffEventModel


class TestPhaseARequiresST(unittest.TestCase):
    def test_sc_ar_without_st_is_pending_label(self):
        ident = PhaseIdentifier(
            pd.DataFrame({'Close': [100.0], 'MA200': [90.0]}),
            WyckoffConfig(), WyckoffThresholds(),
        )

        class MockEvents:
            spring_upthrust = None
            sos_sow = None
            joc = None
            fti = None
            climax = ClimaxModel(detected=True, type='selling_climax')
            automatic_reaction = WyckoffEventModel(detected=True)
            secondary_test = WyckoffEventModel(detected=False)
            trading_range = None
            lps_list = []
            ut_list = []
            vsa_signals = {}

        phase, enum, conf, _ = ident._determine_phase_from_events(MockEvents())
        self.assertIn('待ST确认', phase)
        self.assertEqual(enum, WyckoffPhase.PHASE_A)
        self.assertLess(conf, 0.70)


class TestMtfBearishResonance(unittest.TestCase):
    def test_analyze_resonance_includes_bearish_strength(self):
        n = 80
        df = pd.DataFrame({
            'Open': [100.0] * n,
            'High': [101.0] * n,
            'Low': [99.0] * n,
            'Close': [100.0] * n,
            'Volume': [1_000_000] * n,
        }, index=pd.date_range(end='2024-06-01', periods=n, freq='B'))

        analyzer = MultiTimeframeAnalyzer.__new__(MultiTimeframeAnalyzer)
        analyzer.data = df
        analyzer.pattern_detector = MagicMock()

        phase_result = {
            'phase': 'Distribution Phase C',
            'events_detected': {
                'upthrust': {'detected': True, 'latest_upthrust': {'lifecycle_status': 'active'}},
                'sow': {'detected': True},
                'fti': {'detected': False},
                'spring': {'detected': False},
                'sos': {'detected': False},
                'joc': {'detected': False},
            },
        }
        result = analyzer.analyze_resonance(phase_result=phase_result)
        self.assertGreater(result.get('bearish_resonance_strength', 0), 0)
        self.assertIn('daily_upthrust', result.get('resonance_signals', []))


class TestUpthrustWithoutFtiWaits(unittest.TestCase):
    def test_isolated_upthrust_waits(self):
        engine = RecommendationEngine(WyckoffConfig())
        n = 30
        data = pd.DataFrame({
            'Open': [100.0] * n,
            'High': [101.0] * n,
            'Low': [99.0] * n,
            'Close': [100.0] * n,
            'Volume': [1_000_000] * n,
            'ATR': [1.0] * n,
        })
        patterns = {
            'phase': 'Distribution Phase C',
            'events_detected': {
                'upthrust': {
                    'detected': True,
                    'latest_upthrust': {
                        'breakout_price': 102.0,
                        'lifecycle_status': 'active',
                        'price': 100.0,
                    },
                },
                'sow': {'detected': False},
                'fti': {'detected': False},
            },
        }
        plan = engine.generate_trading_plan(data, patterns, {})
        self.assertEqual(plan.direction, '观望')


class TestResolvePrimaryUpthrustGate(unittest.TestCase):
    def test_upthrust_without_fti_or_sow_is_neutral(self):
        events = {
            'upthrust': {'detected': True, 'latest_upthrust': {'lifecycle_status': 'active'}},
            'fti': {'detected': False},
            'sow': {'detected': False},
        }
        key, direction = SignalExtractor.resolve_primary_signal(events)
        self.assertEqual(key, 'none')
        self.assertEqual(direction, 'neutral')


if __name__ == '__main__':
    unittest.main()
