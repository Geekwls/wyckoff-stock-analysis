"""Phase 28 optimizations: Searchlight structured output, boring FTI/JOC gates, EVR scoring."""
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.core.enums import MarketEnvironment
from wyckoff.core.phase_coordinator import PhaseCoordinator
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.searchlight_arbitrator import build_searchlight_arbitration
from wyckoff.core.searchlight_enrichment import apply_searchlight_phase_adjustment


class _MockBullishMicroState:
    def to_dict(self):
        return {
            'state_probs': {
                'S3: Absorption': 0.55,
                'S4: Demand Emergence': 0.25,
            },
            'aps': 8.0,
            'is_confidence_degraded': False,
            'hidden_weakness': False,
            'hidden_strength': True,
            'regime': 'S3: Absorption',
        }


class _MockBearishMicroState:
    def to_dict(self):
        return {
            'state_probs': {
                'S0: Panic Supply Dominance': 0.62,
                'S5: Distribution': 0.18,
            },
            'aps': 2.0,
            'is_confidence_degraded': False,
            'hidden_weakness': True,
            'hidden_strength': False,
            'regime': 'S0: Panic Supply Dominance',
        }


class TestSearchlightStructuredOutput(unittest.TestCase):
    def test_contradiction_includes_trade_bias_watch_only(self):
        result = build_searchlight_arbitration(
            'Accumulation Phase D',
            _MockBearishMicroState(),
        )
        self.assertTrue(result['has_contradiction'])
        self.assertEqual(result['trade_bias'], 'watch_only')
        self.assertEqual(result['dominant_evidence'], 'conflict')
        self.assertLess(result['confidence_multiplier'], 1.0)
        self.assertIn('禁止做多', result['resolution_hint'])

    def test_distribution_bullish_microstructure_contradiction(self):
        result = build_searchlight_arbitration(
            'Distribution Phase D',
            _MockBullishMicroState(),
        )
        self.assertTrue(result['has_contradiction'])
        self.assertEqual(result['bias'], 'bullish_microstructure')
        self.assertEqual(result['trade_bias'], 'watch_only')
        self.assertIn('禁止做空', result['resolution_hint'])

    def test_entropy_degraded_sets_watch_only(self):
        d = {
            'state_probs': {'S2: Neutral Compression': 0.9},
            'aps': 3.0,
            'is_confidence_degraded': True,
            'hidden_weakness': False,
            'hidden_strength': False,
            'regime': 'S2: Neutral Compression',
        }

        class _State:
            def to_dict(self):
                return d

        result = build_searchlight_arbitration('Accumulation Phase B', _State())
        self.assertEqual(result['trade_bias'], 'watch_only')
        self.assertEqual(result['confidence_multiplier'], 0.75)

    def test_phase_confidence_soft_adjustment(self):
        patterns = {
            'phase': 'Accumulation Phase D',
            'confidence': 0.8,
            'searchlight_arbitration': build_searchlight_arbitration(
                'Accumulation Phase D',
                _MockBearishMicroState(),
            ),
        }
        out = apply_searchlight_phase_adjustment(patterns)
        self.assertLess(out['confidence'], 0.8)
        self.assertTrue(out.get('searchlight_phase_notes'))


class TestBoringSymmetricGates(unittest.TestCase):
    def test_distribution_boring_requires_fti_for_high_alert(self):
        boring = {'score': 90, 'detected': True, 'high_alert': True}
        gated = PhaseCoordinator._apply_boring_fti_gate(boring, {'detected': False}, 'Distribution Phase C')
        self.assertEqual(gated.get('fti_gate'), 'pending')
        self.assertFalse(gated.get('high_alert'))

    def test_accumulation_boring_requires_joc_for_high_alert(self):
        boring = {'score': 88, 'detected': True, 'high_alert': True}
        gated = PhaseCoordinator._apply_boring_joc_gate(boring, {'detected': False}, 'Accumulation Phase B')
        self.assertEqual(gated.get('joc_gate'), 'pending')
        self.assertFalse(gated.get('high_alert'))

    def test_fti_confirmed_keeps_high_alert(self):
        boring = {'score': 90, 'detected': True, 'high_alert': True}
        gated = PhaseCoordinator._apply_boring_fti_gate(boring, {'detected': True}, 'Distribution Phase D')
        self.assertTrue(gated.get('high_alert'))


class TestPhase28Scoring(unittest.TestCase):
    def _minimal_data(self):
        return pd.DataFrame({
            'Open': [100.0] * 30,
            'High': [101.0] * 30,
            'Low': [99.0] * 30,
            'Close': [100.0] * 30,
            'Volume': [1000] * 30,
        })

    def _strong_bullish_patterns(self):
        return {
            'phase': 'Accumulation Phase D',
            'events_detected': {
                'spring': {'detected': True, 'confidence': 0.9, 'volume_ratio': 2.0},
                'joc': {'detected': True, 'confidence': 0.85, 'volume_ratio': 2.5},
                'sos': {'detected': True, 'confidence': 0.8, 'volume_ratio': 1.8},
                'lps': {
                    'detected': True,
                    'confidence': 0.75,
                    'volume_ratio': 0.6,
                    'signal_type': 'lps',
                },
            },
            'sequence_validation': {
                'sequence_score': {'rating': 'A'},
                'spring': {'quality': 'high'},
            },
        }

    def test_two_layer_scoring_fields_present(self):
        engine = RecommendationEngine()
        quality = engine.calculate_weighted_score(
            self._minimal_data(),
            self._strong_bullish_patterns(),
            MarketEnvironment.STRONG_BULL,
        )
        self.assertIsNotNone(quality.structure_score)
        self.assertIsNotNone(quality.background_adjustment)
        self.assertEqual(quality.score, quality.structure_score + quality.background_adjustment)

    def test_evr_resonance_bonus(self):
        engine = RecommendationEngine()
        patterns = self._strong_bullish_patterns()
        patterns['mtf_evr_resonance'] = {
            'boost': True,
            'note': '周线 EVR + 日线Spring 共现，信号可靠性提升',
        }
        quality = engine.calculate_weighted_score(
            self._minimal_data(),
            patterns,
            MarketEnvironment.STRONG_BULL,
        )
        self.assertTrue(any('EVR' in r for r in quality.reasons), quality.reasons)

    def test_boring_floor_blocked_without_joc_in_accumulation(self):
        engine = RecommendationEngine()
        patterns = {
            'phase': 'Accumulation Phase B',
            'events_detected': {
                'spring': {'detected': True, 'confidence': 0.7},
                'boring_zone': {'detected': True, 'score': 90, 'high_alert': True},
            },
            'sequence_validation': {'sequence_score': {'rating': 'C'}},
        }
        quality = engine.calculate_weighted_score(
            self._minimal_data(),
            patterns,
            MarketEnvironment.UNKNOWN,
        )
        self.assertTrue(any('缺 JOC' in r for r in quality.reasons), quality.reasons)

    def test_trade_bias_blocks_trading_plan(self):
        engine = RecommendationEngine()
        patterns = self._strong_bullish_patterns()
        patterns['searchlight_arbitration'] = build_searchlight_arbitration(
            'Accumulation Phase D',
            _MockBearishMicroState(),
        )
        plan = engine.generate_trading_plan(self._minimal_data(), patterns, {})
        self.assertEqual(plan.direction, '观望')
        self.assertIn('禁止做多', plan.entry_zone)


if __name__ == '__main__':
    unittest.main()
