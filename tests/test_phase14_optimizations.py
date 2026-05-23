"""Phase 14：威科夫审查优化 — JOC 主链 / 阶段描述同步 / 孤立 SOW / Spring 门控 / CHoCH"""
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.enums import WyckoffPhase
from wyckoff.core.pattern_detector import WyckoffPatternDetector
from wyckoff.core.phase_coordinator import PhaseCoordinator, PhaseTransitionCriteria
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.utils import continuous_price_confirmation
from wyckoff.schemas import ClimaxModel, EventsModel, JocModel, SpringModel, TradingRangeModel


class TestJocMengPrimary(unittest.TestCase):
    def test_detect_joc_prefers_meng_enhanced(self):
        detector = WyckoffPatternDetector.__new__(WyckoffPatternDetector)
        detector.meng_enhancer = MagicMock()
        detector.classic_detector = MagicMock()
        detector.detect_channels = MagicMock(return_value={'overbought_oversold': None})
        detector.detect_trading_range = MagicMock(return_value={'high': 50, 'low': 40})
        detector.detect_absorption = MagicMock(return_value={'detected': False})

        meng_res = {
            'detected': True,
            'latest': {'creek_level': 21.0, 'confidence': 0.9},
            'method': 'meng_hongtao_joc',
        }
        detector.meng_enhancer.detect_joc_enhanced.return_value = meng_res

        result = WyckoffPatternDetector.detect_joc(detector)
        detector.meng_enhancer.detect_joc_enhanced.assert_called_once()
        detector.classic_detector.detect_joc.assert_not_called()
        self.assertTrue(result['detected'])
        self.assertEqual(result['method'], 'meng_hongtao_joc')


class TestMergePhaseDescriptionSync(unittest.TestCase):
    def test_stale_description_cleared_on_reconcile(self):
        detector = WyckoffPatternDetector.__new__(WyckoffPatternDetector)
        events = MagicMock()
        events.coordinator_final_phase = 'Distribution Phase A'
        events.phase_revision_log = ['[Phase Transition] 派发结构确认']

        merged = detector._merge_coordinator_phase(
            {
                'phase': 'Distribution Phase B (派发区震荡测试)',
                'phase_enum': WyckoffPhase.PHASE_B,
                'phase_description': '[经典威科夫派发特征确认] 波幅收敛...',
            },
            events,
        )
        self.assertEqual(merged['phase'], 'Distribution Phase A')
        self.assertNotIn('波幅收敛', merged.get('phase_description', ''))
        self.assertIn('派发结构确认', merged.get('phase_description', ''))


class TestIsolatedSowPhaseCPlus(unittest.TestCase):
    def test_isolated_sow_in_distribution_is_c_plus(self):
        ident = PhaseIdentifier(
            pd.DataFrame({'Close': [100.0], 'MA200': [90.0]}),
            WyckoffConfig(), WyckoffThresholds(),
        )

        class MockSU:
            type_ = 'sow'
            data = MagicMock(detected=True)

        class MockEvents:
            spring_upthrust = None
            sos_sow = MockSU()
            joc = None
            fti = None
            climax = ClimaxModel(detected=True, type='buying_climax')

        flags = {
            'is_spring': False,
            'is_upthrust': False,
            'is_sos': False,
            'is_sow': True,
            'is_joc': False,
            'is_fti': False,
        }
        result = ident._detect_phase_c_plus_signals(MockEvents(), flags)
        self.assertIsNotNone(result)
        self.assertIn('C+', result[0])
        self.assertIn('FTI', result[0])


class TestSpringWithoutJocWaits(unittest.TestCase):
    def test_spring_only_trading_plan_waits(self):
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
            'phase': 'Accumulation Phase C',
            'spring': {
                'detected': True,
                'latest_spring': {
                    'breakdown_price': 98.0,
                    'support_level': 99.0,
                    'recovery_price': 100.5,
                    'recovery_days': 2,
                    'volume_ratio': 1.5,
                    'lifecycle_status': 'active',
                },
            },
            'joc': {'detected': False},
        }
        plan = engine.generate_trading_plan(data, patterns, {})
        self.assertEqual(plan.direction, '观望')
        self.assertIn('JOC', plan.entry_zone)


class TestChochRequiresPhaseAStructure(unittest.TestCase):
    def test_choch_alone_does_not_create_phase_a(self):
        coord = PhaseCoordinator(MagicMock())
        phase = coord._preliminary_phase_identification(
            climax_res={'detected': False},
            ar_res={'detected': False},
            st_res={'detected': False},
            spring_res={'detected': False},
            upthrust_res={'detected': False},
            ps_res={'detected': False},
            psy_res={'detected': False},
            choch_res={'detected': True, 'direction': 'bullish'},
        )
        self.assertEqual(phase, 'Unknown')

    def test_choch_augments_existing_phase_a(self):
        coord = PhaseCoordinator(MagicMock())
        phase = coord._preliminary_phase_identification(
            climax_res={'detected': True, 'type': 'selling_climax'},
            ar_res={'detected': True},
            st_res={'detected': True},
            spring_res={'detected': False},
            upthrust_res={'detected': False},
            ps_res={'detected': True},
            psy_res={'detected': False},
            choch_res={'detected': True, 'direction': 'up'},
        )
        self.assertIn('Phase A', phase)
        self.assertIn('CHoCH', phase)


class TestClimaxArbitration(unittest.TestCase):
    def test_nearby_sc_bc_prefers_prior_trend(self):
        coord = PhaseCoordinator(MagicMock())
        coord.detector = MagicMock()
        coord.detector.data = pd.DataFrame({'Close': [90.0] * 60})
        coord._detect_prior_trend = MagicMock(return_value='markdown')

        sc = {'detected': True, 'type': 'selling_climax', 'date': '2024-06-01'}
        bc = {'detected': True, 'type': 'buying_climax', 'date': '2024-06-08'}
        result = coord._arbitrate_climax(sc, bc)
        self.assertEqual(result['type'], 'selling_climax')


class TestMinPhaseDuration(unittest.TestCase):
    def test_phase_b_blocks_early_c_transition(self):
        coord = PhaseCoordinator(MagicMock())
        coord.detector = MagicMock()
        coord._calculate_consolidation_duration = MagicMock(return_value=5)

        events = EventsModel(
            trading_range=TradingRangeModel(
                is_consolidation=True, high=50, low=40, range_pct=0.2,
                duration_days=60, position=0.5, current_price=48,
            ),
            spring=SpringModel(detected=True),
        )
        phase, conf = coord._transition_from_phase_b(
            'Accumulation Phase B', events, PhaseTransitionCriteria(),
        )
        self.assertIn('Phase B', phase)
        self.assertLess(conf, 0.7)


class TestPhaseEVolumeConfirmation(unittest.TestCase):
    def test_d_to_e_requires_volume_alignment(self):
        n = 6
        df = pd.DataFrame({
            'Close': [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
            'Volume': [1_000_000, 900_000, 800_000, 700_000, 600_000, 400_000],
        }, index=pd.date_range('2024-01-01', periods=n, freq='B'))
        self.assertFalse(
            continuous_price_confirmation(
                df, 3, 'Accumulation Phase D', require_volume=True,
            )
        )
        self.assertTrue(
            continuous_price_confirmation(
                df, 3, 'Accumulation Phase D', require_volume=False,
            )
        )


class TestPhaseBRequiresStOrTests(unittest.TestCase):
    def test_climax_ar_only_not_phase_b(self):
        n = 80
        df = pd.DataFrame({
            'Open': [100.0] * n,
            'High': [101.0] * n,
            'Low': [99.0] * n,
            'Close': [100.0] * n,
            'Volume': [1_000_000.0] * n,
        }, index=pd.date_range('2024-01-01', periods=n, freq='B'))
        pid = PhaseIdentifier(df, WyckoffConfig(), WyckoffThresholds())

        class MockClimax:
            detected = True
            type = 'selling_climax'

        class MockAR:
            detected = True

        class MockST:
            detected = False

        class MockEvents:
            trading_range = {'is_consolidation': True, 'duration_days': 60}
            lps_list = []
            ut_list = []
            climax = MockClimax()
            automatic_reaction = MockAR()
            secondary_test = MockST()
            vsa_signals = {}

        self.assertIsNone(pid._detect_phase_b_active(MockEvents()))


class TestEventsModelVsaDeadCorner(unittest.TestCase):
    def test_events_model_accepts_vsa_and_dead_corner(self):
        events = EventsModel(
            trading_range=TradingRangeModel(
                is_consolidation=True, high=50, low=40, range_pct=0.2,
                duration_days=60, position=0.5, current_price=48,
            ),
            vsa_menhongtao={'no_supply': {'detected': True}},
            dead_corner_breakout={'detected': False},
        )
        self.assertTrue(events.vsa_menhongtao['no_supply']['detected'])


class TestJocBlockedInDistribution(unittest.TestCase):
    def test_joc_with_bc_and_sow_not_accumulation_phase_d(self):
        ident = PhaseIdentifier(
            pd.DataFrame({'Close': [100.0] * 10, 'Volume': [1e6] * 10}),
            WyckoffConfig(), WyckoffThresholds(),
        )

        class MockEvents:
            climax = ClimaxModel(detected=True, type='buying_climax')
            joc = MagicMock(detected=True, test_detected=False, test_score=0)
            spring_upthrust = None
            sos_sow = MagicMock(type_='sow', data=MagicMock(detected=True))

        flags = {
            'is_spring': False, 'is_upthrust': False, 'is_sos': False,
            'is_sow': True, 'is_joc': True, 'is_fti': False,
        }
        self.assertFalse(ident._is_accumulation_joc_context(MockEvents(), flags))
        result = ident._detect_breakout_phase_d(MockEvents(), flags)
        self.assertIsNone(result)
        c_plus = ident._detect_phase_c_plus_signals(MockEvents(), flags)
        self.assertIsNotNone(c_plus)
        self.assertIn('Distribution', c_plus[0])


if __name__ == '__main__':
    unittest.main()
