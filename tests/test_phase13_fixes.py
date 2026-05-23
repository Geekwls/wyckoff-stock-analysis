"""Phase 13: 审查问题修复回归测试"""
import os
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.core.enums import WyckoffPhase
from wyckoff.core.pattern_detector import WyckoffPatternDetector
from wyckoff.core.symbol_resolver import SymbolResolver
from wyckoff.core.strategies.yfinance_strategy import YFinanceStrategy
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.config.settings import WyckoffConfig


class TestPhase13Fixes(unittest.TestCase):
    def test_yfinance_interval_1w_maps_to_1wk(self):
        self.assertEqual(YFinanceStrategy.normalize_interval('1w'), '1wk')
        self.assertEqual(YFinanceStrategy.normalize_interval('weekly'), '1wk')
        self.assertEqual(YFinanceStrategy.normalize_interval('1d'), '1d')

    def test_hk_prefix_symbol_resolved(self):
        info = SymbolResolver().resolve('hk.00700')
        self.assertEqual(info.normalized, '0700.HK')
        self.assertEqual(info.market.value, 'HK_STOCK')

    def test_merge_coordinator_without_arbitration_marker(self):
        detector = WyckoffPatternDetector.__new__(WyckoffPatternDetector)
        events = MagicMock()
        events.coordinator_final_phase = 'Markdown / Trending Down'
        events.phase_revision_log = ['[Phase Transition] 趋势确认']

        merged = detector._merge_coordinator_phase(
            {'phase': 'Accumulation Phase C (积累期震仓)', 'phase_enum': WyckoffPhase.PHASE_C},
            events,
        )
        self.assertEqual(merged['phase'], 'Markdown / Trending Down')
        self.assertIn(merged['phase_source'], ('coordinator', 'coordinator_reconcile'))

    def test_phase_b_keeps_canonical_label(self):
        n = 80
        df = pd.DataFrame({
            'Open': [100.0] * n,
            'High': [101.0] * n,
            'Low': [99.0] * n,
            'Close': [100.0] * n,
            'Volume': [1_000_000.0] * n,
        }, index=pd.date_range('2024-01-01', periods=n, freq='B'))

        pid = PhaseIdentifier(df, WyckoffConfig(), WyckoffConfig().thresholds)

        class MockClimax:
            detected = True
            type = 'buying_climax'

        class MockAR:
            detected = True

        class MockST:
            detected = True

        class MockEvents:
            trading_range = {'is_consolidation': True, 'duration_days': 60}
            lps_list = [{}, {}]
            ut_list = []
            climax = MockClimax()
            automatic_reaction = MockAR()
            secondary_test = MockST()
            vsa_signals = {}

        result = pid._detect_phase_b_active(MockEvents())
        self.assertIsNotNone(result)
        phase_label, _, _, note = result
        self.assertIn('Distribution Phase B', phase_label)
        self.assertNotIn('[警告]', phase_label)
        if note:
            self.assertTrue(note.startswith('['))

    def test_bearish_spring_trading_plan_waits(self):
        engine = RecommendationEngine(WyckoffConfig())
        n = 30
        data = pd.DataFrame({
            'Open': [100.0] * n,
            'High': [101.0] * n,
            'Low': [99.0] * n,
            'Close': [100.0] * n,
            'Volume': [1e6] * n,
            'ATR': [2.0] * n,
        }, index=pd.date_range('2024-01-01', periods=n, freq='B'))

        patterns = {
            'phase': 'Markdown / Trending Down',
            'coordinator_phase': 'Markdown / Trending Down',
            'spring': {'detected': True, 'latest_spring': {'breakdown_price': 98.0, 'price': 98.0}},
            'joc': {'detected': False},
        }
        plan = engine.generate_trading_plan(data, patterns, {})
        self.assertEqual(plan.direction, '观望')

    def test_yfinance_cache_roundtrip(self):
        import tempfile
        df = pd.DataFrame({
            'Open': [1.0], 'High': [1.1], 'Low': [0.9], 'Close': [1.0], 'Volume': [100.0],
        }, index=pd.to_datetime(['2024-01-02']))
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['WYCKOFF_CACHE_DIR'] = tmp
            YFinanceStrategy._write_cache('TEST', '1y', '1d', df)
            loaded = YFinanceStrategy._read_cache('TEST', '1y', '1d', max_age=3600)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded), 1)
            os.environ.pop('WYCKOFF_CACHE_DIR', None)

    def test_orchestrator_run_analysis_synthetic(self):
        from wyckoff.core.orchestrator import WyckoffOrchestrator
        from wyckoff.core.enums import MarketEnvironment
        from wyckoff.core.data_fetcher import prepare_data
        from wyckoff.exceptions import DataFetchError

        n = 120
        raw = pd.DataFrame({
            'Open': [100 + i * 0.1 for i in range(n)],
            'High': [101 + i * 0.1 for i in range(n)],
            'Low': [99 + i * 0.1 for i in range(n)],
            'Close': [100.5 + i * 0.1 for i in range(n)],
            'Volume': [1_000_000.0] * n,
        }, index=pd.date_range('2024-01-01', periods=n, freq='B'))
        data = prepare_data(raw, WyckoffConfig())

        orch = WyckoffOrchestrator(WyckoffConfig())

        def _mock_fetch(symbol, period, frequency='1d'):
            if str(frequency).lower() not in ('1d', 'd', 'daily'):
                raise DataFetchError(symbol, 'mtf skip')
            return symbol, data.copy()

        orch.data_fetcher.fetch_data = _mock_fetch
        orch._analyze_market_env = lambda _s, _p: MarketEnvironment.RANGE_BOUND

        result = orch.run_analysis('SYNTEST', '1y')
        self.assertEqual(result['symbol'], 'SYNTEST')
        self.assertIn('trading_plan', result)
        self.assertIn('patterns', result)
        self.assertIn('phase', result['patterns'])


if __name__ == '__main__':
    unittest.main()
