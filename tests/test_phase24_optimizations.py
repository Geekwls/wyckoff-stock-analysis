"""Phase 24：审查优化 — 死角/JOC 评分同步、LPS 门控、TR 因果、Spring 收回天数"""
import unittest

import pandas as pd

from wyckoff.core.enums import MarketEnvironment
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.thresholds import spring_max_recovery_days, MAX_RECOVERY_DAYS_STANDARD
from wyckoff.core.utils import PhaseAdapter
from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.schemas import (
    ClimaxModel,
    SpringModel,
    WyckoffEventModel,
)


class TestDeadCornerJocGateScoring(unittest.TestCase):
    def _minimal_data(self):
        return pd.DataFrame({
            'Open': [100.0] * 5,
            'High': [101.0] * 5,
            'Low': [99.0] * 5,
            'Close': [100.0] * 5,
            'Volume': [1000] * 5,
        })

    def test_dead_corner_without_joc_not_boosted_to_85(self):
        engine = RecommendationEngine()
        patterns = {
            'phase': 'Accumulation Phase C',
            'events_detected': {
                'dead_corner_breakout': {
                    'detected': True,
                    'joc_gate': 'pending',
                },
                'joc': {'detected': False},
            },
        }
        quality = engine.calculate_weighted_score(
            self._minimal_data(), patterns, MarketEnvironment.RANGE_BOUND
        )
        self.assertLess(quality.score, 85)
        self.assertTrue(
            any('待 JOC' in r for r in quality.reasons),
            quality.reasons,
        )

    def test_dead_corner_with_joc_can_reach_85(self):
        engine = RecommendationEngine()
        patterns = {
            'phase': 'Accumulation Phase D',
            'events_detected': {
                'dead_corner_breakout': {'detected': True},
                'joc': {
                    'detected': True,
                    'volume_ratio': 2.5,
                    'confidence': 0.9,
                    'creek_level': 105.0,
                },
                'spring': {'detected': True, 'volume_ratio': 1.5, 'confidence': 0.8},
                'sos': {'detected': True, 'volume_ratio': 1.8, 'confidence': 0.8},
            },
        }
        quality = engine.calculate_weighted_score(
            self._minimal_data(), patterns, MarketEnvironment.BULL
        )
        self.assertGreaterEqual(quality.score, 85)


class TestLpsLpsyScoringGate(unittest.TestCase):
    def test_lps_without_joc_not_scored(self):
        engine = RecommendationEngine()
        patterns = {
            'phase': 'Accumulation Phase C',
            'events_detected': {
                'lps': {'detected': True, 'volume_ratio': 0.5, 'confidence': 0.7},
                'joc': {'detected': False},
                'spring': {'detected': True, 'volume_ratio': 1.5, 'confidence': 0.8},
            },
        }
        quality = engine.calculate_weighted_score(
            pd.DataFrame({
                'Open': [100.0] * 5,
                'High': [101.0] * 5,
                'Low': [99.0] * 5,
                'Close': [100.0] * 5,
                'Volume': [1000] * 5,
            }),
            patterns,
            MarketEnvironment.RANGE_BOUND,
        )
        self.assertFalse(any('LPS 成交量' in r or 'LPS 成交量' in r.upper() for r in quality.reasons))


class TestJocLpsEntryZone(unittest.TestCase):
    def test_joc_lps_standard_entry_zone(self):
        engine = RecommendationEngine()
        data = pd.DataFrame({
            'Open': [20.0] * 10,
            'High': [21.0] * 10,
            'Low': [19.0] * 10,
            'Close': [20.5] * 10,
            'Volume': [1000] * 10,
            'ATR': [0.5] * 10,
        })
        plan = engine.generate_trading_plan(
            data,
            {
                'phase': 'Accumulation Phase D',
                'joc': {'detected': True, 'creek_level': 21.0},
                'lps': {'detected': True, 'price': 20.3, 'support_level': 20.2},
            },
            {},
        )
        self.assertEqual(plan.direction, '做多')
        self.assertIn('JOC+LPS', plan.entry_zone)


class TestSpringRecoveryDays(unittest.TestCase):
    def test_low_volatility_matches_classic_standard(self):
        self.assertEqual(spring_max_recovery_days(1.0), MAX_RECOVERY_DAYS_STANDARD)

    def test_high_volatility_allows_five_days(self):
        self.assertEqual(spring_max_recovery_days(4.0), 5)


class TestPhaseAPsHardGate(unittest.TestCase):
    def test_accumulation_requires_ps_sc_ar_st(self):
        events = {
            'climax': {'detected': True, 'type': 'selling_climax'},
            'automatic_reaction': {'detected': True},
            'secondary_test': {'detected': True},
        }
        self.assertFalse(PhaseAdapter.is_phase_a_structure_complete(events))

        events['preliminary_support'] = {'detected': True}
        self.assertTrue(PhaseAdapter.is_phase_a_structure_complete(events))

    def test_distribution_requires_psy_bc_ar_st(self):
        events = {
            'climax': {'detected': True, 'type': 'buying_climax'},
            'automatic_reaction': {'detected': True},
            'secondary_test': {'detected': True},
        }
        self.assertFalse(PhaseAdapter.is_phase_a_structure_complete(events))

        events['preliminary_supply'] = {'detected': True}
        self.assertTrue(PhaseAdapter.is_phase_a_structure_complete(events))

    def test_reaccumulation_ar_st_without_climax(self):
        events = {
            'automatic_reaction': {'detected': True},
            'secondary_test': {'detected': True},
        }
        self.assertTrue(PhaseAdapter.is_phase_a_structure_complete(events))

    def test_spring_phase_c_blocked_without_ps(self):
        from tests.test_phase19_optimizations import _base_events, _make_ohlcv

        ident = PhaseIdentifier(_make_ohlcv(), WyckoffConfig(), WyckoffThresholds())
        events = _base_events(
            climax=ClimaxModel(detected=True, type='selling_climax'),
            automatic_reaction=WyckoffEventModel(detected=True),
            secondary_test=WyckoffEventModel(detected=True),
            spring=SpringModel(detected=True),
        )
        phase, _, _, _ = ident._determine_phase_from_events(events)
        self.assertIn('Spring待Phase A确认', phase)


class TestMtfRsScoreCaps(unittest.TestCase):
    def test_mtf_conflict_caps_score(self):
        engine = RecommendationEngine()
        patterns = {
            'phase': 'Accumulation Phase D',
            'mtf_has_conflict': True,
            'events_detected': {
                'joc': {
                    'detected': True,
                    'volume_ratio': 2.5,
                    'confidence': 0.95,
                    'creek_level': 105.0,
                },
                'spring': {'detected': True, 'volume_ratio': 1.8, 'confidence': 0.9},
                'sos': {'detected': True, 'volume_ratio': 2.0, 'confidence': 0.9},
            },
        }
        quality = engine.calculate_weighted_score(
            pd.DataFrame({
                'Open': [100.0] * 5,
                'High': [101.0] * 5,
                'Low': [99.0] * 5,
                'Close': [100.0] * 5,
                'Volume': [1000] * 5,
            }),
            patterns,
            MarketEnvironment.STRONG_BULL,
        )
        self.assertLessEqual(quality.score, 50)


if __name__ == '__main__':
    unittest.main()
