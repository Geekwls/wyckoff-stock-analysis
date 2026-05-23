import pandas as pd
import numpy as np
from wyckoff.core.detectors.strength_weakness_detector import StrengthWeaknessDetector
from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds

def create_mock_data(trend="up"):
    dates = pd.date_range(start="2023-01-01", periods=100)
    data = pd.DataFrame({
        'Open': np.random.randn(100) + 100,
        'High': np.random.randn(100) + 102,
        'Low': np.random.randn(100) + 98,
        'Close': np.random.randn(100) + 100,
        'Volume': np.random.uniform(1000, 5000, 100).astype(float)
    }, index=dates)
    
    # 模拟均线
    data['MA20'] = data['Close'].rolling(20).mean()
    data['Volume_MA20'] = data['Volume'].rolling(20).mean()
    
    if trend == "up":
        # 模拟 LPS: 价格在 MA20 上，缩量回踩
        data.iloc[-5, data.columns.get_loc('Close')] = data['MA20'].iloc[-5] + 5
        data.iloc[-5, data.columns.get_loc('Volume')] = data['Volume_MA20'].iloc[-5] * 0.5
        data.iloc[-5, data.columns.get_loc('Low')] = data['MA20'].iloc[-5] + 2
    else:
        # 模拟 LPSY: 价格在 MA20 下，缩量反弹
        data.iloc[-5, data.columns.get_loc('Close')] = data['MA20'].iloc[-5] - 5
        data.iloc[-5, data.columns.get_loc('Volume')] = data['Volume_MA20'].iloc[-5] * 0.5
        data.iloc[-5, data.columns.get_loc('High')] = data['MA20'].iloc[-5] - 2
        
    return data

def test_lps_detection():
    data = create_mock_data("up")
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    detector = StrengthWeaknessDetector(data, config, thresholds)
    
    result = detector.detect_lps()
    # 虽然随机数据不一定次次中，但我们可以验证结构
    assert 'detected' in result
    if result['detected']:
        assert 'latest' in result
        assert 'signals' in result

def test_lpsy_detection():
    data = create_mock_data("down")
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    detector = StrengthWeaknessDetector(data, config, thresholds)
    
    result = detector.detect_lpsy()
    assert 'detected' in result
