"""Phase 25：威科夫第五步入场 + RS/MTF 方向硬门控"""
import unittest

import pandas as pd

from wyckoff.core.enums import MarketEnvironment
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.trading_plan_generator import TradingPlanGenerator
from unittest.mock import MagicMock


class TestWyckoffStep5EntryGate(unittest.TestCase):
    def _data(self):
        return pd.DataFrame({
            'Open': [20.0] * 10,
            'High': [21.0] * 10,
            'Low': [19.0] * 10,
            'Close': [20.5] * 10,
            'Volume': [1000] * 10,
            'ATR': [0.5] * 10,
        })

    def test_joc_without_lps_waits(self):
        engine = RecommendationEngine()
        plan = engine.generate_trading_plan(
            self._data(),
            {
                'phase': 'Accumulation Phase D',
                'joc': {'detected': True, 'creek_level': 21.0},
                'lps': {'detected': False},
            },
            {},
        )
        self.assertEqual(plan.direction, '观望')
        self.assertIn('LPS', plan.entry_zone)

    def test_joc_with_lps_long(self):
        engine = RecommendationEngine()
        plan = engine.generate_trading_plan(
            self._data(),
            {
                'phase': 'Accumulation Phase D',
                'joc': {'detected': True, 'creek_level': 21.0},
                'lps': {'detected': True, 'price': 20.3},
            },
            {},
        )
        self.assertEqual(plan.direction, '做多')
        self.assertIn('JOC+LPS', plan.entry_zone)

    def test_fti_without_lpsy_waits(self):
        engine = RecommendationEngine()
        plan = engine.generate_trading_plan(
            self._data(),
            {
                'phase': 'Distribution Phase D',
                'fti': {'detected': True, 'ice_level': 19.0},
                'lpsy': {'detected': False},
            },
            {},
        )
        self.assertEqual(plan.direction, '观望')
        self.assertIn('LPSY', plan.entry_zone)

    def test_trading_plan_generator_fti_requires_lpsy(self):
        pd_mock = MagicMock()
        pd_mock.identify_phase.return_value = {
            'phase': 'Distribution Phase D',
            'events_detected': {
                'fti': {'detected': True, 'ice_level': 95.0},
            },
        }
        pd_mock.detect_trading_range.return_value = {'high': 110, 'low': 90}
        plan = TradingPlanGenerator(self._data(), pd_mock).generate(
            phase_str='Distribution Phase D', is_a_stock=False
        )
        self.assertEqual(plan.get('direction'), '观望')


class TestHarmonyHardGates(unittest.TestCase):
    def _data(self):
        return pd.DataFrame({
            'Open': [100.0] * 5,
            'High': [101.0] * 5,
            'Low': [99.0] * 5,
            'Close': [100.0] * 5,
            'Volume': [1000] * 5,
            'ATR': [1.0] * 5,
        })

    def test_mtf_conflict_forces_watch_on_long(self):
        engine = RecommendationEngine()
        plan = engine.generate_trading_plan(
            self._data(),
            {
                'phase': 'Accumulation Phase D',
                'mtf_has_conflict': True,
                'mtf_conflict_details': '周线 bearish vs 日线 spring',
                'joc': {'detected': True, 'creek_level': 105.0},
                'lps': {'detected': True, 'price': 103.0},
            },
            {},
        )
        self.assertEqual(plan.direction, '观望')
        self.assertIn('跨周期冲突', plan.entry_zone)

    def test_rs_falling_blocks_accumulation_long(self):
        engine = RecommendationEngine()
        plan = engine.generate_trading_plan(
            self._data(),
            {
                'phase': 'Accumulation Phase D',
                'relative_strength': {'rs_trend': 'falling'},
                'joc': {'detected': True, 'creek_level': 105.0},
                'lps': {'detected': True, 'price': 103.0},
            },
            {},
        )
        self.assertEqual(plan.direction, '观望')
        self.assertIn('相对强度', plan.entry_zone)


if __name__ == '__main__':
    unittest.main()
