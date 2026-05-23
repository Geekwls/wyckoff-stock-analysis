"""Phase 0：SOS/SOW 契约 / Spring 置信度 / EventsModel 评分"""
import unittest

import pandas as pd

from wyckoff.core.phase_coordinator import (
    _normalize_sos_event,
    _normalize_sow_event,
    _normalize_spring_event,
    _normalize_upthrust_event,
    _get_pydantic_fields,
)
from wyckoff.core.detectors.meng_reversal_detector import MengReversalDetector
from wyckoff.core.event_arbitrator import EventArbitrator
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.schemas import SosModel, SowModel, EventsModel, TradingRangeModel, LpsModel


def _minimal_tr() -> TradingRangeModel:
    return TradingRangeModel(
        is_consolidation=True,
        high=110.0,
        low=90.0,
        range_pct=20.0,
        duration_days=60,
        position=0.5,
        current_price=100.0,
    )


class TestSosSowModelRoundtrip(unittest.TestCase):
    def test_sos_model_preserves_latest_after_safe_filter(self):
        raw = _normalize_sos_event({
            'detected': True,
            'date': '2024-06-01',
            'price': 110.0,
            'volume_ratio': 1.75,
            'price_change': 0.025,
            'breakthrough_level': 108.5,
            'breakout_type': 'breakout_sos',
        })
        valid = set(_get_pydantic_fields(SosModel))
        filtered = {k: v for k, v in raw.items() if k in valid}
        model = SosModel(**filtered)
        self.assertTrue(model.detected)
        self.assertIsNotNone(model.latest)
        self.assertEqual(model.latest.volume_ratio, 1.75)

    def test_sow_model_preserves_latest(self):
        raw = _normalize_sow_event({
            'detected': True,
            'date': '2024-06-02',
            'price': 90.0,
            'volume_ratio': 1.6,
            'price_change': -0.03,
            'breakdown_level': 92.0,
        })
        valid = set(_get_pydantic_fields(SowModel))
        model = SowModel(**{k: v for k, v in raw.items() if k in valid})
        self.assertTrue(model.latest is not None)
        self.assertAlmostEqual(model.latest.price, 90.0)

    def test_get_event_dict_flattens_latest(self):
        tr = _minimal_tr()
        events = EventsModel(
            trading_range=tr,
            sos=SosModel(
                detected=True,
                latest={
                    'date': '2024-01-01',
                    'price': 100.0,
                    'volume_ratio': 1.8,
                    'price_change': 0.02,
                    'breakthrough_level': 99.0,
                },
            ),
        )
        sos = SignalExtractor.get_event_dict(events, 'sos')
        self.assertEqual(sos.get('volume_ratio'), 1.8)
        self.assertEqual(sos.get('price'), 100.0)


class TestSpringConfidenceScale(unittest.TestCase):
    def setUp(self):
        self.det = MengReversalDetector(None, WyckoffConfig(), WyckoffThresholds())

    def test_close_position_085_gets_top_tier(self):
        score = self.det._calculate_spring_confidence(
            breakdown_pct=2.0,
            recovery_days=2,
            vol_ratio=2.0,
            close_position=0.85,
            is_high_speed=True,
            s_type=2,
        )
        self.assertGreaterEqual(score, 80)


class TestArbitratorSosExtraction(unittest.TestCase):
    def test_arbitrator_reads_sos_from_model(self):
        model = SosModel(
            detected=True,
            latest={
                'date': '2024-03-01',
                'price': 50.0,
                'volume_ratio': 2.0,
                'price_change': 0.03,
                'breakthrough_level': 49.0,
            },
        )
        arb = EventArbitrator(pd.DataFrame({'Close': [100.0] * 5}))
        signals = arb._extract_sos_signals(model)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_type, 'sos')
        self.assertGreater(signals[0].confidence, 0.5)


class TestSignalStrengthEventsModel(unittest.TestCase):
    def test_calculate_signal_strength_with_events_model(self):
        tr = _minimal_tr()
        events = EventsModel(
            trading_range=tr,
            sos=SosModel(detected=True, latest={
                'date': '2024-01-01',
                'price': 1.0,
                'volume_ratio': 1.5,
                'price_change': 0.01,
                'breakthrough_level': 1.0,
            }),
            lps=LpsModel(detected=True),
        )
        phase_res = {'events_detected': events, 'phase': 'Accumulation Phase C'}
        strength = RecommendationEngine.calculate_signal_strength(phase_res)
        # Phase 26：LPS 无 JOC 前置时不计入 signal strength
        self.assertEqual(strength, 1)


class TestSpringNormalize(unittest.TestCase):
    def test_latest_spring_promoted(self):
        raw = {
            'detected': True,
            'signals': [{'date': '2024-01-01', 'recovery_days': 2, 'volume_ratio': 1.5}],
            'latest_spring': {'date': '2024-01-01', 'recovery_days': 2, 'volume_ratio': 1.5},
        }
        out = _normalize_spring_event(raw)
        self.assertIsNotNone(out.get('latest_spring'))
        self.assertTrue(out.get('signals'))


class TestUpthrustNormalize(unittest.TestCase):
    def test_latest_upthrust_promoted(self):
        raw = {
            'detected': True,
            'signals': [{'breakout_price': 105.0, 'rejection_price': 103.0}],
        }
        out = _normalize_upthrust_event(raw)
        self.assertIsNotNone(out.get('latest_upthrust'))
        self.assertEqual(out['latest_upthrust']['breakout_price'], 105.0)
