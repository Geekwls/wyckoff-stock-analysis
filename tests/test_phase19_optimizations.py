"""Phase 19：P0/P1 威科夫语义优化"""
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.meng_reversal_detector import MengReversalDetector
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.core.trading_plan_generator import TradingPlanGenerator
from wyckoff.core.enums import WyckoffPhase
from wyckoff.schemas import (
    ClimaxModel,
    DualEventModel,
    EventsModel,
    FtiModel,
    JocModel,
    SpringModel,
    SosModel,
    SowModel,
    TradingRangeModel,
    UpthrustModel,
    WyckoffEventModel,
)


def _make_ohlcv(n: int = 30) -> pd.DataFrame:
    idx = pd.date_range('2024-01-01', periods=n, freq='D')
    return pd.DataFrame(
        {
            'Open': [100.0] * n,
            'High': [101.0] * n,
            'Low': [99.0] * n,
            'Close': [100.0] * n,
            'Volume': [1000.0] * n,
            'ATR': [1.0] * n,
        },
        index=idx,
    )


def _base_events(**kwargs) -> EventsModel:
    defaults = dict(
        trading_range=TradingRangeModel(
            is_consolidation=True,
            high=110,
            low=90,
            range_pct=0.2,
            duration_days=30,
            position=0.5,
            current_price=100,
        ),
        climax=ClimaxModel(detected=False),
        automatic_reaction=WyckoffEventModel(detected=False),
        secondary_test=WyckoffEventModel(detected=False),
        spring=SpringModel(detected=False),
        upthrust=UpthrustModel(detected=False),
        sos=SosModel(detected=False),
        sow=SowModel(detected=False),
        joc=JocModel(detected=False),
        fti=FtiModel(detected=False),
        lps_list=[],
        ut_list=[],
    )
    defaults.update(kwargs)
    events = EventsModel(**defaults)
    if defaults.get('spring', SpringModel(detected=False)).detected:
        events.spring_upthrust = DualEventModel(_type='spring', data=events.spring)
    if defaults.get('upthrust', UpthrustModel(detected=False)).detected:
        events.spring_upthrust = DualEventModel(_type='upthrust', data=events.upthrust)
    if defaults.get('sos', SosModel(detected=False)).detected:
        events.sos_sow = DualEventModel(_type='sos', data=events.sos)
    if defaults.get('sow', SowModel(detected=False)).detected:
        events.sos_sow = DualEventModel(_type='sow', data=events.sow)
    return events


class TestPhaseCRequiresPhaseA(unittest.TestCase):
    def test_isolated_spring_without_phase_a_not_phase_c(self):
        ident = PhaseIdentifier(_make_ohlcv(), WyckoffConfig(), WyckoffThresholds())
        events = _base_events(spring=SpringModel(detected=True))
        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertNotIn('Phase C', phase)
        self.assertIn('Spring待Phase A确认', phase)

    def test_spring_with_complete_phase_a_is_phase_c(self):
        ident = PhaseIdentifier(_make_ohlcv(), WyckoffConfig(), WyckoffThresholds())
        events = _base_events(
            preliminary_support=WyckoffEventModel(detected=True),
            climax=ClimaxModel(detected=True, type='selling_climax'),
            automatic_reaction=WyckoffEventModel(detected=True),
            secondary_test=WyckoffEventModel(detected=True),
            spring=SpringModel(detected=True),
        )
        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertIn('Phase C', phase)
        self.assertEqual(enum, WyckoffPhase.PHASE_C)

    def test_spring_without_ps_not_phase_c(self):
        ident = PhaseIdentifier(_make_ohlcv(), WyckoffConfig(), WyckoffThresholds())
        events = _base_events(
            climax=ClimaxModel(detected=True, type='selling_climax'),
            automatic_reaction=WyckoffEventModel(detected=True),
            secondary_test=WyckoffEventModel(detected=True),
            spring=SpringModel(detected=True),
        )
        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertNotIn('Phase C', phase)
        self.assertIn('Spring待Phase A确认', phase)


class TestTradingPlanDistributionFtiGate(unittest.TestCase):
    def test_distribution_phase_c_without_fti_waits(self):
        df = _make_ohlcv()
        pd_mock = MagicMock()
        pd_mock.identify_phase.return_value = {
            'phase': 'Distribution Phase C',
            'events_detected': {
                'upthrust': {'detected': True, 'lifecycle_status': 'active'},
                'fti': {'detected': False},
                'sow': {'detected': False},
            },
        }
        pd_mock.detect_trading_range.return_value = {'high': 110, 'low': 90}
        plan = TradingPlanGenerator(df, pd_mock).generate(phase_str='Distribution Phase C')
        self.assertEqual(plan.get('direction'), '观望')

    def test_distribution_with_fti_allows_short(self):
        df = _make_ohlcv()
        pd_mock = MagicMock()
        pd_mock.identify_phase.return_value = {
            'phase': 'Distribution Phase D',
            'events_detected': {
                'fti': {'detected': True, 'ice_level': 95.0},
                'lpsy': {'detected': True, 'price': 96.0, 'resistance_level': 96.5},
            },
        }
        pd_mock.detect_trading_range.return_value = {'high': 110, 'low': 90}
        plan = TradingPlanGenerator(df, pd_mock).generate(
            phase_str='Distribution Phase D', is_a_stock=False
        )
        self.assertEqual(plan.get('direction'), '做空')


class TestLpsySemantics(unittest.TestCase):
    def test_lpsy_requires_fti_for_primary_signal(self):
        sig, direction = SignalExtractor.resolve_primary_signal({
            'events_detected': {
                'lpsy': {'detected': True},
                'fti': {'detected': False},
            }
        })
        self.assertEqual((sig, direction), ('none', 'neutral'))

    def test_lpsy_allowed_when_fti_present(self):
        sig, direction = SignalExtractor.resolve_primary_signal({
            'events_detected': {
                'lpsy': {'detected': True},
                'fti': {'detected': True},
            }
        })
        self.assertEqual(direction, 'short')
        self.assertIn(sig, ('fti', 'lpsy'))


class TestMengSpringSecondaryTest(unittest.TestCase):
    def test_type1_spring_needs_secondary_test(self):
        det = MengReversalDetector(_make_ohlcv(), WyckoffConfig(), WyckoffThresholds())
        signal = det._build_spring_signal(
            idx=pd.Timestamp('2024-01-10'),
            breakdown_price=98.0,
            support_level=99.0,
            close_price=100.0,
            recovery_days=2,
            vol_ratio=1.5,
            close_position=0.8,
            breakdown_pct=0.02,
            b_vol=2000.0,
            v_ma=1000.0,
        )
        self.assertEqual(signal['spring_type'], 1)
        self.assertTrue(signal['needs_secondary_test'])
        self.assertFalse(signal['st_confirmed'])


class TestClimaxStRequiresAr(unittest.TestCase):
    def test_climax_st_without_ar_not_phase_b(self):
        ident = PhaseIdentifier(_make_ohlcv(), WyckoffConfig(), WyckoffThresholds())
        events = _base_events(
            climax=ClimaxModel(detected=True, type='selling_climax'),
            automatic_reaction=WyckoffEventModel(detected=False),
            secondary_test=WyckoffEventModel(detected=True),
        )
        phase, enum, conf, _ = ident._determine_phase_from_events(events)
        self.assertNotIn('Phase B', phase)


if __name__ == '__main__':
    unittest.main()
