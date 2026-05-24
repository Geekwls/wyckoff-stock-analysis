import unittest
from unittest.mock import patch

import pandas as pd

from wyckoff.core.wie3_market_state_service import WIE3AnalysisResult, WIE3MarketStateService


class TestWIE3MarketStateService(unittest.TestCase):
    def _sample_data(self):
        return pd.DataFrame({
            'Open': [100.0, 101.0, 102.0],
            'High': [101.0, 102.0, 103.0],
            'Low': [99.0, 100.0, 101.0],
            'Close': [100.5, 101.5, 102.5],
            'Volume': [1000, 1100, 1200],
        })

    def test_analyze_memoizes_same_data_and_index(self):
        service = WIE3MarketStateService()
        data = self._sample_data()
        expected = WIE3AnalysisResult(market_state=object(), df_vsa=data.copy())

        with patch.object(service, '_compute', return_value=expected) as compute_mock:
            first = service.analyze(data, index_df=None)
            second = service.analyze(data, index_df=None)

        self.assertIs(first, second)
        compute_mock.assert_called_once()

    def test_clear_cache_forces_recompute(self):
        service = WIE3MarketStateService()
        data = self._sample_data()
        expected = WIE3AnalysisResult(market_state=object(), df_vsa=data.copy())

        with patch.object(service, '_compute', return_value=expected) as compute_mock:
            service.analyze(data, index_df=None)
            service.clear_cache()
            service.analyze(data, index_df=None)

        self.assertEqual(compute_mock.call_count, 2)

    def test_explicit_and_resolved_index_share_cache(self):
        service = WIE3MarketStateService()
        data = self._sample_data()
        index_df = self._sample_data()
        expected = WIE3AnalysisResult(market_state=object(), df_vsa=data.copy())

        with patch.object(service, '_compute', return_value=expected) as compute_mock:
            explicit = service.analyze(data, index_df=index_df)
            resolved = service.analyze(
                data,
                resolve_index_df=lambda: index_df.copy(),
            )

        self.assertIs(explicit, resolved)
        compute_mock.assert_called_once()
