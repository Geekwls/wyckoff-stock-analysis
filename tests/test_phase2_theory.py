"""Phase 2 理论修复：JOC 回测 / Breakout TR 窗口 / Phase D 硬约束"""
import unittest
import pandas as pd
import numpy as np
from datetime import datetime

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.breakout_analyzer import BreakoutAnalyzer
from wyckoff.core.detectors.meng_trend_detector import MengTrendDetector
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.schemas import (
    EventsModel, TradingRangeModel, SpringModel, SosModel, JocModel,
    DualEventModel, ClimaxModel, WyckoffEventModel,
)


class TestJocTestValidation(unittest.TestCase):
    def setUp(self):
        self.det = MengTrendDetector(None, WyckoffConfig(), WyckoffThresholds())

    def test_deep_breakdown_not_valid_test(self):
        creek = 100.0
        # 深跌破位且收盘未收回
        self.assertFalse(self.det._is_valid_joc_test_bar(90.0, 92.0, 500_000, 1_000_000, creek))

    def test_valid_test_in_band_with_reclaim(self):
        creek = 100.0
        self.assertTrue(self.det._is_valid_joc_test_bar(99.5, 100.2, 700_000, 1_000_000, creek))

    def test_finalize_rejects_low_quality_score(self):
        creek = 100.0
        # 放量 + 大实体 → 质量分通常低于 60
        ok, score, quality, _ = self.det._finalize_joc_test(
            99.8, 101.0, 100.0, 102.0, 2_000_000, 1_000_000, creek, 0.5
        )
        self.assertFalse(ok)


class TestBreakoutTrScope(unittest.TestCase):
    def test_ignores_historical_breakout_before_tr_window(self):
        dates = pd.date_range('2020-01-01', periods=120, freq='D')
        closes = [55.0] * 60
        for i in range(50):
            closes.append(45.0 + (i % 5) * 0.2)
        for i in range(10):
            closes.append(52.0 + i * 0.1)

        df = pd.DataFrame({
            'Open': closes,
            'High': [c + 0.5 for c in closes],
            'Low': [c - 0.5 for c in closes],
            'Close': closes,
            'Volume': [1_000_000] * 120,
        }, index=dates)

        analyzer = BreakoutAnalyzer(df)
        tr = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'up',
            'current_price': 53.0,
            'range_start_idx': 60,
            'duration_days': 60,
        }
        scoped = analyzer._get_tr_scoped_data(tr)
        self.assertEqual(len(scoped), 60)
        breakout_idx = scoped[scoped['Close'] > 50.0].index[0]
        self.assertGreaterEqual(df.index.get_loc(breakout_idx), 60)


class TestPhaseDRequiresJoc(unittest.TestCase):
    def _make_events(self, *, joc=False, spring=False, sos=False):
        spring_model = SpringModel(detected=spring)
        sos_model = SosModel(detected=sos, breakout_type='breakout_sos')
        joc_model = JocModel(detected=joc, test_detected=True, test_score=80) if joc else JocModel(detected=False)
        events = EventsModel(
            trading_range=TradingRangeModel(
                is_consolidation=True, high=50, low=40, range_pct=0.2,
                duration_days=60, position=0.5, current_price=48,
            ),
            climax=ClimaxModel(detected=False),
            automatic_reaction=WyckoffEventModel(detected=False),
            secondary_test=WyckoffEventModel(detected=False),
            spring=spring_model,
            sos=sos_model,
            joc=joc_model,
        )
        if spring:
            events.spring_upthrust = DualEventModel(_type='spring', data=spring_model)
        if sos:
            events.sos_sow = DualEventModel(_type='sos', data=sos_model)
        return events

    def test_spring_sos_without_joc_is_not_phase_d(self):
        idx = pd.Series({'Close': [45] * 80})
        ident = PhaseIdentifier(idx.to_frame(), WyckoffConfig(), WyckoffThresholds())
        events = self._make_events(joc=False, spring=True, sos=True)
        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertIn('Phase C', phase)
        self.assertNotIn('Phase D', phase)

    def test_joc_is_phase_d(self):
        idx = pd.Series({'Close': [45] * 80})
        ident = PhaseIdentifier(idx.to_frame(), WyckoffConfig(), WyckoffThresholds())
        events = self._make_events(joc=True, spring=True, sos=True)
        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertIn('Phase D', phase)
        self.assertGreaterEqual(conf, 0.85)


if __name__ == '__main__':
    unittest.main()
