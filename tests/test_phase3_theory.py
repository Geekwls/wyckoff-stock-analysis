"""Phase 3：P&F 因果 / Symbol / VSA 修复"""
import unittest

from wyckoff.core.symbol_resolver import SymbolResolver, MarketType
from wyckoff.core.point_and_figure import PointAndFigureCalculator


class TestSymbolResolverPhase3(unittest.TestCase):
    def setUp(self):
        self.resolver = SymbolResolver()

    def test_brk_b_is_us_stock(self):
        info = self.resolver.resolve("BRK-B")
        self.assertEqual(info.market, MarketType.US_STOCK)

    def test_btc_usd_still_crypto(self):
        info = self.resolver.resolve("BTC-USD")
        self.assertEqual(info.market, MarketType.CRYPTO)


class TestPnfAccumulationDirection(unittest.TestCase):
    def test_accumulation_phase_targets_upward(self):
        calc = PointAndFigureCalculator(box_size_pct=1.0, reversal_boxes=3)
        columns = []
        for i in range(12):
            direction = 'up' if i % 2 == 0 else 'down'
            base = 100 + (i % 4)
            columns.append({
                'direction': direction,
                'start_idx': i * 3,
                'low': base,
                'high': base + 2,
                'boxes': [base, base + 1],
            })
        pnf_data = {'columns': columns}
        result = calc.calculate_horizontal_count(
            pnf_data,
            phase='Accumulation Phase B',
            known_tr_high=110.0,
            known_tr_low=98.0,
            dynamic_threshold=1,
        )
        self.assertEqual(result.get('breakout_direction'), 'up')
        targets = result.get('targets', {})
        self.assertGreater(targets.get('target_1', 0), 110.0)

    def test_distribution_phase_targets_downward(self):
        calc = PointAndFigureCalculator(box_size_pct=1.0, reversal_boxes=3)
        columns = []
        for i in range(12):
            direction = 'up' if i % 2 == 0 else 'down'
            base = 100 + (i % 4)
            columns.append({
                'direction': direction,
                'start_idx': i * 3,
                'low': base,
                'high': base + 2,
                'boxes': [base, base + 1],
            })
        pnf_data = {'columns': columns}
        result = calc.calculate_horizontal_count(
            pnf_data,
            phase='Distribution Phase B',
            known_tr_high=110.0,
            known_tr_low=98.0,
            dynamic_threshold=1,
        )
        self.assertEqual(result.get('breakout_direction'), 'down')
        targets = result.get('targets', {})
        self.assertLess(targets.get('target_1', 999), 98.0)
