"""
突破分析器测试用例

测试BreakoutAnalyzer的突破质量评估和Upthrust识别功能
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from wyckoff.core.breakout_analyzer import BreakoutAnalyzer


class TestBreakoutAnalyzer:
    """突破分析器测试"""

    @pytest.fixture
    def sample_data_with_upside_breakout(self):
        """创建包含向上突破的测试数据"""
        dates = pd.date_range(start='2025-01-01', periods=100, freq='D')

        # 创建价格数据：区间震荡后向上突破
        prices = []
        volumes = []

        # 前60天：区间震荡（40-50元）
        for i in range(60):
            base_price = 45
            noise = np.random.randn() * 2
            prices.append(base_price + noise)
            volumes.append(1000000 + np.random.randn() * 200000)

        # 后40天：向上突破（到60元）
        for i in range(40):
            base_price = 50 + i * 0.25  # 逐步上涨
            noise = np.random.randn() * 1
            prices.append(base_price + noise)
            # 突破时放量
            if i < 5:  # 突破前几天
                volumes.append(1000000 * 2.0)  # 放量
            else:
                volumes.append(1000000 + np.random.randn() * 200000)

        df = pd.DataFrame({
            'Open': [p * 0.99 for p in prices],
            'High': [p * 1.02 for p in prices],
            'Low': [p * 0.98 for p in prices],
            'Close': prices,
            'Volume': volumes
        }, index=dates)

        # 添加20日成交量均值
        df['Volume_MA20'] = df['Volume'].rolling(20).mean()

        return df

    @pytest.fixture
    def sample_data_with_upthrust(self):
        """创建包含Upthrust（假突破）的测试数据"""
        dates = pd.date_range(start='2025-01-01', periods=100, freq='D')

        rng = np.random.default_rng(42)  # 固定随机种子，确保测试可重复性

        prices = []
        volumes = []

        # 前60天：区间震荡（40-50元）
        for i in range(60):
            base_price = 45
            noise = rng.standard_normal() * 2
            prices.append(base_price + noise)
            volumes.append(1000000 + rng.standard_normal() * 100000)  # 均值约100万

        # 后5天：快速冲高（到55元），严格缩量（0.3x均量）确保is_adequate=False
        for i in range(5):
            base_price = 50 + i * 1
            noise = rng.standard_normal() * 0.5
            prices.append(base_price + noise)
            volumes.append(300000)  # 严格缩量：0.3x，确保量比 < 1.2

        # 后35天：快速回落
        for i in range(35):
            base_price = 55 - i * 0.3  # 逐步回落
            noise = rng.standard_normal() * 1
            prices.append(base_price + noise)
            volumes.append(1000000 + rng.standard_normal() * 100000)

        df = pd.DataFrame({
            'Open': [p * 0.99 for p in prices],
            'High': [p * 1.02 for p in prices],
            'Low': [p * 0.98 for p in prices],
            'Close': prices,
            'Volume': volumes
        }, index=dates)

        df['Volume_MA20'] = df['Volume'].rolling(20).mean()

        return df


    @pytest.fixture
    def analyzer(self, sample_data_with_upside_breakout):
        """创建分析器实例"""
        return BreakoutAnalyzer(sample_data_with_upside_breakout)

    def test_no_breakout(self, analyzer):
        """测试未突破的情况"""
        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': False
        }

        result = analyzer.analyze_breakout(trading_range)

        assert result['is_breakout'] is False
        assert 'reason' in result

    def test_upside_breakout_detection(self, sample_data_with_upside_breakout):
        """测试向上突破检测"""
        analyzer = BreakoutAnalyzer(sample_data_with_upside_breakout)

        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'up',
            'current_price': 60.0
        }

        result = analyzer.analyze_breakout(trading_range)

        assert result['is_breakout'] is True
        assert result['direction'] == 'up'
        assert result['quality'] in ['strong', 'moderate', 'weak']

    def test_upthrust_detection(self, sample_data_with_upthrust):
        """测试Upthrust（假突破）识别"""
        analyzer = BreakoutAnalyzer(sample_data_with_upthrust)

        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'up',
            'current_price': 25.0  # 已深度回落，触发severe drawdown
        }

        result = analyzer.analyze_breakout(trading_range)

        assert result['is_breakout'] == True
        assert result.get('is_upthrust') == True

    def test_volume_analysis(self, sample_data_with_upside_breakout):
        """测试成交量分析"""
        analyzer = BreakoutAnalyzer(sample_data_with_upside_breakout)

        # 找到突破点
        tr_high = 50.0
        breakout_data = sample_data_with_upside_breakout[
            sample_data_with_upside_breakout['Close'] > tr_high
        ]

        if len(breakout_data) > 0:
            breakout_point = breakout_data.index[0]
            breakout_bar = sample_data_with_upside_breakout.loc[breakout_point]

            vol_analysis = analyzer._analyze_breakout_volume(breakout_bar, tr_high)

            assert 'volume_ratio' in vol_analysis
            assert 'strength' in vol_analysis
            assert 'signal' in vol_analysis
            assert vol_analysis['volume_ratio'] > 0

    def test_pullback_analysis(self, sample_data_with_upside_breakout):
        """测试回测行为分析"""
        analyzer = BreakoutAnalyzer(sample_data_with_upside_breakout)

        tr_high = 50.0
        breakout_data = sample_data_with_upside_breakout[
            sample_data_with_upside_breakout['Close'] > tr_high
        ]

        if len(breakout_data) > 0:
            breakout_point = breakout_data.index[0]
            pullback_analysis = analyzer._analyze_pullback(breakout_point, tr_high)

            assert 'has_pullback' in pullback_analysis
            assert 'interpretation' in pullback_analysis

    def test_override_recommendation_upside(self, sample_data_with_upside_breakout):
        """向上突破不再自动覆盖派发阶段，须 JOC/结构确认（Phase 14+）"""
        analyzer = BreakoutAnalyzer(sample_data_with_upside_breakout)

        current_phase = "Distribution Phase A"
        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'up',
            'current_price': 60.0
        }

        breakout_analysis = analyzer.analyze_breakout(trading_range)

        if not breakout_analysis.get('is_upthrust', False):
            new_phase, reason, conf_adjust = analyzer.get_override_recommendation(
                trading_range, current_phase
            )

            assert new_phase == current_phase
            assert 'Distribution' in new_phase
            assert 'JOC' in reason or '再积累' in reason
            assert conf_adjust < 1.0

    def test_override_recommendation_downside(self):
        """测试向下突破的覆盖建议（吸筹→下跌）"""
        dates = pd.date_range(start='2025-01-01', periods=60, freq='D')

        # 创建向下突破数据
        prices = [50 - i * 0.2 for i in range(60)]  # 从50元跌到38元
        volumes = [1000000] * 60

        df = pd.DataFrame({
            'Open': [p * 1.01 for p in prices],
            'High': [p * 1.02 for p in prices],
            'Low': [p * 0.98 for p in prices],
            'Close': prices,
            'Volume': volumes
        }, index=dates)

        df['Volume_MA20'] = df['Volume'].rolling(20).mean()

        analyzer = BreakoutAnalyzer(df)

        current_phase = "Accumulation Phase A"
        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'down',
            'current_price': 38.0
        }

        breakout_analysis = analyzer.analyze_breakout(trading_range)
        new_phase, reason, conf_adjust = analyzer.get_override_recommendation(
            trading_range, current_phase
        )

        # 向下突破应该否决吸筹判断
        assert 'Accumulation' not in new_phase
        assert 'Markdown' in new_phase or 'Trending Down' in new_phase
        assert conf_adjust < 1.0

    def test_breakout_quality_scoring(self, sample_data_with_upside_breakout):
        """测试突破质量评分"""
        analyzer = BreakoutAnalyzer(sample_data_with_upside_breakout)

        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'up',
            'current_price': 60.0
        }

        result = analyzer.analyze_breakout(trading_range)

        assert 'quality_score' in result
        assert 0 <= result['quality_score'] <= 100
        assert result['quality'] in ['strong', 'moderate', 'weak', 'very_weak']

    def test_weak_volume_breakout(self):
        """测试缩量突破（Upthrust特征）"""
        dates = pd.date_range(start='2025-01-01', periods=50, freq='D')

        # 创建缩量突破数据
        prices = [45] * 30 + [52] * 20  # 突破到52元
        volumes = [1000000] * 30 + [500000] * 20  # 缩量突破

        df = pd.DataFrame({
            'Open': [p * 0.99 for p in prices],
            'High': [p * 1.02 for p in prices],
            'Low': [p * 0.98 for p in prices],
            'Close': prices,
            'Volume': volumes
        }, index=dates)

        df['Volume_MA20'] = df['Volume'].rolling(20).mean()

        analyzer = BreakoutAnalyzer(df)

        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'up',
            'current_price': 52.0
        }

        result = analyzer.analyze_breakout(trading_range)

        # 缩量突破应该被标记为弱突破
        assert result['volume_analysis']['strength'] in ['weak', 'very_weak']
        # is_adequate只在向上突破且量比>=1.2时为True
        # 缩量突破（量比0.5）应该is_adequate=False
        assert result['volume_analysis']['volume_ratio'] < 1.2
        # 因此is_adequate应该是False（对于向上突破）
        assert result['volume_analysis']['is_adequate'] == False

    def test_strong_volume_breakout(self):
        """测试放量突破（真突破特征）"""
        dates = pd.date_range(start='2025-01-01', periods=50, freq='D')

        # 创建放量突破数据
        prices = [45] * 30 + [55] * 20  # 突破到55元
        volumes = [1000000] * 30 + [3000000] * 20  # 放量突破

        df = pd.DataFrame({
            'Open': [p * 0.99 for p in prices],
            'High': [p * 1.02 for p in prices],
            'Low': [p * 0.98 for p in prices],
            'Close': prices,
            'Volume': volumes
        }, index=dates)

        df['Volume_MA20'] = df['Volume'].rolling(20).mean()

        analyzer = BreakoutAnalyzer(df)

        trading_range = {
            'low': 40.0,
            'high': 50.0,
            'is_broken': True,
            'breakout_direction': 'up',
            'current_price': 55.0
        }

        result = analyzer.analyze_breakout(trading_range)

        # 放量突破应该被标记为强突破
        assert result['volume_analysis']['strength'] in ['strong', 'very_strong']
        # 向上突破量比3.0x >= 1.2，应该是adequate
        assert result['volume_analysis']['volume_ratio'] >= 1.5
        assert result['volume_analysis']['is_adequate'] == True
