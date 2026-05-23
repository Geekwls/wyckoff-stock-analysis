"""Phase 20：P2 威科夫语义优化"""
import unittest

import pandas as pd

from wyckoff.core.event_arbitrator import ArbitrationSignal, EventArbitrator
from wyckoff.core.phase_coordinator import PhaseCoordinator
from wyckoff.core.detectors.meng_trend_detector import MengTrendDetector
from wyckoff.core.laws.cause_effect import CauseEffectMixin
from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame({'Close': [100.0] * 30})


class TestLpsArbitration(unittest.TestCase):
    def test_joc_context_prefers_lps_over_spring(self):
        arb = EventArbitrator(_ohlcv())
        events = {
            'spring': {'detected': True, 'latest_spring': {'date': '2024-01-01', 'confidence': 80, 'volume_ratio': 1.5}},
            'lps': {'detected': True, 'latest': {'date': '2024-02-01', 'confidence': 75, 'volume_ratio': 0.8}},
            'joc': {'detected': True, 'latest': {'date': '2024-01-15', 'confidence': 85, 'volume_ratio': 2.0}},
            '_phase_context': 'Accumulation Phase D',
            '_climax_type': 'selling_climax',
        }
        result = arb.arbitrate(events)
        self.assertTrue(result.has_conflict)
        self.assertEqual(result.dominant_signal.signal_type, 'lps')
        self.assertIn('LPS', result.arbitration_reason)

    def test_no_joc_prefers_spring_over_lps(self):
        arb = EventArbitrator(_ohlcv())
        events = {
            'spring': {'detected': True, 'latest_spring': {'date': '2024-01-01', 'confidence': 80, 'volume_ratio': 1.5}},
            'lps': {'detected': True, 'latest': {'date': '2024-02-01', 'confidence': 75, 'volume_ratio': 0.8}},
            'joc': {'detected': False},
            '_phase_context': 'Accumulation Phase C',
        }
        result = arb.arbitrate(events)
        self.assertTrue(result.has_conflict)
        self.assertEqual(result.dominant_signal.signal_type, 'spring')


class TestDeadCornerJocGate(unittest.TestCase):
    def test_coordinator_gate_downgrades_without_joc(self):
        dead = {
            'detected': True,
            'trading_advice': {'action': 'STRONG_BUY', 'entry': '激进追涨'},
        }
        out = PhaseCoordinator._apply_dead_corner_joc_gate(dead, {'detected': False})
        self.assertEqual(out['trading_advice']['action'], 'WATCH')
        self.assertEqual(out.get('joc_gate'), 'pending')

    def test_meng_trend_advice_waits_without_joc(self):
        det = MengTrendDetector(_ohlcv(), WyckoffConfig(), WyckoffThresholds())
        advice = det._generate_breakout_trading_advice(
            {'breakout_price': 100.0}, 'SUPER_STRONG', joc_confirmed=False
        )
        self.assertEqual(advice['action'], 'WATCH')


class TestCauseEffectFtiSymmetry(unittest.TestCase):
    def test_fti_quality_used_for_downside(self):
        idx = pd.date_range('2024-01-01', periods=60, freq='D')
        df = pd.DataFrame({
            'Open': [100.0] * 60,
            'High': [101.0] * 60,
            'Low': [99.0] * 60,
            'Close': [100.0] * 60,
            'Volume': [1000.0] * 60,
        }, index=idx)

        class _Det:
            def identify_phase(self):
                return {
                    'events_detected': {
                        'fti': {'detected': True, 'date': idx[-1]},
                        'joc': {'detected': False},
                    }
                }

        class _TestCause(CauseEffectMixin):
            def __init__(self, df, detector):
                self.data = df
                self.pattern_detector = detector

        analyzer = _TestCause(df, _Det())
        analyzer._get_weis_wave_breakout_quality = lambda _d: {'quality_score': 0.12}
        res = analyzer._calculate_breakout_probability_enhanced(
            'Distribution Phase D', 'down'
        )
        self.assertGreaterEqual(res['probability'], 0.87)


class TestSpringStructuralSupport(unittest.TestCase):
    def test_structural_support_not_raised_by_rolling(self):
        from wyckoff.core.detectors.meng_reversal_detector import MengReversalDetector

        idx = pd.date_range('2024-01-01', periods=30, freq='D')
        lows = [95.0] * 10 + [88.0] * 10 + [92.0] * 10
        df = pd.DataFrame({'Low': lows, 'High': [101.0] * 30}, index=idx)
        det = MengReversalDetector(df, WyckoffConfig(), WyckoffThresholds())
        det.set_structural_levels(support=90.0)
        series = det._build_support_level_series(df)
        self.assertTrue((series == 90.0).all())
