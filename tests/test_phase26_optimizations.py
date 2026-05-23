"""Phase 26：LPS 正式性贯通、Phase B 路径、双轨门控同步"""
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.enums import WyckoffPhase
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.core.trading_plan_generator import TradingPlanGenerator
from wyckoff.schemas import (
    SignalQualityModel,
    TradingPlanModel,
    StopLossModel,
    PositionSizingModel,
)


class TestFormalLpsContract(unittest.TestCase):
    def test_support_test_not_formal_lps(self):
        event = {
            'detected': False,
            'observation_detected': True,
            'signals': [{'signal_type': 'support_test', 'price': 20.0}],
            'latest': {'signal_type': 'support_test', 'price': 20.0},
        }
        self.assertFalse(SignalExtractor.is_formal_lps(event))
        self.assertTrue(SignalExtractor.has_lps_observation(event))

    def test_formal_lps_detected(self):
        event = {
            'detected': True,
            'latest': {'signal_type': 'lps', 'price': 20.3},
        }
        self.assertTrue(SignalExtractor.is_formal_lps(event))

    def test_joc_with_support_test_only_waits(self):
        engine = RecommendationEngine()
        data = pd.DataFrame({
            'Open': [20.0] * 10,
            'High': [21.0] * 10,
            'Low': [19.0] * 10,
            'Close': [20.5] * 10,
            'Volume': [1000] * 10,
            'ATR': [0.5] * 10,
        })
        plan = engine.generate_trading_plan(
            data,
            {
                'phase': 'Accumulation Phase D',
                'joc': {'detected': True, 'creek_level': 21.0},
                'lps': {
                    'detected': False,
                    'observation_detected': True,
                    'latest': {'signal_type': 'support_test', 'price': 20.3},
                },
            },
            {},
        )
        self.assertEqual(plan.direction, '观望')

    def test_signal_strength_ignores_support_test(self):
        patterns = {
            'events_detected': {
                'joc': {'detected': True},
                'lps': {
                    'detected': False,
                    'observation_detected': True,
                    'latest': {'signal_type': 'support_test'},
                },
            }
        }
        self.assertEqual(RecommendationEngine.calculate_signal_strength(patterns), 1)


class TestPhaseBPath(unittest.TestCase):
    def _data(self):
        n = 120
        return pd.DataFrame({
            'Open': [100.0] * n,
            'High': [101.0] * n,
            'Low': [99.0] * n,
            'Close': [100.0] * n,
            'Volume': [1000] * n,
            'MA20': [100.0] * n,
            'MA50': [100.0] * n,
            'MA200': [100.0] * n,
        })

    def test_sc_ar_st_maps_to_phase_b(self):
        identifier = PhaseIdentifier(self._data(), WyckoffConfig(), WyckoffThresholds())
        events = {
            'climax': {'detected': True, 'type': 'selling_climax', 'date': '2024-01-01'},
            'automatic_reaction': {'detected': True, 'date': '2024-01-05'},
            'secondary_test': {'detected': True, 'date': '2024-01-10'},
            'preliminary_support': {'detected': True, 'date': '2023-12-20'},
        }
        phase_str, phase_enum, *_ = identifier._determine_phase_from_events(events)
        self.assertEqual(phase_enum, WyckoffPhase.PHASE_B)
        self.assertIn('Phase B', phase_str)

    def test_sc_ar_without_ps_not_confident_phase_a(self):
        identifier = PhaseIdentifier(self._data(), WyckoffConfig(), WyckoffThresholds())
        events = {
            'climax': {'detected': True, 'type': 'selling_climax', 'date': '2024-01-01'},
            'automatic_reaction': {'detected': True, 'date': '2024-01-05'},
        }
        phase_str, phase_enum, confidence, *_ = identifier._determine_phase_from_events(events)
        self.assertEqual(phase_enum, WyckoffPhase.UNKNOWN)
        self.assertLess(confidence, 0.5)
        self.assertIn('PS', phase_str)


class TestTradingPlanGeneratorSync(unittest.TestCase):
    def _data(self):
        return pd.DataFrame({
            'Open': [20.0] * 10,
            'High': [21.0] * 10,
            'Low': [19.0] * 10,
            'Close': [20.5] * 10,
            'Volume': [1000] * 10,
            'ATR': [0.5] * 10,
        })

    def test_phase_e_without_joc_lps_waits(self):
        pd_mock = MagicMock()
        pd_mock.identify_phase.return_value = {'phase': 'Accumulation Phase E'}
        pd_mock.detect_trading_range.return_value = {'high': 22, 'low': 18}
        plan = TradingPlanGenerator(self._data(), pd_mock).generate(
            phase_str='Accumulation Phase E', is_a_stock=True
        )
        self.assertEqual(plan.get('direction'), '观望')

    def test_redistribution_waits(self):
        pd_mock = MagicMock()
        pd_mock.identify_phase.return_value = {'phase': 'Re-distribution Phase C'}
        pd_mock.detect_trading_range.return_value = {'high': 22, 'low': 18}
        plan = TradingPlanGenerator(self._data(), pd_mock).generate(
            phase_str='Re-distribution Phase C', is_a_stock=True
        )
        self.assertEqual(plan.get('direction'), '观望')

    def test_mtf_conflict_blocks_long(self):
        pd_mock = MagicMock()
        pd_mock.identify_phase.return_value = {
            'phase': 'Accumulation Phase D',
            'mtf_has_conflict': True,
            'mtf_conflict_details': '周线 bearish',
            'events_detected': {
                'joc': {'detected': True, 'creek_level': 21.0},
                'lps': {'detected': True, 'latest': {'signal_type': 'lps', 'price': 20.3}},
            },
        }
        pd_mock.detect_trading_range.return_value = {'high': 22, 'low': 18}
        plan = TradingPlanGenerator(self._data(), pd_mock).generate(
            phase_str='Accumulation Phase D', is_a_stock=True
        )
        self.assertEqual(plan.get('direction'), '观望')


class TestRiskAdviceMtfSync(unittest.TestCase):
    def test_aggressive_mtf_conflict_waits(self):
        engine = RecommendationEngine()
        quality = SignalQualityModel(score=60, max_score=100, confidence='中', reasons=[])
        plan = TradingPlanModel(
            direction='做多',
            entry_zone='test',
            stop_loss=StopLossModel(conservative=100.0, aggressive=99.0, atr_dynamic_stop=98.0),
            targets={
                'target_1': {'value': 110.0, 'derivation': 'test', 'note': 'test'},
                'target_2': {'value': 120.0, 'derivation': 'test', 'note': 'test'},
            },
            position_sizing=PositionSizingModel(conservative='25%', moderate='35%', aggressive='45%'),
            scale_in_triggers={},
            exit_rules={},
            holding_period='1-3个月',
            atr_value=1.0,
        )
        advice = engine.generate_risk_advice(
            quality,
            plan,
            has_conflict=True,
            conflict_details='周线 bearish vs 日线 spring',
        )
        self.assertEqual(advice.aggressive.action, '观望')
        self.assertEqual(advice.aggressive.position, '0%')


if __name__ == '__main__':
    unittest.main()
