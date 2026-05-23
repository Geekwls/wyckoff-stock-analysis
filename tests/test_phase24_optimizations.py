"""Phase 24：审查优化 — 死角/JOC 评分同步、LPS 门控、TR 因果、Spring 收回天数"""
import unittest

import pandas as pd

from wyckoff.core.enums import MarketEnvironment
from wyckoff.core.orchestrator import WyckoffOrchestrator
from wyckoff.core.wie3_market_state_service import WIE3AnalysisResult, WIE3MarketStateService
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.searchlight_arbitrator import build_searchlight_arbitration
from wyckoff.core.searchlight_enrichment import enrich_patterns_with_searchlight
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
    def _strong_bullish_patterns(self):
        return {
            'phase': 'Accumulation Phase D',
            'events_detected': {
                'joc': {
                    'detected': True,
                    'volume_ratio': 2.5,
                    'confidence': 0.95,
                    'creek_level': 105.0,
                },
                'spring': {'detected': True, 'volume_ratio': 1.8, 'confidence': 0.9},
                'sos': {'detected': True, 'volume_ratio': 2.0, 'confidence': 0.9},
                'lps': {'detected': True, 'volume_ratio': 0.7, 'confidence': 0.85},
            },
        }

    def _minimal_data(self):
        return pd.DataFrame({
            'Open': [100.0] * 5,
            'High': [101.0] * 5,
            'Low': [99.0] * 5,
            'Close': [100.0] * 5,
            'Volume': [1000] * 5,
        })

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

    def test_searchlight_bearish_contradiction_caps_accumulation_score(self):
        engine = RecommendationEngine()
        patterns = self._strong_bullish_patterns()
        patterns['searchlight_arbitration'] = {
            'available': True,
            'has_contradiction': True,
            'bias': 'bearish_microstructure',
            'bearish_probability': 0.72,
            'bullish_probability': 0.18,
            'aps': 2.0,
            'entropy_degraded': False,
        }

        quality = engine.calculate_weighted_score(
            self._minimal_data(),
            patterns,
            MarketEnvironment.STRONG_BULL,
        )

        self.assertLessEqual(quality.score, 45)
        self.assertTrue(any('Searchlight/WIE3' in r for r in quality.reasons), quality.reasons)

    def test_searchlight_high_entropy_caps_score(self):
        engine = RecommendationEngine()
        patterns = self._strong_bullish_patterns()
        patterns['searchlight_arbitration'] = {
            'available': True,
            'has_contradiction': False,
            'bias': 'neutral',
            'bearish_probability': 0.35,
            'bullish_probability': 0.40,
            'aps': 4.0,
            'entropy_degraded': True,
        }

        quality = engine.calculate_weighted_score(
            self._minimal_data(),
            patterns,
            MarketEnvironment.STRONG_BULL,
        )

        self.assertLessEqual(quality.score, 65)
        self.assertTrue(any('高熵' in r for r in quality.reasons), quality.reasons)

    def test_searchlight_contradiction_blocks_trading_plan(self):
        engine = RecommendationEngine()
        patterns = self._strong_bullish_patterns()
        patterns['searchlight_arbitration'] = {
            'available': True,
            'has_contradiction': True,
            'bias': 'bearish_microstructure',
            'bearish_probability': 0.72,
            'bullish_probability': 0.18,
            'aps': 2.0,
            'entropy_degraded': False,
        }

        plan = engine.generate_trading_plan(self._minimal_data(), patterns, {})

        self.assertEqual(plan.direction, "观望")
        self.assertEqual(plan.position_sizing.conservative, "0%")
        self.assertIn('Searchlight/WIE3', plan.entry_zone)

    def test_searchlight_entropy_degrades_position_sizing(self):
        engine = RecommendationEngine()
        patterns = self._strong_bullish_patterns()
        patterns['searchlight_arbitration'] = {
            'available': True,
            'has_contradiction': False,
            'bias': 'neutral',
            'bearish_probability': 0.35,
            'bullish_probability': 0.40,
            'aps': 4.0,
            'entropy_degraded': True,
        }

        plan = engine.generate_trading_plan(self._minimal_data(), patterns, {})

        self.assertEqual(plan.direction, "做多")
        self.assertIn('WIE3高熵降级', plan.position_sizing.conservative)


class TestSearchlightArbitrator(unittest.TestCase):
    def test_custom_thresholds_gate_contradiction(self):
        strict = WyckoffThresholds(SEARCHLIGHT_BEARISH_PROB_THRESHOLD=0.90)
        result = build_searchlight_arbitration(
            'Accumulation Phase D',
            {
                'state_probs': {'S0: Panic Liquidation (恐慌出清)': 0.62},
                'aps': 2.0,
                'hidden_weakness': False,
            },
            strict,
        )
        self.assertFalse(result['has_contradiction'])

    def test_bearish_microstructure_contradicts_accumulation(self):
        result = build_searchlight_arbitration(
            'Accumulation Phase D',
            {
                'state_probs': {
                    'S0: Panic Liquidation (恐慌出清)': 0.62,
                    'S1: Absorption (主力高密持续吸收)': 0.15,
                },
                'aps': 2.0,
                'is_confidence_degraded': False,
                'hidden_weakness': False,
                'hidden_strength': False,
                'regime': 'S0: Panic Liquidation (恐慌出清)',
            },
        )

        self.assertTrue(result['available'])
        self.assertTrue(result['has_contradiction'])
        self.assertEqual(result['bias'], 'bearish_microstructure')

    def test_shared_enrichment_matches_orchestrator_searchlight(self):
        class _MockMarketState:
            def to_dict(self):
                return {
                    'state_probs': {
                        'S0: Panic Liquidation (恐慌出清)': 0.62,
                        'S1: Absorption (主力高密持续吸收)': 0.15,
                    },
                    'aps': 2.0,
                    'is_confidence_degraded': False,
                    'hidden_weakness': False,
                    'hidden_strength': False,
                    'regime': 'S0: Panic Liquidation (恐慌出清)',
                }

        wie3 = WIE3MarketStateService()
        wie3.analyze = lambda _data, index_df=None, resolve_index_df=None: WIE3AnalysisResult(
            market_state=_MockMarketState(),
            df_vsa=pd.DataFrame(),
        )
        patterns = {
            'phase': 'Accumulation Phase D',
            'events_detected': {},
        }
        enriched = enrich_patterns_with_searchlight(
            patterns,
            pd.DataFrame({
                'Open': [100.0] * 5,
                'High': [101.0] * 5,
                'Low': [99.0] * 5,
                'Close': [100.0] * 5,
                'Volume': [1000] * 5,
            }),
            wie3,
        )
        self.assertTrue(enriched['searchlight_arbitration']['has_contradiction'])
        self.assertIn('microstructure_background', enriched)

    def test_orchestrator_enriches_patterns_with_searchlight(self):
        class _MockMarketState:
            def to_dict(self):
                return {
                    'state_probs': {
                        'S0: Panic Liquidation (恐慌出清)': 0.62,
                        'S1: Absorption (主力高密持续吸收)': 0.15,
                    },
                    'aps': 2.0,
                    'is_confidence_degraded': False,
                    'hidden_weakness': False,
                    'hidden_strength': False,
                    'regime': 'S0: Panic Liquidation (恐慌出清)',
                }

        orch = WyckoffOrchestrator()
        orch._fetch_benchmark_data = lambda _symbol, _period: None
        orch._wie3_service.analyze = lambda _data, index_df=None, resolve_index_df=None: WIE3AnalysisResult(
            market_state=_MockMarketState(),
            df_vsa=pd.DataFrame(),
        )
        patterns = {
            'phase': 'Accumulation Phase D',
            'events_detected': {},
        }

        enriched = orch._enrich_patterns_with_searchlight(
            'TEST',
            '1y',
            pd.DataFrame({
                'Open': [100.0] * 5,
                'High': [101.0] * 5,
                'Low': [99.0] * 5,
                'Close': [100.0] * 5,
                'Volume': [1000] * 5,
            }),
            patterns,
        )

        self.assertTrue(enriched['searchlight_arbitration']['available'])
        self.assertTrue(enriched['searchlight_arbitration']['has_contradiction'])
        self.assertEqual(enriched['searchlight_arbitration']['bias'], 'bearish_microstructure')
        self.assertIn('microstructure_background', enriched)
