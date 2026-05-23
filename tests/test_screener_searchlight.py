"""Screener/batch scan Searchlight integration tests."""
import unittest
from unittest.mock import patch

import pandas as pd

from wyckoff.config.settings import WyckoffThresholds
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.enums import MarketEnvironment
from wyckoff.core.wie3_market_state_service import WIE3AnalysisResult, WIE3MarketStateService
from wyckoff.services.screener_service import ScreenerService


class _MockBearishMarketState:
    def to_dict(self):
        return {
            'state_probs': {
                'S0: Panic Supply Dominance': 0.62,
                'S3: Absorption': 0.15,
            },
            'aps': 2.0,
            'is_confidence_degraded': False,
            'hidden_weakness': False,
            'hidden_strength': False,
            'regime': 'S0: Panic Supply Dominance',
        }


def _sample_ohlcv(rows: int = 30) -> pd.DataFrame:
    return pd.DataFrame({
        'Open': [100.0] * rows,
        'High': [101.0] * rows,
        'Low': [99.0] * rows,
        'Close': [100.0] * rows,
        'Volume': [1000] * rows,
    })


class TestScreenerSearchlightIntegration(unittest.TestCase):
    def test_prepare_scoring_payload_applies_contradiction_cap(self):
        screener = ScreenerService()
        phase_res = {
            'phase': 'Accumulation Phase D',
            'confidence': 0.8,
            'events_detected': {
                'spring': {'detected': True, 'confidence': 0.9},
                'sos': {'detected': True, 'confidence': 0.85},
            },
        }
        data = _sample_ohlcv()

        screener._wie3_service.analyze = lambda _data, index_df=None, resolve_index_df=None: WIE3AnalysisResult(
            market_state=_MockBearishMarketState(),
            df_vsa=pd.DataFrame(),
        )

        patterns = screener._prepare_scoring_payload(phase_res, data)
        engine = RecommendationEngine()
        quality = engine.calculate_signal_quality(data, patterns, MarketEnvironment.UNKNOWN)

        self.assertTrue(patterns['searchlight_arbitration']['has_contradiction'])
        self.assertLessEqual(quality.score, 45)
        self.assertTrue(any('Searchlight/WIE3' in r for r in quality.reasons))

    def test_scan_fields_exposed_on_result_row(self):
        from wyckoff.core.searchlight_enrichment import searchlight_scan_fields

        screener = ScreenerService()
        screener._wie3_service.analyze = lambda *_a, **_k: WIE3AnalysisResult(
            market_state=_MockBearishMarketState(),
            df_vsa=pd.DataFrame(),
        )
        patterns = screener._prepare_scoring_payload(
            {'phase': 'Accumulation Phase D', 'events_detected': {}},
            _sample_ohlcv(),
        )
        row = searchlight_scan_fields(patterns)
        self.assertTrue(row['searchlight_available'])
        self.assertTrue(row['searchlight_contradiction'])
        self.assertEqual(row['searchlight_bias'], 'bearish_microstructure')

    @patch.object(ScreenerService, '_scan_single')
    def test_batch_summary_includes_searchlight_contradiction_count(self, mock_scan):
        mock_scan.side_effect = [
            {
                'symbol': 'A',
                'phase': 'Accumulation',
                'strength': 2,
                'weighted_score': 70,
                'searchlight_contradiction': True,
                'searchlight_available': True,
                'searchlight_bias': 'bearish_microstructure',
                'searchlight_entropy_degraded': False,
            },
            {
                'symbol': 'B',
                'phase': 'Markup',
                'strength': 1,
                'weighted_score': 80,
                'searchlight_contradiction': False,
                'searchlight_available': True,
                'searchlight_bias': 'neutral',
                'searchlight_entropy_degraded': False,
            },
        ]
        screener = ScreenerService()
        result = screener.batch_scan(['A', 'B'], scan_mode='quick', show_progress=False)

        self.assertEqual(result['summary']['searchlight_contradiction_count'], 1)

    def test_spring_searchlight_context_caps_score(self):
        screener = ScreenerService()
        screener._wie3_service.analyze = lambda _data, index_df=None, resolve_index_df=None: WIE3AnalysisResult(
            market_state=_MockBearishMarketState(),
            df_vsa=pd.DataFrame(),
        )

        class _FakeDetector:
            def identify_phase(self):
                return {
                    'phase': 'Accumulation Phase D',
                    'confidence': 0.8,
                    'events_detected': {
                        'spring': {'detected': True, 'confidence': 0.9},
                    },
                }

        ctx = screener._build_spring_searchlight_context(
            'sh.600000',
            '1y',
            _sample_ohlcv(),
            _FakeDetector(),
        )
        self.assertTrue(ctx['searchlight_contradiction'])
        self.assertLessEqual(ctx['weighted_score'], 45)
        self.assertEqual(ctx['searchlight_bias'], 'bearish_microstructure')

    def test_spring_sort_deprioritizes_searchlight_contradiction(self):
        rows = [
            {'confirmation': 'confirmed', 'confidence': 90, 'weighted_score': 80,
             'searchlight_contradiction': True},
            {'confirmation': 'pending', 'confidence': 70, 'weighted_score': 60,
             'searchlight_contradiction': False},
        ]
        rows.sort(key=lambda x: (
            1 if x.get('searchlight_contradiction') else 0,
            0 if x.get('confirmation') == 'confirmed' else 1,
            -x.get('weighted_score', x.get('confidence', 0)),
        ))
        self.assertFalse(rows[0]['searchlight_contradiction'])
