"""Phase 23：派发 Phase A/B 中文格式 + 审查结案"""
import unittest

from wyckoff.core.utils import PhaseAdapter
from wyckoff.core.recommendation_engine import RecommendationEngine
import pandas as pd


class TestDistributionEarlyPhaseFormats(unittest.TestCase):
    def test_chinese_phase_a_b_recognized(self):
        cases = [
            "派发阶段A",
            "派发阶段B",
            "派发 Phase A",
            "DISTRIBUTION PHASE A/B",
            "Distribution 阶段 B (买盘衰竭)",
        ]
        for phase in cases:
            with self.subTest(phase=phase):
                self.assertTrue(
                    PhaseAdapter.is_distribution_early(phase),
                    f"{phase} should be distribution early",
                )

    def test_phase_c_not_early(self):
        self.assertFalse(PhaseAdapter.is_distribution_early("Distribution Phase C"))

    def test_trading_plan_intercepts_chinese_early_dist(self):
        engine = RecommendationEngine()
        data = pd.DataFrame({
            'Open': [100.0, 100.0],
            'High': [100.0, 100.0],
            'Low': [100.0, 100.0],
            'Close': [100.0, 108.0],
            'Volume': [1000, 1000],
        })
        patterns = {
            'phase': '派发阶段A',
            'upthrust': {'detected': True},
            'sow': {'detected': True},
        }
        plan = engine.generate_trading_plan(data, patterns, {'target_1': 95.0})
        self.assertEqual(plan.direction, '观望')
