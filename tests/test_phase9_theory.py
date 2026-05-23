"""Phase 9：深度审查修复 — JOC 优先 / FTI Phase D / CHoCH 枚举"""
import unittest

import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.utils import is_bearish_choch, is_bullish_choch, normalize_choch_direction
from wyckoff.schemas import (
    EventsModel,
    TradingRangeModel,
    SpringModel,
    SosModel,
    JocModel,
    FtiModel,
    UpthrustModel,
    SowModel,
    ClimaxModel,
    WyckoffEventModel,
    DualEventModel,
)


class TestChoChDirectionNormalize(unittest.TestCase):
    def test_bullish_aliases(self):
        for d in ('bullish', 'up', 'long'):
            self.assertEqual(normalize_choch_direction(d), 'bullish')
            self.assertTrue(is_bullish_choch(d))

    def test_bearish_aliases(self):
        for d in ('bearish', 'down', 'short'):
            self.assertEqual(normalize_choch_direction(d), 'bearish')
            self.assertTrue(is_bearish_choch(d))


class TestPhase9BreakoutPriority(unittest.TestCase):
    def _make_df(self, n: int = 80) -> pd.DataFrame:
        idx = pd.Series({'Close': [45.0] * n})
        return idx.to_frame()

    def _base_events(self, **kwargs) -> EventsModel:
        defaults = dict(
            trading_range=TradingRangeModel(
                is_consolidation=True,
                high=50,
                low=40,
                range_pct=0.2,
                duration_days=60,
                position=0.5,
                current_price=48,
            ),
            climax=ClimaxModel(detected=True, type='selling_climax'),
            automatic_reaction=WyckoffEventModel(detected=True),
            secondary_test=WyckoffEventModel(detected=True),
            spring=SpringModel(detected=False),
            upthrust=UpthrustModel(detected=False),
            sos=SosModel(detected=False),
            sow=SowModel(detected=False),
            joc=JocModel(detected=False),
            fti=FtiModel(detected=False),
            lps_list=[
                {'detected': True, 'date': '2024-01-01', 'price': 42.0},
                {'detected': True, 'date': '2024-01-15', 'price': 43.0},
            ],
            ut_list=[],
        )
        defaults.update(kwargs)
        events = EventsModel(**defaults)
        if defaults.get('spring', SpringModel(detected=False)).detected:
            events.spring_upthrust = DualEventModel(_type='spring', data=events.spring)
        if defaults.get('sos', SosModel(detected=False)).detected:
            events.sos_sow = DualEventModel(_type='sos', data=events.sos)
        if defaults.get('upthrust', UpthrustModel(detected=False)).detected:
            events.spring_upthrust = DualEventModel(_type='upthrust', data=events.upthrust)
        if defaults.get('sow', SowModel(detected=False)).detected:
            events.sos_sow = DualEventModel(_type='sow', data=events.sow)
        return events

    def test_joc_wins_over_phase_b_when_lps_tests_present(self):
        """B1：Climax+AR+2LPS+JOC 应 Phase D，而非 Phase B。"""
        ident = PhaseIdentifier(self._make_df(), WyckoffConfig(), WyckoffThresholds())
        joc = JocModel(detected=True, test_detected=True, test_score=80)
        events = self._base_events(
            spring=SpringModel(detected=True),
            sos=SosModel(detected=True, breakout_type='breakout_sos'),
            joc=joc,
        )
        events.spring_upthrust = DualEventModel(_type='spring', data=events.spring)
        events.sos_sow = DualEventModel(_type='sos', data=events.sos)

        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertIn('Phase D', phase)
        self.assertNotIn('Phase B', phase)
        self.assertGreaterEqual(conf, 0.85)

    def test_upthrust_sow_without_fti_is_phase_c_plus(self):
        """B3：Upthrust+SOW 无 FTI 最高 Phase C+。"""
        ident = PhaseIdentifier(self._make_df(), WyckoffConfig(), WyckoffThresholds())
        events = self._base_events(
            climax=ClimaxModel(detected=True, type='buying_climax'),
            spring=SpringModel(detected=False),
            upthrust=UpthrustModel(detected=True),
            sow=SowModel(detected=True),
            fti=FtiModel(detected=False),
            lps_list=[],
        )
        events.spring_upthrust = DualEventModel(_type='upthrust', data=events.upthrust)
        events.sos_sow = DualEventModel(_type='sow', data=events.sow)

        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertIn('Phase C', phase)
        self.assertNotIn('Phase D', phase)
        self.assertIn('FTI', phase)

    def test_fti_is_distribution_phase_d(self):
        """B3：FTI detected → Distribution Phase D。"""
        ident = PhaseIdentifier(self._make_df(), WyckoffConfig(), WyckoffThresholds())
        events = self._base_events(
            climax=ClimaxModel(detected=True, type='buying_climax'),
            fti=FtiModel(detected=True, test_detected=True),
            lps_list=[],
        )
        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertIn('Phase D', phase)
        self.assertIn('Distribution', phase)
        self.assertGreaterEqual(conf, 0.85)


if __name__ == '__main__':
    unittest.main()
