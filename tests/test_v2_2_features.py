import pytest
import pandas as pd
import json
from wyckoff.schemas import DerivedValueModel, SowSignalModel
from wyckoff.core.symbol_resolver import SymbolResolver, MarketType
from wyckoff.facade import WyckoffAnalyzer
from wyckoff.core.pattern_detector import WyckoffPatternDetector


def test_derived_value_backward_compatibility():
    """测试 DerivedValueModel 的向后兼容性 (自动转换 float 为 dict)"""
    # 模拟旧版数据 (float)
    legacy_data = 10.46
    
    # 验证自动转换
    model = DerivedValueModel.model_validate(legacy_data)
    assert model.value == 10.46
    assert model.derivation == "legacy_data"
    assert "兼容性" in model.note

def test_symbol_resolver_is_st():
    """测试 ST 股识别逻辑"""
    resolver = SymbolResolver()
    
    # 测试 ST
    info = resolver.resolve("ST 浪潮信息")
    assert info.is_st is True
    
    # 测试 *ST
    info = resolver.resolve("*ST 核心")
    assert info.is_st is True
    
    # 测试普通股
    info = resolver.resolve("600519")
    assert info.is_st is False

@pytest.fixture
def mock_analyzer_data():
    """创建模拟分析器数据"""
    dates = pd.date_range(start='2023-01-01', periods=100)
    data = pd.DataFrame({
        'Open': [10.0] * 100,
        'High': [11.0] * 100,
        'Low': [9.0] * 100,
        'Close': [10.5] * 100,
        'Volume': [1000] * 100,
    }, index=dates)
    # 计算 ATR
    data['ATR'] = 1.0
    return data

def test_atomic_methods_structure(mock_analyzer_data, monkeypatch):
    """测试原子工具输出结构的完整性"""
    # Mock fetch_data 避免网络请求
    def mock_fetch(self, frequency="1d"):
        self.data = mock_analyzer_data
        self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)
        return self.data
    
    monkeypatch.setattr(WyckoffAnalyzer, "fetch_data", mock_fetch)
    
    with WyckoffAnalyzer("AAPL") as analyzer:
        # 1. 测试 phase_json
        phase_json = analyzer.generate_phase_json()
        res = json.loads(phase_json)
        assert 'phase' in res
        assert 'phase_confidence' in res
        assert 'phase_advice' in res
        
        # 2. 测试 levels_json
        levels_json = analyzer.generate_levels_json()
        res = json.loads(levels_json)
        assert 'stop_loss' in res
        assert 'targets' in res
        # 验证 derivation 是否存在 (说明成功复用了 TradingPlanGenerator)
        assert 'derivation' in res['stop_loss']['conservative']
        
        # 3. 测试 conflict_json
        conflict_json = analyzer.generate_conflict_json()
        res = json.loads(conflict_json)
        assert 'has_conflict' in res
        assert 'interpretation' in res
