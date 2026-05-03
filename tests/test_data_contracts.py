"""
跨模块数据契约测试
确保检测器输出字段与报告层读取字段一致
"""
import pytest
import pandas as pd
import numpy as np
from typing import Dict, Any, Set

from tools.core.detectors.classic_pattern_detector import ClassicPatternDetector
from tools.core.detectors.strength_weakness_detector import StrengthWeaknessDetector
from tools.config.settings import WyckoffConfig, WyckoffThresholds
from tools.core.cache import LRUCache


def _make_test_df(n: int = 100) -> pd.DataFrame:
    """创建测试用DataFrame"""
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=n)
    data = {
        'Open': np.random.uniform(100, 110, n),
        'High': np.random.uniform(110, 120, n),
        'Low': np.random.uniform(90, 100, n),
        'Close': np.random.uniform(100, 110, n),
        'Volume': np.random.randint(1000000, 5000000, n)
    }
    df = pd.DataFrame(data, index=dates)
    df['Volume_MA20'] = df['Volume'].rolling(20).mean()
    df['ATR'] = (df['High'] - df['Low']).rolling(14).mean()
    return df


class TestSpringContract:
    """Spring数据契约测试"""
    
    # Spring信号必须包含的字段
    REQUIRED_FIELDS = {
        'date',
        'breakdown_date', 
        'breakdown_price',
        'support_level',
        'recovery_price',
        'recovery_days',  # 注意：是复数
        'volume_ratio'
    }
    
    def test_spring_signal_has_required_fields(self):
        """验证Spring信号包含所有必需字段"""
        df = _make_test_df()
        config = WyckoffConfig()
        cache = LRUCache()
        detector = ClassicPatternDetector(df, config, cache, cache)
        
        result = detector.detect_spring()
        
        if result.get('detected') and result.get('signals'):
            for signal in result['signals']:
                actual_fields = set(signal.keys())
                missing_fields = self.REQUIRED_FIELDS - actual_fields
                assert not missing_fields, f"Spring信号缺少字段: {missing_fields}"
    
    def test_spring_recovery_days_is_integer(self):
        """验证recovery_days是整数类型"""
        df = _make_test_df()
        config = WyckoffConfig()
        cache = LRUCache()
        detector = ClassicPatternDetector(df, config, cache, cache)
        
        result = detector.detect_spring()
        
        if result.get('detected') and result.get('signals'):
            for signal in result['signals']:
                assert 'recovery_days' in signal, "缺少recovery_days字段"
                assert isinstance(signal['recovery_days'], int), \
                    f"recovery_days应该是int，实际是{type(signal['recovery_days'])}"
    
    def test_spring_no_recovery_day_singular(self):
        """验证不存在recovery_day（单数）字段"""
        df = _make_test_df()
        config = WyckoffConfig()
        cache = LRUCache()
        detector = ClassicPatternDetector(df, config, cache, cache)
        
        result = detector.detect_spring()
        
        if result.get('detected') and result.get('signals'):
            for signal in result['signals']:
                assert 'recovery_day' not in signal, \
                    "发现已废弃的字段名'recovery_day'，应使用'recovery_days'"


class TestUpthrustContract:
    """Upthrust数据契约测试"""
    
    REQUIRED_FIELDS = {
        'date',
        'breakout_date',
        'breakout_price', 
        'resistance_level',
        'rejection_price',
        'rejection_days',
        'close_from_high'
    }
    
    def test_upthrust_signal_has_required_fields(self):
        """验证Upthrust信号包含所有必需字段"""
        df = _make_test_df()
        config = WyckoffConfig()
        cache = LRUCache()
        detector = ClassicPatternDetector(df, config, cache, cache)
        
        result = detector.detect_upthrust()
        
        if result.get('detected') and result.get('upthrusts'):
            for signal in result['upthrusts']:
                actual_fields = set(signal.keys())
                missing_fields = self.REQUIRED_FIELDS - actual_fields
                assert not missing_fields, f"Upthrust信号缺少字段: {missing_fields}"


class TestSOSContract:
    """SOS数据契约测试"""
    
    REQUIRED_FIELDS = {
        'date',
        'price',
        'volume_ratio',
        'price_change',
        'breakthrough_level'
    }
    
    def test_sos_signal_has_required_fields(self):
        """验证SOS信号包含所有必需字段"""
        df = _make_test_df()
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        detector = StrengthWeaknessDetector(df, config, thresholds)
        
        result = detector.detect_sos()
        
        if result.get('detected'):
            actual_fields = set(result.keys())
            missing_fields = self.REQUIRED_FIELDS - actual_fields
            assert not missing_fields, f"SOS信号缺少字段: {missing_fields}"


class TestSOWContract:
    """SOW数据契约测试"""
    
    REQUIRED_FIELDS = {
        'date',
        'price',
        'volume_ratio',
        'price_change',
        'breakdown_level'
    }
    
    def test_sow_signal_has_required_fields(self):
        """验证SOW信号包含所有必需字段"""
        df = _make_test_df()
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        detector = StrengthWeaknessDetector(df, config, thresholds)
        
        result = detector.detect_sow()
        
        if result.get('detected'):
            actual_fields = set(result.keys())
            missing_fields = self.REQUIRED_FIELDS - actual_fields
            assert not missing_fields, f"SOW信号缺少字段: {missing_fields}"


class TestVSAContract:
    """VSA数据契约测试"""
    
    REQUIRED_FIELDS = {
        'detected',
        'date',
        'vol_ratio',
        'description'
    }
    
    def test_vsa_signals_have_description(self):
        """验证VSA信号包含description字段"""
        df = _make_test_df()
        config = WyckoffConfig()
        thresholds = WyckoffThresholds()
        cache = LRUCache()
        detector = ClassicPatternDetector(df, config, thresholds, cache)
        
        result = detector.detect_vsa_signals()
        
        for signal_type in ['no_supply', 'no_demand', 'stopping_vol']:
            signal = result.get(signal_type, {})
            if signal.get('detected'):
                actual_fields = set(signal.keys())
                missing_fields = self.REQUIRED_FIELDS - actual_fields
                assert not missing_fields, \
                    f"VSA {signal_type} 缺少字段: {missing_fields}"
                assert isinstance(signal['description'], str), \
                    f"VSA {signal_type} 的description应该是字符串"


class TestReportReaderContract:
    """报告层读取契约测试"""
    
    def test_report_reads_recovery_days(self):
        """验证报告层读取recovery_days（复数）"""
        # 这个测试通过代码检查来验证
        import inspect
        from tools.core.report_generator import WyckoffReportGenerator
        
        source = inspect.getsource(WyckoffReportGenerator.generate_report)
        
        # 检查是否使用了正确的字段名
        assert "latest['recovery_days']" in source, \
            "报告层应该读取'recovery_days'（复数）"
        
        # 检查是否没有使用废弃的字段名
        assert "latest['recovery_day']" not in source, \
            "报告层不应读取已废弃的'recovery_day'（单数）"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
