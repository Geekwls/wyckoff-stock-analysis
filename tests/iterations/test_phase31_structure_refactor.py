import unittest
import pandas as pd
import numpy as np
from typing import Dict, Any
from wyckoff.schemas import SpringSignalModel, LpsSignalModel, TradingRangeModel, EventsModel
from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.point_and_figure import calculate_cause_effect_from_pnf
from wyckoff.core.detectors.reversal_detector import ReversalDetector
from wyckoff.core.detectors.strength_weakness_detector import StrengthWeaknessDetector
from wyckoff.core.detectors.trading_range_detector import TradingRangeDetector
from wyckoff.core.orchestrator import WyckoffOrchestrator
from wyckoff.core.signal_extractor import SignalExtractor


class MockCache:
    def get_or_compute(self, key, func, *args, **kwargs):
        return func(*args, **kwargs)


class TestPhase31StructureRefactor(unittest.TestCase):
    def _create_base_tr_data(self, length: int = 100, tr_low: float = 90.0, tr_high: float = 110.0, atr: float = 2.0) -> pd.DataFrame:
        """Helper to create standard TR base data"""
        closes = [100.0] * length
        highs = [101.0] * length
        lows = [99.0] * length
        volumes = [1000.0] * length
        atrs = [atr] * length

        # Establish historical TR boundaries (e.g. at index 10 to 50)
        for i in range(10, 50):
            closes[i] = 100.0 if i % 2 == 0 else 98.0
            highs[i] = tr_high
            lows[i] = tr_low

        data = pd.DataFrame({
            'Open': closes,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': volumes,
            'ATR': atrs
        })
        return data

    def test_phase31_schemas_pydantic_backward_compatibility(self):
        # 1. SpringSignalModel extensions verification
        spring_sig = SpringSignalModel(
            breakdown_date="2026-05-24",
            breakdown_price=88.5,
            support_level=90.0,
            recovery_price=91.0,
            recovery_days=3,
            volume_ratio=1.2,
            filter_passed=True,
            classification="confirmed",
            failure_reason=None,
            penetration_pct=1.67,
            recovery_quality=85.0
        )
        self.assertEqual(spring_sig.classification, "confirmed")
        self.assertTrue(spring_sig.filter_passed)
        self.assertEqual(spring_sig.recovery_days, 3)

        # 2. LpsSignalModel extensions verification
        lps_sig = LpsSignalModel(
            price=92.5,
            volume_ratio=0.7,
            support_level=90.0,
            atr=2.0,
            atr_pct=2.16,
            tolerance_pct=3.24,
            matched_anchor="tr_low",
            distance_to_anchor_pct=2.78,
            qualification="formal_lps"
        )
        self.assertEqual(lps_sig.qualification, "formal_lps")
        self.assertEqual(lps_sig.matched_anchor, "tr_low")
        self.assertEqual(lps_sig.price, 92.5)

        # 3. TradingRangeModel extensions verification
        tr_model = TradingRangeModel(
            is_consolidation=True,
            high=110.0,
            low=90.0,
            range_pct=20.0,
            duration_days=60,
            position=0.5,
            current_price=100.0,
            invalidation_level=88.0,
            invalidation_reason="Severe breakdown beyond PNF support",
            invalidation_severity="invalidated",
            transition_period=True,
            transition_reason="Old TR invalid, monitoring for new TR setup"
        )
        self.assertTrue(tr_model.transition_period)
        self.assertEqual(tr_model.invalidation_severity, "invalidated")
        self.assertEqual(tr_model.high, 110.0)

    def test_golden_sample_true_spring(self):
        # Setup data with a true Spring: breakdown by 1.5% and quick 2-day recovery
        data = self._create_base_tr_data(length=80)
        # Breakdown at index 60
        data.loc[60, 'Low'] = 88.5
        data.loc[60, 'Close'] = 88.5
        data.loc[60, 'Volume'] = 600.0  # low volume breakdown (supply exhaustion)
        
        # Recovery at index 62
        data.loc[61, 'Close'] = 89.5
        data.loc[62, 'Close'] = 91.5
        data.loc[62, 'High'] = 91.5
        
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        analysis_cache = MockCache()
        detector = ReversalDetector(data, config, thresholds, analysis_cache)
        res = detector.detect_spring(trading_range={'low': 90.0, 'high': 110.0})
        self.assertTrue(res['detected'])
        sig = res['latest_spring']
        self.assertTrue(sig['filter_passed'])
        self.assertEqual(sig['classification'], 'confirmed')
        self.assertEqual(sig['recovery_days'], 2)

    def test_golden_sample_false_spring_no_recovery(self):
        # Setup data where price breaks down but fails to recover and grinds down
        data = self._create_base_tr_data(length=80)
        data.loc[60, 'Low'] = 88.5
        data.loc[60, 'Close'] = 88.5
        
        # Stays depressed for 10 days
        for j in range(61, 71):
            data.loc[j, 'Close'] = 88.0
            data.loc[j, 'High'] = 88.5
            data.loc[j, 'Low'] = 87.5
            
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        analysis_cache = MockCache()
        detector = ReversalDetector(data, config, thresholds, analysis_cache)
        res = detector.detect_spring(trading_range={'low': 90.0, 'high': 110.0})
        self.assertFalse(res['detected'])
        sigs = res.get('signals', [])
        self.assertTrue(len(sigs) > 0)
        sig = sigs[-1]
        self.assertFalse(sig['filter_passed'])
        self.assertEqual(sig['classification'], 'failed')

    def test_golden_sample_excessive_breakdown_triggering_invalidation(self):
        # Setup data with a massive breakdown (e.g. 8.0% drop, far exceeding 2.5 * ATR)
        data = self._create_base_tr_data(length=80, atr=2.0) # ATR% is 2.0%
        # Breakdown to 80.0 (an 11% drop, way beyond max depth limit)
        data.loc[60, 'Low'] = 80.0
        data.loc[60, 'Close'] = 80.0
        
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        analysis_cache = MockCache()
        detector = ReversalDetector(data, config, thresholds, analysis_cache)
        res = detector.detect_spring(trading_range={'low': 90.0, 'high': 110.0})
        self.assertFalse(res['detected'])
        sigs = res.get('signals', [])
        self.assertTrue(len(sigs) > 0)
        sig = sigs[-1]
        self.assertFalse(sig['filter_passed'])
        self.assertEqual(sig['classification'], 'rejected')

    def test_golden_sample_sc_valid_ar_vs_weak_rebound(self):
        # Setup valid AR: SC low at 90.0, rapid rebound to 98.0 within 3 days (covers > 1.5 * ATR)
        data_valid_ar = self._create_base_tr_data(length=60, atr=2.0)
        data_valid_ar.loc[30, 'Close'] = 90.0  # SC low
        data_valid_ar.loc[31, 'Close'] = 93.0
        data_valid_ar.loc[32, 'Close'] = 96.0
        data_valid_ar.loc[33, 'Close'] = 98.0  # peak rebound
        
        # Setup weak rebound: SC low at 90.0, slow grind rebound of only 0.5 * ATR over 10 days
        data_weak = self._create_base_tr_data(length=60, atr=2.0)
        data_weak.loc[30, 'Close'] = 90.0
        for i in range(31, 46):
            data_weak.loc[i, 'Close'] = 90.0 + (i - 30) * 0.1 # weak slope, max 91.5
            data_weak.loc[i, 'High'] = 90.0 + (i - 30) * 0.1 + 0.5
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        analysis_cache = MockCache()
        
        # Valid AR test
        detector_valid = ReversalDetector(data_valid_ar, config, thresholds, analysis_cache)
        climax_res = {
            'detected': True,
            'type': 'selling_climax',
            'date': data_valid_ar.index[30],
            'price': 90.0,
            'volume': 1000.0
        }
        ar_res_valid = detector_valid.detect_automatic_reaction(climax_res)
        self.assertTrue(ar_res_valid['detected'])
        self.assertEqual(ar_res_valid['quality'], 'strong')
        self.assertIn('reaction_days', ar_res_valid)
        self.assertIn('volume_quality', ar_res_valid)
        self.assertIn('structural_role', ar_res_valid)
        self.assertIn('quality_score', ar_res_valid)
        
        # Weak AR test
        detector_weak = ReversalDetector(data_weak, config, thresholds, analysis_cache)
        climax_res_weak = {
            'detected': True,
            'type': 'selling_climax',
            'date': data_weak.index[30],
            'price': 90.0,
            'volume': 1000.0
        }
        ar_res_weak = detector_weak.detect_automatic_reaction(climax_res_weak)
        self.assertFalse(ar_res_weak['detected'])
        self.assertEqual(ar_res_weak['quality'], 'weak_rebound')

    def test_golden_sample_lps_high_vs_low_volatility(self):
        # High volatility asset (ATR = 5.0). Tolerance = min(8.0, 5.0 * 1.5) = 7.5%
        # Pullback of 5.5% relative to JOC creek should be accepted as formal LPS
        data_high_vol = self._create_mock_data_for_lps(atr=5.0)
        self.assertEqual(len(data_high_vol), 70)
        
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        analysis_cache = MockCache()
        
        detector_high = StrengthWeaknessDetector(data_high_vol, config, thresholds, analysis_cache)
        detector_high.update_analysis_context("accumulation")
        
        phase_a_events = {
            'ps': {'detected': True},
            'climax': {'detected': True, 'type': 'selling_climax'},
            'ar': {'detected': True},
            'st': {'detected': True}
        }
        detector_high.set_phase_a_events(phase_a_events)
        
        joc_result = {
            'detected': True,
            'latest': {
                'creek_level': 100.0,
                'date': '2026-05-01'
            }
        }
        
        res_high = detector_high.detect_lps(
            joc_result=joc_result,
            trading_range={'low': 90.0, 'high': 110.0}
        )
        self.assertTrue(res_high['detected'])
        self.assertEqual(res_high['latest_formal']['qualification'], 'formal_lps')
        self.assertEqual(res_high['latest_formal']['matched_anchor'], 'joc_creek')
        self.assertAlmostEqual(res_high['latest_formal']['distance_to_anchor_pct'], 5.5)

        # Low volatility asset (ATR = 1.0). Tolerance = min(8.0, 1.0 * 1.5) = 2.0%
        # Pullback of 5.5% should be rejected/degraded from formal LPS (too deep)
        data_low_vol = self._create_mock_data_for_lps(atr=1.0)
        self.assertEqual(len(data_low_vol), 70)
        
        detector_low = StrengthWeaknessDetector(data_low_vol, config, thresholds, analysis_cache)
        detector_low.update_analysis_context("accumulation")
        detector_low.set_phase_a_events(phase_a_events)
        
        res_low = detector_low.detect_lps(
            joc_result=joc_result,
            trading_range={'low': 90.0, 'high': 110.0}
        )
        # Low volatility pullback is outside the 2.0% tolerance, so no formal LPS is matched
        self.assertFalse(res_low['detected'])

    def _create_mock_data_for_lps(self, atr: float) -> pd.DataFrame:
        length = 70
        closes = [100.0] * length
        highs = [101.0] * length
        lows = [90.0] * length
        volumes = [50.0] * length
        
        # Setup pre-existing low at index 20 so higher_low condition holds
        lows[20] = 80.0
        
        # Setup standard JOC breakout at index 40-45 with high volume
        for i in range(40, 46):
            closes[i] = 110.0
            highs[i] = 112.0
            lows[i] = 108.0
            volumes[i] = 2000.0
            
        # Pullback at index 65
        # Low is 94.5, which is a -5.5% pullback relative to JOC creek (100.0)
        lows[65] = 94.5
        closes[65] = 101.0
        volumes[65] = 10.0  # very low volume for volume validation
        
        data = pd.DataFrame({
            'Open': closes,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': volumes,
            'ATR': [atr] * length
        })
        data.index = pd.date_range(start='2026-04-01', periods=length)
        return data

    def test_golden_sample_tr_invalidation_and_trading_plan(self):
        # 1. Setup a broken TR (downward breakdown)
        data = self._create_base_tr_data(length=80, atr=2.0)
        # Breakdown to 80.0 (a severe breakdown) at the very last bar (index 79)
        data.loc[79, 'Low'] = 80.0
        data.loc[79, 'Close'] = 80.0
        data.loc[79, 'Volume'] = 3000.0  # high volume breakdown
        
        config = WyckoffConfig()
        detector = TradingRangeDetector(data, config)
        tr_res = detector.detect()
        
        # Verify TradingRangeDetector populated invalidation fields correctly
        self.assertTrue(tr_res['is_broken'])
        self.assertTrue(tr_res['transition_period'])
        self.assertEqual(tr_res['invalidation_severity'], 'distribution_risk')
        self.assertEqual(tr_res['invalidation_level'], tr_res['low'])
        
        # 2. Test TradingPlanGenerator.generate
        from wyckoff.core.trading_plan_generator import TradingPlanGenerator
        class MockDetector:
            def __init__(self, tr_res):
                self.tr_res = tr_res
            def detect_trading_range(self):
                return self.tr_res
            def identify_phase(self):
                return {'phase': 'Distribution Phase D', 'events_detected': {'trading_range': self.tr_res}}
                
        mock_pd = MockDetector(tr_res)
        plan_gen = TradingPlanGenerator(data, mock_pd)
        plan_res = plan_gen.generate(phase_str="Distribution Phase D")
        
        self.assertEqual(plan_res['direction'], '观望')
        self.assertEqual(plan_res['entry_zone'], '过渡期观察，等待新区间')
        self.assertEqual(plan_res['position_sizing']['conservative'], '0%')
        self.assertEqual(plan_res['targets']['target_1']['value'], 0.0)
        
        # 3. Test RecommendationEngine.generate_trading_plan
        from wyckoff.core.recommendation_engine import RecommendationEngine
        rec_engine = RecommendationEngine(config)
        patterns = {
            'phase': 'Distribution Phase D',
            'events_detected': {
                'trading_range': tr_res
            }
        }
        rec_plan = rec_engine.generate_trading_plan(data, patterns, {})
        self.assertEqual(rec_plan.direction, '观望')
        self.assertEqual(rec_plan.entry_zone, '过渡期观察，等待新区间')
        self.assertEqual(rec_plan.position_sizing.conservative, '0%')
        self.assertEqual(rec_plan.targets.target_1, 0.0)

    def test_transition_period_blocks_tr_dependent_detectors_and_targets(self):
        data = self._create_base_tr_data(length=80, atr=2.0)
        data.loc[60, 'Low'] = 88.5
        data.loc[60, 'Close'] = 88.5
        data.loc[62, 'Close'] = 91.5

        transition_tr = {
            'low': 90.0,
            'high': 110.0,
            'transition_period': True,
            'invalidation_severity': 'invalidated',
            'transition_reason': 'old TR invalid, waiting for new TR',
        }
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        analysis_cache = MockCache()

        reversal = ReversalDetector(data, config, thresholds, analysis_cache)
        spring_res = reversal.detect_spring(trading_range=transition_tr)
        self.assertFalse(spring_res['detected'])
        self.assertEqual(spring_res['reason'], 'transition_period_no_spring')

        sw = StrengthWeaknessDetector(data, config, thresholds, analysis_cache)
        lps_res = sw.detect_lps(
            joc_result={'detected': True, 'creek_level': 100.0, 'date': data.index[55]},
            trading_range=transition_tr,
        )
        self.assertFalse(lps_res['detected'])
        self.assertEqual(lps_res['reason'], 'transition_period_no_lps')

        from wyckoff.core.orchestrator import WyckoffOrchestrator
        orch = WyckoffOrchestrator()
        class MockDetector:
            def __init__(self, frame):
                self.data = frame
            def detect_trading_range(self):
                return transition_tr

        targets = orch._calculate_targets(
            MockDetector(data),
            {'phase': 'Accumulation Phase C', 'events_detected': {'trading_range': transition_tr}},
        )
        self.assertEqual(targets['method'], 'transition_period')
        self.assertEqual(targets['target_1'], 0.0)


if __name__ == '__main__':
    unittest.main()
