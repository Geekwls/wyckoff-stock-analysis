"""Phase 10：架构收尾 — Spring 类型 / SOW 对称 / LPS-JOC / 阶段合并"""
import unittest
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.phase_coordinator import PhaseCoordinator, PhaseTransitionCriteria
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.schemas import (
    ClimaxModel,
    EventsModel,
    JocModel,
    LpsModel,
    LpsyModel,
    SpringModel,
    SosModel,
    SowModel,
    TradingRangeModel,
    WyckoffEventModel,
)


class TestSpringTypeMapping(unittest.TestCase):
    def test_meng_type_3_is_phase_c(self):
        phase = PhaseCoordinator._phase_from_spring_signal({'spring_type': 3})
        self.assertIn('Phase C', phase)

    def test_meng_type_1_is_phase_b(self):
        phase = PhaseCoordinator._phase_from_spring_signal({'spring_type': 1})
        self.assertIn('Phase B', phase)

    def test_failed_spring_is_observation(self):
        phase = PhaseCoordinator._phase_from_spring_signal({
            'spring_type': 3, 'lifecycle_status': 'failed',
        })
        self.assertIn('失效', phase)


class TestScOnlyTightening(unittest.TestCase):
    def test_sc_only_not_formal_phase_a(self):
        coord = PhaseCoordinator(MagicMock())
        phase = coord._preliminary_phase_identification(
            climax_res={'detected': True, 'type': 'selling_climax'},
            ar_res={'detected': False},
            st_res={'detected': False},
            spring_res={'detected': False},
            upthrust_res={'detected': False},
            ps_res={'detected': True},
            psy_res={'detected': False},
        )
        self.assertIn('SC待AR确认', phase)


class TestLpsWithoutJoc(unittest.TestCase):
    def _events_with_lps(self) -> EventsModel:
        return EventsModel(
            trading_range=TradingRangeModel(
                is_consolidation=True, high=50, low=40, range_pct=0.2,
                duration_days=60, position=0.5, current_price=48,
            ),
            climax=ClimaxModel(detected=True, type='buying_climax'),
            lps=LpsModel(detected=True),
            joc=JocModel(detected=False),
        )

    def test_lps_without_joc_not_phase_d(self):
        from wyckoff.core.enums import WyckoffPhase
        ident = PhaseIdentifier(
            pd.DataFrame({'Close': [100.0], 'MA200': [90.0]}),
            WyckoffConfig(), WyckoffThresholds(),
        )
        events = self._events_with_lps()
        phase, enum, _ = ident._check_logical_consistency(
            events,
            'Distribution Phase C',
            WyckoffPhase.PHASE_C,
            0.7,
        )
        self.assertNotIn('Phase D', phase)
        self.assertIn('JOC', phase)


class TestCToDHardConstraint(unittest.TestCase):
    def _base_events(self, **kwargs) -> EventsModel:
        defaults = dict(
            trading_range=TradingRangeModel(
                is_consolidation=True, high=50, low=40, range_pct=0.2,
                duration_days=60, position=0.5, current_price=48,
            ),
            climax=ClimaxModel(detected=True, type='selling_climax'),
        )
        defaults.update(kwargs)
        return EventsModel(**defaults)

    def test_lps_alone_does_not_transition_to_d(self):
        coord = PhaseCoordinator(MagicMock())
        events = self._base_events(lps=LpsModel(detected=True))
        phase, _ = coord._transition_from_phase_c(
            'Accumulation Phase C', events, PhaseTransitionCriteria(),
        )
        self.assertIn('Phase C', phase)

    def test_joc_transitions_to_d(self):
        coord = PhaseCoordinator(MagicMock())
        events = self._base_events(joc=JocModel(detected=True))
        phase, conf = coord._transition_from_phase_c(
            'Accumulation Phase C', events, PhaseTransitionCriteria(),
        )
        self.assertIn('Phase D', phase)
        self.assertGreaterEqual(conf, 0.85)


class TestSowAloneWatch(unittest.TestCase):
    def test_isolated_sow_yields_watch(self):
        data = pd.DataFrame({
            'Open': [50.0] * 40,
            'High': [51.0] * 40,
            'Low': [49.0] * 40,
            'Close': [50.5] * 40,
            'Volume': [1_000_000] * 40,
        })
        events = {
            'sow': {'detected': True, 'price': 48.0, 'date': '2024-06-01'},
            'spring': {'detected': False},
            'joc': {'detected': False},
            'fti': {'detected': False},
            'upthrust': {'detected': False},
            'sos': {'detected': False},
            'utad': {'detected': False},
            'trading_range': {'detected': False},
        }
        plan = RecommendationEngine(WyckoffConfig()).generate_trading_plan(data, events, {})
        self.assertEqual(plan.direction, '观望')
        self.assertIn('SOW', plan.entry_zone)


class TestFailedSpringPrimarySignal(unittest.TestCase):
    def test_failed_spring_skipped_in_primary_signal(self):
        events = {
            'spring': {
                'detected': True,
                'latest_spring': {
                    'lifecycle_status': 'failed',
                    'breakdown_date': '2024-01-01',
                    'breakdown_price': 38.0,
                    'support_level': 40.0,
                    'recovery_price': 41.0,
                    'recovery_days': 2,
                    'volume_ratio': 1.5,
                },
            },
            'sos': {'detected': True, 'price': 52.0},
        }
        sig, direction = SignalExtractor.resolve_primary_signal({'events_detected': events})
        self.assertEqual(sig, 'sos')
        self.assertEqual(direction, 'long')


class TestMergeCoordinatorPhase(unittest.TestCase):
    def test_arbitration_override_applied(self):
        from wyckoff.core.pattern_detector import WyckoffPatternDetector

        detector = WyckoffPatternDetector.__new__(WyckoffPatternDetector)
        events = MagicMock()
        events.coordinator_final_phase = 'Distribution Phase C'
        events.phase_revision_log = ['[事件仲裁] LPSY 主导']

        merged = detector._merge_coordinator_phase(
            {'phase': 'Accumulation Phase C', 'phase_enum': None},
            events,
        )
        self.assertEqual(merged['phase'], 'Distribution Phase C')
        self.assertEqual(merged['phase_source'], 'coordinator')
        self.assertEqual(merged['identifier_phase'], 'Accumulation Phase C')


if __name__ == '__main__':
    unittest.main()
