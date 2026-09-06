import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.wyckoff.config.settings import WyckoffConfig
from src.wyckoff.core.enums import MarketEnvironment
from src.wyckoff.core.point_and_figure import calculate_cause_effect_from_pnf
from src.wyckoff.core.trading_plan_generator import TradingPlanGenerator
from src.wyckoff.core.recommendation_engine import RecommendationEngine
from src.wyckoff.core.signal_extractor import SignalExtractor
from src.wyckoff.schemas import TradingPlanModel, StopLossModel, TargetsModel, PositionSizingModel


class MockPatternDetector:
    def __init__(self, tr_high=110.0, tr_low=90.0, phase="Accumulation Phase D (SOS / JOC 跨越小溪)", events=None, invalidated=False):
        self.tr_high = tr_high
        self.tr_low = tr_low
        self.phase_str = phase
        self.invalidated = invalidated
        self.events = events or {
            'trading_range': {'high': tr_high, 'low': tr_low, 'detected': True, 'invalidated_tr': invalidated},
            'joc': {'detected': True, 'creek_level': 105.0},
            'lps': {'detected': True, 'price': 104.0, 'valid': True, 'is_formal': True},
            'spring': {'detected': True, 'price': 89.0, 'low': 89.0},
            'sos': {'detected': True, 'price': 106.0},
        }

    def detect_trading_range(self):
        return {
            'high': self.tr_high,
            'low': self.tr_low,
            'detected': True,
            'transition_period': self.invalidated,
            'invalidated_tr': self.invalidated
        }

    def identify_phase(self):
        return {
            'phase': self.phase_str,
            'confidence': 0.85,
            'events_detected': self.events
        }


class TestPhase33StrategyEvolution(unittest.TestCase):
    def setUp(self):
        # 构造震荡交易区 100 根 K 线（提供丰富的 P&F 箱体反转）
        base_cycle = [100.0, 105.0, 96.0, 104.0, 97.0, 106.0, 95.0, 103.0, 98.0, 107.0]
        closes = np.tile(base_cycle, 10)
        length = len(closes)
        dates = pd.date_range(start='2026-01-01', periods=length, freq='D')
        highs = closes + 1.5
        lows = closes - 1.5
        vols = np.full(length, 50000.0)
        atrs = np.full(length, 2.5)

        self.df = pd.DataFrame({
            'Open': closes,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': vols,
            'ATR': atrs,
            'MA20': closes,
            'MA50': closes - 1.0,
            'MA200': closes - 3.0,
        }, index=dates)

    def test_trading_plan_model_backward_compatibility(self):
        """测试 TradingPlanModel 对新增字段的向后兼容性"""
        base_plan = TradingPlanModel(
            direction="做多",
            entry_zone="100.0 - 102.0",
            stop_loss=StopLossModel(conservative=95.0, aggressive=98.0),
            targets=TargetsModel(target_1=115.0, target_2=125.0),
            position_sizing=PositionSizingModel(conservative="20%", moderate="40%", aggressive="60%"),
            holding_period="中期（2-8周）"
        )
        self.assertIsNone(base_plan.scale_in_plan)
        self.assertIsNone(base_plan.trailing_stop_plan)
        self.assertIsNone(base_plan.sector_synergy)

        # 包含新增字段时亦可正常解析
        scale_in = {"stage_1_pilot": {"weight": "25%"}}
        trailing_stop = {"stage_1_initial": {"stop_price": 95.0}}
        synergy = {"state": "HEALTHY_MAINLINE", "name": "半导体"}

        evolved_plan = TradingPlanModel(
            direction="做多",
            entry_zone="100.0 - 102.0",
            stop_loss=StopLossModel(conservative=95.0, aggressive=98.0),
            targets=TargetsModel(target_1=115.0, target_2=125.0),
            position_sizing=PositionSizingModel(conservative="20%", moderate="40%", aggressive="60%"),
            holding_period="中期（2-8周）",
            scale_in_plan=scale_in,
            trailing_stop_plan=trailing_stop,
            sector_synergy=synergy
        )
        self.assertEqual(evolved_plan.scale_in_plan, scale_in)
        self.assertEqual(evolved_plan.trailing_stop_plan, trailing_stop)
        self.assertEqual(evolved_plan.sector_synergy, synergy)

    def test_scale_in_plan_and_trailing_stop_in_trading_plan_generator(self):
        """测试 TradingPlanGenerator 生成三段式金字塔建仓与阶梯跟踪止损"""
        detector = MockPatternDetector()
        generator = TradingPlanGenerator(self.df, detector)
        plan = generator.generate(is_a_stock=True)

        self.assertEqual(plan['direction'], "做多")
        scale_in = plan.get('scale_in_plan')
        self.assertIsNotNone(scale_in)
        self.assertIn('stage_1_pilot', scale_in)
        self.assertIn('stage_2_confirmation', scale_in)
        self.assertIn('stage_3_trend_addition', scale_in)
        self.assertIn('20%-30%', scale_in['stage_1_pilot']['weight'])
        self.assertIn('30%-40%', scale_in['stage_2_confirmation']['weight'])

        trailing_stop = plan.get('trailing_stop_plan')
        self.assertIsNotNone(trailing_stop)
        self.assertIn('stage_1_initial', trailing_stop)
        self.assertIn('stage_2_breakeven', trailing_stop)
        self.assertIn('stage_3_lps_protection', trailing_stop)
        self.assertIn('stage_4_trend_trailing', trailing_stop)
        self.assertEqual(trailing_stop['stage_2_breakeven']['stop_price'], 105.0)

    def test_point_and_figure_dual_target_projection(self):
        """测试 P&F 双重目标测算：保守 Semi-Count 与 宏观 Full-Count"""
        res = calculate_cause_effect_from_pnf(self.df, known_tr_high=110.0, known_tr_low=90.0, phase="Phase D")

        self.assertIn('horizontal_count', res)
        self.assertIn('semi_count', res)
        self.assertIn('targets', res)
        self.assertIn('semi_targets', res)

        h_count = res['horizontal_count']
        semi_count = res['semi_count']
        self.assertGreaterEqual(h_count, semi_count)
        self.assertGreaterEqual(semi_count, 3)

        targets = res['targets']
        semi_targets = res['semi_targets']
        # 做多目标必须高于突破基准价，且宏观目标应大于或等于保守半程目标
        self.assertGreater(semi_targets['target_1'], 110.0)
        self.assertGreaterEqual(targets['target_1'], semi_targets['target_1'])
        self.assertGreater(targets['target_2'], targets['target_1'])

    def test_sector_synergy_resonance_and_veto(self):
        """测试板块共振赋能加分与退潮风险一票否决"""
        engine = RecommendationEngine(WyckoffConfig())

        detector = MockPatternDetector()
        pattern_res = detector.identify_phase()

        # 1. 行业处于主线推进，获得共振加分
        pattern_res['sector_state'] = {'state': 'HEALTHY_MAINLINE', 'name': '算力硬件'}
        quality = engine.calculate_weighted_score(self.df, pattern_res, MarketEnvironment.BULL)
        self.assertTrue(any("板块共振加成" in r for r in quality.reasons))
        self.assertGreaterEqual(quality.score, 60)

        # 2. 行业处于退潮派发风险，做多触发一票否决
        pattern_res['sector_state'] = {'state': 'DISTRIBUTION_RISK', 'name': '消费电子'}
        plan_model = engine.generate_trading_plan(self.df, pattern_res, {'target_1': 120.0, 'target_2': 130.0})
        self.assertEqual(plan_model.direction, "观望")
        self.assertIn("退潮派发风险", plan_model.entry_zone)

        # 3. 验证 TradingPlanGenerator 中的板块退潮否决
        generator = TradingPlanGenerator(self.df, detector)
        plan_dict = generator.generate(sector_state={'state': 'DISTRIBUTION_RISK', 'name': '白酒'})
        self.assertEqual(plan_dict['direction'], "观望")
        self.assertIn("退潮派发", plan_dict['entry_zone'])
        self.assertEqual(plan_dict['position_sizing']['moderate'], "0%")

    def test_signal_aging_decay(self):
        """测试信号生命周期与时效性衰减"""
        today = datetime.now()

        # 1. 刚发生的信号（5天前），处于有效窗口，衰减系数高
        fresh_event = {'detected': True, 'price': 100.0, 'date': (today - timedelta(days=5)).strftime('%Y-%m-%d')}
        fresh_aging = SignalExtractor.calculate_signal_aging(fresh_event, reference_date=today)
        self.assertFalse(fresh_aging['is_stale'])
        self.assertGreater(fresh_aging['decay_factor'], 0.7)

        # 2. 陈旧信号（40天前），超过 30 天活跃窗口，进入滞留衰减期
        stale_event = {'detected': True, 'price': 100.0, 'date': (today - timedelta(days=40)).strftime('%Y-%m-%d')}
        stale_aging = SignalExtractor.calculate_signal_aging(stale_event, reference_date=today)
        self.assertTrue(stale_aging['is_stale'])
        self.assertLess(stale_aging['decay_factor'], 0.3)


if __name__ == '__main__':
    unittest.main()
