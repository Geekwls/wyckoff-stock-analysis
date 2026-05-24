"""
事件仲裁器测试用例

测试 EventArbitrator 的各种场景：
1. Spring vs LPSY 仲裁
2. 时间顺序判断
3. 信号强度评估
4. 边界情况
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from wyckoff.core.event_arbitrator import EventArbitrator
from wyckoff.schemas import (
    ArbitrationResult,
    ArbitrationSignal,
    SpringModel,
    SpringSignalModel,
    LpsyModel,
    LpsySignalModel
)


class TestEventArbitrator:
    """事件仲裁器测试"""

    @pytest.fixture
    def sample_data(self):
        """创建测试用的价格数据"""
        dates = pd.date_range(start='2026-01-01', periods=100, freq='D')
        df = pd.DataFrame({
            'Open': 100,
            'High': 105,
            'Low': 95,
            'Close': 102,
            'Volume': 1000000
        }, index=dates)
        return df

    @pytest.fixture
    def arbitrator(self, sample_data):
        """创建仲裁器实例"""
        return EventArbitrator(sample_data)

    def test_no_conflict_single_signal(self, arbitrator):
        """测试单一信号，无冲突"""
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 3, 24),
                        breakdown_date=datetime(2026, 3, 24),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=2,
                        volume_ratio=2.5,
                        strength='strong'
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)

        assert result.has_conflict is False
        assert result.dominant_signal is not None
        assert result.dominant_signal.signal_type == 'spring'
        assert len(result.conflicting_signals) == 0
        assert "无信号冲突" in result.arbitration_reason

    def test_no_signals(self, arbitrator):
        """测试无信号的情况"""
        events = {
            'spring': SpringModel(detected=False),
            'lpsy': LpsyModel(detected=False)
        }

        result = arbitrator.arbitrate(events)

        assert result.has_conflict is False
        assert result.dominant_signal is None or result.dominant_signal.signal_type == ''
        assert "无有效信号" in result.arbitration_reason

    def test_spring_vs_lpsy_spring_older(self, arbitrator):
        """
        测试 Spring vs LPSY：Spring 较旧

        场景：
        - Spring 出现在 2026-03-24
        - LPSY 出现在 2026-05-10（47天后）
        - 预期：LPSY 主导，Spring 失效
        """
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 3, 24),
                        breakdown_date=datetime(2026, 3, 24),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=3,
                        volume_ratio=2.0,
                        strength='normal'
                    )
                ]
            ),
            'lpsy': LpsyModel(
                detected=True,
                signals=[
                    LpsySignalModel(
                        date=datetime(2026, 5, 10),
                        price=102.0,
                        volume_ratio=1.8,
                        resistance_level=103.0
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)

        assert result.has_conflict is True
        assert len(result.conflicting_signals) == 2
        assert result.dominant_signal.signal_type == 'lpsy'
        assert len(result.rejected_signals) == 1
        assert result.rejected_signals[0].signal_type == 'spring'
        assert "47天" in result.arbitration_reason or "30" in result.arbitration_reason
        assert result.suggested_phase == "Distribution Phase D"
        assert result.confidence_adjustment < 1.0

    def test_spring_vs_lpsy_short_time_gap(self, arbitrator):
        """
        测试 Spring vs LPSY：时间间隔短（<7天）

        场景：
        - Spring 出现在 2026-05-01
        - LPSY 出现在 2026-05-05（4天后）
        - 预期：Spring 仍然有效，LPSY 可能是假信号
        """
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 5, 1),
                        breakdown_date=datetime(2026, 5, 1),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=2,
                        volume_ratio=2.5,
                        strength='strong'
                    )
                ]
            ),
            'lpsy': LpsyModel(
                detected=True,
                signals=[
                    LpsySignalModel(
                        date=datetime(2026, 5, 5),
                        price=102.0,
                        volume_ratio=1.5,
                        resistance_level=103.0
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)

        assert result.has_conflict is True
        assert result.dominant_signal.signal_type == 'spring'
        assert result.rejected_signals[0].signal_type == 'lpsy'
        assert "4天" in result.arbitration_reason or "假信号" in result.arbitration_reason
        assert result.suggested_phase == "Accumulation Phase C（需观察）"

    def test_spring_vs_lpsy_medium_time_gap(self, arbitrator):
        """
        测试 Spring vs LPSY：中等时间间隔（7-30天）

        场景：
        - Spring 出现在 2026-04-01
        - LPSY 出现在 2026-04-20（19天后）
        - 预期：LPSY 主导，反弹无力
        """
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 4, 1),
                        breakdown_date=datetime(2026, 4, 1),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=5,
                        volume_ratio=1.8,
                        strength='normal'
                    )
                ]
            ),
            'lpsy': LpsyModel(
                detected=True,
                signals=[
                    LpsySignalModel(
                        date=datetime(2026, 4, 20),
                        price=102.0,
                        volume_ratio=2.0,
                        resistance_level=103.0
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)

        assert result.has_conflict is True
        assert result.dominant_signal.signal_type == 'lpsy'
        assert "19天" in result.arbitration_reason or "反弹无力" in result.arbitration_reason
        assert result.suggested_phase == "Distribution Phase C"

    def test_confidence_adjustment_with_multiple_rejections(self, arbitrator):
        """测试置信度调整系数：多个被拒绝的信号"""
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 3, 1),
                        breakdown_date=datetime(2026, 3, 1),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=3,
                        volume_ratio=2.5,
                        strength='strong'
                    )
                ]
            ),
            'lpsy': LpsyModel(
                detected=True,
                signals=[
                    LpsySignalModel(
                        date=datetime(2026, 5, 1),
                        price=102.0,
                        volume_ratio=2.2,
                        resistance_level=103.0
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)

        # 由于有冲突，置信度应该被降低
        assert result.confidence_adjustment < 1.0
        assert result.confidence_adjustment >= 0.5  # 但不应该低于最低值

    def test_arbitration_summary_generation(self, arbitrator):
        """测试仲裁结果摘要生成"""
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 3, 24),
                        breakdown_date=datetime(2026, 3, 24),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=2,
                        volume_ratio=2.0,
                        strength='normal'
                    )
                ]
            ),
            'lpsy': LpsyModel(
                detected=True,
                signals=[
                    LpsySignalModel(
                        date=datetime(2026, 5, 10),
                        price=102.0,
                        volume_ratio=1.8,
                        resistance_level=103.0
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)
        summary = arbitrator.get_arbitration_summary(result)

        assert "信号冲突" in summary
        assert "主导信号" in summary
        assert "仲裁理由" in summary
        assert "被拒绝信号" in summary

    def test_spring_strength_calculation(self, arbitrator):
        """测试 Spring 信号强度计算"""
        # 强 Spring
        strong_spring = SpringSignalModel(
            date=datetime(2026, 5, 1),
            breakdown_date=datetime(2026, 5, 1),
            breakdown_price=100.0,
            support_level=99.0,
            recovery_price=101.0,
            recovery_days=1,  # 快速收回
            volume_ratio=3.0,  # 高量比
            strength='strong'
        )

        confidence = arbitrator._calculate_spring_confidence(strong_spring)
        assert confidence > 0.8  # 应该有很高的置信度

        # 弱 Spring
        weak_spring = SpringSignalModel(
            date=datetime(2026, 5, 1),
            breakdown_date=datetime(2026, 5, 1),
            breakdown_price=100.0,
            support_level=99.0,
            recovery_price=101.0,
            recovery_days=10,  # 慢速收回
            volume_ratio=1.2,  # 低量比
            strength='weak'
        )

        confidence = arbitrator._calculate_spring_confidence(weak_spring)
        assert confidence < 0.6  # 应该有较低的置信度

    def test_signal_priority_ordering(self, arbitrator):
        """测试信号优先级排序"""
        # LPSY 优先级高于 Spring
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 5, 1),
                        breakdown_date=datetime(2026, 5, 1),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=3,
                        volume_ratio=2.0,
                        strength='normal'
                    )
                ]
            ),
            'lpsy': LpsyModel(
                detected=True,
                signals=[
                    LpsySignalModel(
                        date=datetime(2026, 5, 1),  # 同一天
                        price=102.0,
                        volume_ratio=1.5,
                        resistance_level=103.0
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)

        # LPSY 优先级更高
        assert result.dominant_signal.signal_type == 'lpsy'

    def test_edge_case_same_date(self, arbitrator):
        """测试边界情况：信号出现在同一天"""
        events = {
            'spring': SpringModel(
                detected=True,
                signals=[
                    SpringSignalModel(
                        date=datetime(2026, 5, 1),
                        breakdown_date=datetime(2026, 5, 1),
                        breakdown_price=100.0,
                        support_level=99.0,
                        recovery_price=101.0,
                        recovery_days=2,
                        volume_ratio=2.0,
                        strength='normal'
                    )
                ]
            ),
            'lpsy': LpsyModel(
                detected=True,
                signals=[
                    LpsySignalModel(
                        date=datetime(2026, 5, 1),
                        price=102.0,
                        volume_ratio=2.0,
                        resistance_level=103.0
                    )
                ]
            )
        }

        result = arbitrator.arbitrate(events)

        # 应该基于优先级（LPSY > Spring）
        assert result.has_conflict is True
        assert result.dominant_signal is not None


class TestArbitrationIntegration:
    """仲裁器与其他组件集成测试"""

    def test_arbitration_with_phase_coordinator(self):
        """测试仲裁器与阶段协调器的集成"""
        # 这个测试需要实际的 PatternDetector 实例
        # 这里提供一个基本的测试框架
        pass

    def test_arbitration_result_serialization(self):
        """测试仲裁结果可以正确序列化"""
        from wyckoff.schemas import ArbitrationSignal

        signal = ArbitrationSignal(
            signal_type='spring',
            date=datetime(2026, 5, 1),
            direction='bullish',
            confidence=0.8,
            strength=85.0,
            raw_data={'test': 'data'}
        )

        # 测试模型可以正确创建
        assert signal.signal_type == 'spring'
        assert signal.direction == 'bullish'
        assert signal.confidence == 0.8
