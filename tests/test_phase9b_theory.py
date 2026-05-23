"""Phase 9b–9d：B4–B15 语义回归测试"""
import unittest
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.base_detector import BaseDetector
from wyckoff.core.detectors.meng_reversal_detector import MengReversalDetector
from wyckoff.core.event_arbitrator import EventArbitrator
from wyckoff.core.phase_coordinator import PhaseCoordinator
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.schemas import SpringModel, SosModel


class _StubDetector(BaseDetector):
    pass


class TestStructuralLevels(unittest.TestCase):
    def test_set_structural_support_from_sc(self):
        det = _StubDetector()
        det.set_phase_a_events({
            'climax': {'detected': True, 'type': 'selling_climax', 'price': 38.0},
        })
        self.assertEqual(det._resolve_structural_support(), 38.0)


class TestSpringStructuralSeries(unittest.TestCase):
    def test_support_series_uses_structural_floor(self):
        n = 30
        idx = pd.date_range('2024-01-01', periods=n, freq='D')
        lows = np.linspace(35, 42, n)
        df = pd.DataFrame({
            'Open': lows + 0.5,
            'High': lows + 1.0,
            'Low': lows,
            'Close': lows + 0.3,
            'Volume': np.full(n, 1_000_000),
        }, index=idx)
        det = MengReversalDetector(df, WyckoffConfig(), WyckoffThresholds())
        det.set_structural_levels(support=40.0)
        series = det._build_support_level_series(df)
        self.assertTrue(np.nanmax(series) >= 40.0)


class TestPreliminaryPhaseTightening(unittest.TestCase):
    def test_ps_only_not_formal_phase_a(self):
        coord = PhaseCoordinator(MagicMock())
        phase = coord._preliminary_phase_identification(
            climax_res={'detected': False},
            ar_res={'detected': False},
            st_res={'detected': False},
            spring_res={'detected': False},
            upthrust_res={'detected': False},
            ps_res={'detected': True},
            psy_res={'detected': False},
        )
        self.assertIn('PS待SC确认', phase)
        self.assertNotEqual(phase, 'Accumulation Phase A')


class TestEventArbitratorExtended(unittest.TestCase):
    def _df(self):
        return pd.DataFrame({'Close': [100.0]})

    def test_spring_deduped_when_latest_in_signals(self):
        arb = EventArbitrator(self._df())
        sig = {
            'date': '2024-06-01',
            'breakdown_date': '2024-05-28',
            'breakdown_price': 38.0,
            'support_level': 40.0,
            'recovery_price': 41.0,
            'recovery_days': 2,
            'volume_ratio': 1.5,
            'confidence': 80,
        }
        spring = SpringModel(
            detected=True,
            signals=[sig],
            latest_spring=sig,
        )
        out = arb._extract_spring_signals(spring)
        self.assertEqual(len(out), 1)

    def test_upthrust_joc_fti_extracted(self):
        arb = EventArbitrator(self._df())
        events = {
            'spring': {'detected': False},
            'upthrust': {
                'detected': True,
                'signals': [{'date': '2024-06-02', 'confidence': 70, 'vol_ratio': 1.3}],
            },
            'joc': {
                'detected': True,
                'latest': {'date': '2024-06-03', 'confidence': 75, 'volume_ratio': 1.6},
            },
            'fti': {
                'detected': True,
                'latest': {'date': '2024-06-04', 'confidence': 72, 'volume_ratio': 1.4},
            },
        }
        signals = arb._extract_all_signals(events)
        types = {s.signal_type for s in signals}
        self.assertIn('upthrust', types)
        self.assertIn('joc', types)
        self.assertIn('fti', types)


class TestSosAloneWatch(unittest.TestCase):
    def test_isolated_sos_yields_watch(self):
        data = pd.DataFrame({
            'Open': [50.0] * 40,
            'High': [51.0] * 40,
            'Low': [49.0] * 40,
            'Close': [50.5] * 40,
            'Volume': [1_000_000] * 40,
        })
        events = {
            'sos': {'detected': True, 'price': 52.0, 'date': '2024-06-01'},
            'spring': {'detected': False},
            'joc': {'detected': False},
            'upthrust': {'detected': False},
            'fti': {'detected': False},
            'sow': {'detected': False},
            'utad': {'detected': False},
            'trading_range': {'detected': False},
        }
        engine = RecommendationEngine(WyckoffConfig())
        plan = engine.generate_trading_plan(data, events, targets={})
        self.assertEqual(plan.direction, '观望')
        self.assertIn('SOS', plan.entry_zone)


class TestPhaseDToEConfirmation(unittest.TestCase):
    def test_accumulation_requires_up_days(self):
        coord = PhaseCoordinator(MagicMock())
        idx = pd.date_range('2024-01-01', periods=5, freq='D')
        coord.detector = MagicMock()
        coord.detector.data = pd.DataFrame({
            'Close': [100, 101, 102, 103, 104],
        }, index=idx)
        self.assertTrue(
            coord._has_continuous_confirmation(3, 'Accumulation Phase D', None)
        )

    def test_distribution_requires_down_days(self):
        coord = PhaseCoordinator(MagicMock())
        idx = pd.date_range('2024-01-01', periods=5, freq='D')
        coord.detector = MagicMock()
        coord.detector.data = pd.DataFrame({
            'Close': [100, 99, 98, 97, 96],
        }, index=idx)
        self.assertTrue(
            coord._has_continuous_confirmation(3, 'Distribution Phase D', None)
        )


if __name__ == '__main__':
    unittest.main()
