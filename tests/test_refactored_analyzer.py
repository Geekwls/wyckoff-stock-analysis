import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.wyckoff.wyckoff_analyzer import WyckoffAnalyzer
from src.wyckoff.core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from src.wyckoff.core.relative_strength_analyzer import RelativeStrengthAnalyzer
from src.wyckoff.core.pattern_detector import WyckoffPatternDetector
from src.wyckoff.config.settings import WyckoffConfig

def _make_base_df(days=300):
    end_date = datetime(2024, 1, 1)
    dates = pd.date_range(end=end_date, periods=days)
    data = {
        'Open': np.linspace(100, 150, days),
        'High': np.linspace(102, 152, days),
        'Low': np.linspace(98, 148, days),
        'Close': np.linspace(101, 151, days),
        'Volume': np.random.randint(1000, 2000, days).astype(float)
    }
    df = pd.DataFrame(data, index=dates)
    df['Volume_MA20'] = df['Volume'].rolling(20).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA50'] = df['Close'].rolling(50).mean()
    df['MA200'] = df['Close'].rolling(200).mean().fillna(df['Close'])
    df['ATR'] = (df['High'] - df['Low']).rolling(14).mean().fillna(5.0)
    return df

def test_mtf_analyzer():
    df = _make_base_df(400)
    # 模拟上涨趋势
    df['Close'] = np.linspace(100, 300, 400)
    df['MA10'] = df['Close'].rolling(10).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    
    from src.wyckoff.core.cache import LRUCache
    cache = LRUCache()
    config = WyckoffConfig()
    pd_detector = WyckoffPatternDetector(df, config, cache)
    mtf = MultiTimeframeAnalyzer(df, pd_detector)
    
    weekly_trend = mtf.get_weekly_trend()
    assert weekly_trend in ['bullish', 'neutral', 'bearish', 'unknown']
    
    monthly_trend = mtf.get_monthly_trend()
    assert monthly_trend in ['bullish', 'neutral', 'bearish', 'unknown']
    
    resonance = mtf.analyze_resonance()
    assert 'resonance_level' in resonance
    assert 'resonance_signals' in resonance

def test_rs_analyzer():
    stock_df = _make_base_df(100)
    bench_df = _make_base_df(100)
    
    # 模拟个股强于大盘
    stock_df['Close'] = np.linspace(100, 200, 100)
    bench_df['Close'] = np.linspace(100, 120, 100)
    
    rs_analyzer = RelativeStrengthAnalyzer(stock_df, "TEST_STOCK")
    rs_result = rs_analyzer.calculate_rs(bench_df)
    
    assert rs_result['rs_trend'] == 'rising'
    assert rs_result['is_outperforming'] is True
    assert 'rs_change_20d' in rs_result

def test_wyckoff_analyzer_integration():
    from src.wyckoff.core.cache import LRUCache
    # 这是一个集成测试，验证 refactored WyckoffAnalyzer 是否能正常工作
    analyzer = WyckoffAnalyzer("AAPL", period="1y")
    # 我们不真调 fetch_data，而是注入模拟数据
    df = _make_base_df(300)
    analyzer.data = df
    analyzer.pattern_detector = WyckoffPatternDetector(df, analyzer.config, LRUCache())
    analyzer.mtf_analyzer = MultiTimeframeAnalyzer(df, analyzer.pattern_detector)
    analyzer.rs_analyzer = RelativeStrengthAnalyzer(df, "AAPL")
    
    # 测试 delegation
    res = analyzer.analyze_timeframe_resonance()
    assert 'resonance_level' in res
    assert 'implication' in res
    
    phase_res = analyzer.identify_phase_multi_timeframe()
    assert 'phase' in phase_res
    assert 'weekly_trend' in phase_res
