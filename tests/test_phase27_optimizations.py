"""Phase 27：fallback/方案B、A→B 最短路径、序列评分、Spring 二次测试同步"""
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.enums import WyckoffPhase
from wyckoff.core.phase_coordinator import PhaseCoordinator, PhaseTransitionCriteria
from wyckoff.schemas import EventsModel, TradingRangeModel


class TestFallbackNoPhaseE(unittest.TestCase):
    def test_ma_alignment_returns_unknown_not_phase_e(self):
        n = 250
        close = [100.0 + i * 0.1 for i in range(n)]
        df = pd.DataFrame({
            'Open': close,
            'High': [c + 1 for c in close],
            'Low': [c - 1 for c in close],
            'Close': close,
            'Volume': [1_000_000.0] * n,
            'MA20': [c - 0.5 for c in close],
            'MA50': [c - 1.0 for c in close],
            'MA200': [c - 10.0 for c in close],
        })
        ident = PhaseIdentifier(df, WyckoffConfig(), WyckoffThresholds())
        phase, enum, conf, _ = ident._fallback_logic({})
        self.assertEqual(enum, WyckoffPhase.UNKNOWN)
        self.assertIn('Trending Bullish', phase)
        self.assertLess(conf, 0.55)


class TestPlanBAmbiguousPhase(unittest.TestCase):
    def test_bc_in_bull_trend_is_distribution_a_not_markup_e(self):
        ident = PhaseIdentifier(
            pd.DataFrame({'Close': [110.0], 'MA20': [105.0], 'MA50': [100.0], 'MA200': [90.0]}),
            WyckoffConfig(), WyckoffThresholds(),
        )
        trend = ident._get_market_trend_context()
        phase, enum, _ = ident._handle_bullish_trend_ambiguous_phase('buying_climax', True, True)
        self.assertEqual(enum, WyckoffPhase.PHASE_A)
        self.assertIn('Distribution', phase)
        self.assertNotIn('Markup Phase E', phase)


class TestPhaseAToBNotC(unittest.TestCase):
    def test_phase_a_with_sos_enters_phase_b_not_c(self):
        coord = PhaseCoordinator(MagicMock())
        coord.detector = MagicMock()
        coord._has_complete_phase_a = MagicMock(return_value=True)
        coord._calculate_consolidation_duration = MagicMock(return_value=30)

        events = EventsModel(
            trading_range=TradingRangeModel(
                is_consolidation=True, high=50, low=40, range_pct=0.2,
                duration_days=60, position=0.5, current_price=48,
            ),
        )
        phase, conf = coord._transition_from_phase_a(
            'Accumulation Phase A', events, PhaseTransitionCriteria(),
        )
        self.assertIn('Phase B', phase)
        self.assertNotIn('Phase C', phase)


class TestSequenceScoreExtended(unittest.TestCase):
    def test_full_chain_scores_higher(self):
        ident = PhaseIdentifier(
            pd.DataFrame({'Close': [100.0]}),
            WyckoffConfig(), WyckoffThresholds(),
        )
        minimal = ident.calculate_sequence_score(
            {'climax': {'detected': True}, 'automatic_reaction': {'detected': True}},
            WyckoffPhase.PHASE_A,
        )
        full = ident.calculate_sequence_score(
            {
                'preliminary_support': {'detected': True},
                'climax': {'detected': True},
                'automatic_reaction': {'detected': True},
                'secondary_test': {'detected': True},
                'joc': {'detected': True},
                'lps': {'detected': True, 'latest': {'signal_type': 'lps'}},
            },
            WyckoffPhase.PHASE_D,
        )
        self.assertGreater(full['completeness'], minimal['completeness'])
        self.assertEqual(full['total_events'], 11)


class TestSpringSecondaryTestSync(unittest.TestCase):
    def test_type1_spring_maps_to_phase_b(self):
        phase = PhaseCoordinator._phase_from_spring_signal({
            'spring_type': 1,
            'needs_secondary_test': True,
            'st_confirmed': False,
            'lifecycle_status': 'active',
        })
        self.assertIn('Phase B', phase)

    def test_validate_phase_spring_in_phase_a_type1_stays_phase_b(self):
        coord = PhaseCoordinator(MagicMock())
        coord.detector = MagicMock()

        spring_detail = {
            'spring_type': 1,
            'needs_secondary_test': True,
            'st_confirmed': False,
        }
        events = MagicMock()
        events.spring_upthrust = DualSpringStub()
        events.spring = MagicMock()
        events.spring.latest_spring = spring_detail
        events.spring.signals = []
        events.breakout_analysis = None
        events.trading_range = None
        events.sos_sow = None

        phase, logs = coord.validate_phase_consistency(
            'Accumulation Phase A', events,
        )
        self.assertIn('Phase B', phase)
        self.assertTrue(any('二次测试' in log or 'Phase B' in log for log in logs))


class DualSpringStub:
    type_ = 'spring'
    data = {
        'spring_type': 1,
        'needs_secondary_test': True,
        'st_confirmed': False,
    }


if __name__ == '__main__':
    unittest.main()
