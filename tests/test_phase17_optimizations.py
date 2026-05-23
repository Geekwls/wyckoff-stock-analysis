"""Phase 17：JOC/SOW/FTI 仲裁 + MTF Coordinator EVR 接线"""
import unittest

import pandas as pd

from wyckoff.core.event_arbitrator import ArbitrationSignal, EventArbitrator
from wyckoff.core.multi_timeframe_coordinator import MultiTimeframeCoordinator


def _ohlcv(n: int = 60) -> pd.DataFrame:
    return pd.DataFrame({
        'Open': [100.0] * n,
        'High': [101.0] * n,
        'Low': [99.0] * n,
        'Close': [100.0] * n,
        'Volume': [1_000_000] * n,
    }, index=pd.date_range(end='2024-06-01', periods=n, freq='B'))


class TestJocSowArbitration(unittest.TestCase):
    def test_distribution_context_prefers_sow(self):
        arb = EventArbitrator(_ohlcv())
        joc = ArbitrationSignal(
            signal_type='joc', date='2024-03-01', direction='bullish',
            confidence=0.85, strength=2.0,
        )
        sow = ArbitrationSignal(
            signal_type='sow', date='2024-02-15', direction='bearish',
            confidence=0.7, strength=1.5,
        )
        winner, rejected, reason, phase = arb._arbitrate_joc_sow(
            joc, sow, 14, {'_phase_context': 'Distribution Phase C'}
        )
        self.assertEqual(winner.signal_type, 'sow')
        self.assertIn('派发', reason)
        self.assertIn('Distribution', phase)

    def test_accumulation_context_prefers_joc(self):
        arb = EventArbitrator(_ohlcv())
        joc = ArbitrationSignal(
            signal_type='joc', date='2024-03-01', direction='bullish',
            confidence=0.8, strength=2.0,
        )
        sow = ArbitrationSignal(
            signal_type='sow', date='2024-02-20', direction='bearish',
            confidence=0.75, strength=1.5,
        )
        winner, _, reason, phase = arb._arbitrate_joc_sow(
            joc, sow, 10, {'_phase_context': 'Accumulation Phase C'}
        )
        self.assertEqual(winner.signal_type, 'joc')
        self.assertIn('吸筹', reason)
        self.assertIn('Accumulation', phase)


class TestJocFtiArbitration(unittest.TestCase):
    def test_distribution_prefers_fti(self):
        arb = EventArbitrator(_ohlcv())
        joc = ArbitrationSignal(
            signal_type='joc', date='2024-03-01', direction='bullish',
            confidence=0.8, strength=2.0,
        )
        fti = ArbitrationSignal(
            signal_type='fti', date='2024-03-05', direction='bearish',
            confidence=0.75, strength=1.8,
        )
        winner, _, reason, phase = arb._arbitrate_joc_fti(
            joc, fti, 4, {'_phase_context': 'Distribution Phase D'}
        )
        self.assertEqual(winner.signal_type, 'fti')
        self.assertIn('派发', reason)


class TestMtfCoordinatorEvr(unittest.TestCase):
    def test_weekly_evr_boost_with_spring(self):
        mtf = MultiTimeframeCoordinator()
        daily = _ohlcv(80)
        mtf.set_timeframe_data('daily', daily)

        # 构造周线 EVR：第二根巨量窄幅
        weekly = pd.DataFrame({
            'Open': [100.0, 100.0],
            'High': [101.0, 100.5],
            'Low': [99.0, 99.8],
            'Close': [100.0, 100.2],
            'Volume': [1_000_000, 2_500_000],
        }, index=pd.date_range('2024-05-10', periods=2, freq='W-FRI'))
        mtf.set_timeframe_data('weekly', weekly)

        pattern = {
            'events_detected': {
                'spring': {'detected': True, 'latest_spring': {'lifecycle_status': 'active'}},
                'joc': {'detected': True},
            },
        }
        evr_ctx = mtf._build_evr_context(pattern)
        self.assertTrue(evr_ctx['spring_detected'])
        self.assertTrue(mtf._detect_weekly_evr())
        evr = mtf._evaluate_evr_resonance(evr_ctx, True, {'signal_type': 'spring'})
        self.assertTrue(evr['boost'])
        self.assertIn('Spring', evr['note'])

    def test_spring_without_joc_waits_in_recommendation(self):
        mtf = MultiTimeframeCoordinator()
        pattern = {
            'events_detected': {
                'spring': {'detected': True, 'latest_spring': {'lifecycle_status': 'active'}},
                'joc': {'detected': False},
            },
        }
        rec = mtf._generate_resonance_recommendation(
            'strong',
            {'trend': 'bullish'},
            {'signal_type': 'spring', 'entry_quality': 'excellent'},
            {'entry_quality': 'excellent'},
            direction='long',
            pattern_results=pattern,
        )
        self.assertIn('JOC', rec)
        self.assertIn('等待', rec)
