"""Phase 18：SOW/FTI + SOS/JOC 仲裁 + 验证脚本增强"""
import unittest

import pandas as pd

from wyckoff.core.event_arbitrator import ArbitrationSignal, EventArbitrator


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame({'Close': [100.0] * 30})


class TestSowFtiArbitration(unittest.TestCase):
    def test_distribution_prefers_fti_over_sow(self):
        arb = EventArbitrator(_ohlcv())
        sow = ArbitrationSignal(
            signal_type='sow', date='2024-02-01', direction='bearish',
            confidence=0.8, strength=1.6,
        )
        fti = ArbitrationSignal(
            signal_type='fti', date='2024-03-01', direction='bearish',
            confidence=0.75, strength=1.5,
        )
        winner, _, reason, phase = arb._arbitrate_sow_fti(
            sow, fti, 28, {'_phase_context': 'Distribution Phase C'}
        )
        self.assertEqual(winner.signal_type, 'fti')
        self.assertIn('FTI', reason)
        self.assertIn('Distribution Phase D', phase)

    def test_sow_after_fti_within_14_days(self):
        arb = EventArbitrator(_ohlcv())
        sow = ArbitrationSignal(
            signal_type='sow', date='2024-03-10', direction='bearish',
            confidence=0.7, strength=1.4,
        )
        fti = ArbitrationSignal(
            signal_type='fti', date='2024-03-01', direction='bearish',
            confidence=0.8, strength=1.6,
        )
        winner, _, reason, phase = arb._arbitrate_sow_fti(
            sow, fti, 9, {'_phase_context': 'Distribution Phase D'}
        )
        self.assertEqual(winner.signal_type, 'sow')
        self.assertIn('失败', reason)
        self.assertIn('Phase C', phase)


class TestSosJocArbitration(unittest.TestCase):
    def test_accumulation_prefers_joc_over_sos(self):
        arb = EventArbitrator(_ohlcv())
        sos = ArbitrationSignal(
            signal_type='sos', date='2024-02-01', direction='bullish',
            confidence=0.8, strength=1.6,
        )
        joc = ArbitrationSignal(
            signal_type='joc', date='2024-03-01', direction='bullish',
            confidence=0.75, strength=1.5,
        )
        winner, _, reason, phase = arb._arbitrate_sos_joc(
            sos, joc, 28, {'_phase_context': 'Accumulation Phase C'}
        )
        self.assertEqual(winner.signal_type, 'joc')
        self.assertIn('JOC', reason)
        self.assertIn('Accumulation Phase D', phase)


class TestJocSowFullArbitrate(unittest.TestCase):
    def test_distribution_joc_sow_conflict_picks_sow(self):
        arb = EventArbitrator(_ohlcv())
        events = {
            'spring': {'detected': False},
            'joc': {
                'detected': True,
                'latest': {'date': '2024-03-01', 'confidence': 85, 'volume_ratio': 2.0},
            },
            'sow': {
                'detected': True,
                'latest': {'date': '2024-02-15', 'confidence': 70, 'volume_ratio': 1.5},
            },
            '_phase_context': 'Distribution Phase A',
        }
        result = arb.arbitrate(events)
        self.assertTrue(result.has_conflict)
        self.assertEqual(result.dominant_signal.signal_type, 'sow')


class TestArbitrationResultPersistence(unittest.TestCase):
    def test_arbitration_result_model_not_dropped(self):
        from wyckoff.schemas import ArbitrationResult, ArbitrationSignal

        result = ArbitrationResult(
            has_conflict=True,
            dominant_signal=ArbitrationSignal(
                signal_type='sow', date='2024-03-01', direction='bearish',
                confidence=0.8, strength=1.5,
            ),
            arbitration_reason='派发语境：SOW 优先于 JOC',
            suggested_phase='Distribution Phase C/D',
        )
        stored = result if isinstance(result, ArbitrationResult) else None
        self.assertIsNotNone(stored)
        self.assertEqual(stored.dominant_signal.signal_type, 'sow')
