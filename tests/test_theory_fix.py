import pandas as pd
import numpy as np
import sys
import os

# 将 src 添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from wyckoff.facade import WyckoffAnalyzer
from wyckoff.config.settings import WyckoffConfig
from wyckoff.core.pattern_detector import WyckoffPatternDetector

def create_mock_data():
    """
    创建一个具有明确 PS -> SC -> AR -> ST 序列的模拟数据
    """
    dates = pd.date_range(start="2023-01-01", periods=100, freq='D')
    
    # 基础价格：从 100 开始缓慢下跌
    prices = np.linspace(100, 80, 50)
    
    # PS: 第一次放量止跌尝试 (第 55 天)
    prices = np.append(prices, [78, 79, 80, 77, 76]) # 小反弹后继续跌
    
    # SC: 恐慌抛售 (第 60 天)
    prices = np.append(prices, [70]) # 暴跌
    
    # AR: 自然反弹 (第 61-65 天)
    prices = np.append(prices, [72, 75, 78, 80, 79])
    
    # ST: 二次测试 (第 66-70 天)
    prices = np.append(prices, [75, 73, 72, 73, 74])
    
    # 填充到 100 天
    remaining = 100 - len(prices)
    prices = np.append(prices, np.linspace(74, 76, remaining))
    
    df = pd.DataFrame({
        'Open': prices - 1,
        'High': prices + 2,
        'Low': prices - 2,
        'Close': prices,
        'Volume': [1000] * 100
    }, index=dates)
    
    # 设置异常成交量和价差 (Climax 特征)
    df.loc[dates[54], 'Volume'] = 4000 # PS
    df.loc[dates[54], 'High'] = df.loc[dates[54], 'Close'] + 10 # 增加价差
    
    df.loc[dates[59], 'Volume'] = 6000 # SC
    df.loc[dates[59], 'Low'] = df.loc[dates[59], 'Close'] - 15 # 增加价差，向下穿刺
    df.loc[dates[59], 'High'] = df.loc[dates[59], 'Open'] + 2
    
    # 预计算指标
    df['Volume_MA20'] = df['Volume'].rolling(20).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA50'] = df['Close'].rolling(50).mean()
    df['MA200'] = df['Close'].rolling(200).mean() # 虽然数据不够，但保留结构
    
    return df

def test_ps_sc_sequence():
    print("Testing PS -> SC -> AR sequence...")
    data = create_mock_data()
    config = WyckoffConfig()
    analyzer = WyckoffAnalyzer("MOCK", config=config)
    analyzer.data = data # 手动注入数据
    # 直接使用导入的类初始化
    analyzer.pattern_detector = WyckoffPatternDetector(data, config, analyzer._analysis_cache)
    
    # 运行 Phase A 证据分析
    evidence = analyzer.pattern_detector.analyze_phase_a_evidence()
    
    print(f"Phase A Confirmed: {evidence['phase_a_confirmed']}")
    print(f"Is Valid Sequence: {evidence['is_valid_sequence']}")
    
    sc_res = evidence['evidence']['sc']
    ps_res = evidence['evidence']['ps']
    ar_res = evidence['evidence']['ar']
    
    sc_date = sc_res.get('date')
    ps_date = ps_res.get('ps_date')
    ar_date = ar_res.get('ar_date')
    
    print(f"PS Date: {ps_date}")
    print(f"SC Date: {sc_date}")
    print(f"AR Date: {ar_date}")
    
    if ps_date and sc_date and ar_date:
        ps_dt = pd.to_datetime(ps_date)
        sc_dt = pd.to_datetime(sc_date)
        ar_dt = pd.to_datetime(ar_date)
        if ps_dt < sc_dt < ar_dt:
            print("SUCCESS: PS -> SC -> AR sequence is correct.")
        else:
            print(f"FAILURE: Inverted sequence detected! {ps_dt} < {sc_dt} < {ar_dt} is False")
    else:
        print("FAILURE: Could not detect all events in sequence.")

def test_cause_effect():
    print("\nTesting Cause & Effect (Horizontal Logic)...")
    # 模拟一个长期横盘
    dates = pd.date_range(start="2023-01-01", periods=200, freq='D')
    df = pd.DataFrame({
        'Open': [80]*200, 'High': [82]*200, 'Low': [78]*200, 'Close': [80]*200, 'Volume': [1000]*200
    }, index=dates)
    df['Volume_MA20'] = 1000
    
    config = WyckoffConfig()
    analyzer = WyckoffAnalyzer("MOCK", config=config)
    analyzer.data = df
    analyzer.pattern_detector = WyckoffPatternDetector(df, config, analyzer._analysis_cache)
    
    ce_result = analyzer.calculate_cause_effect()
    print(f"Description: {ce_result.get('description')}")
    print(f"Targets: {ce_result.get('targets')}")
    
    # 验证目标价是否合理
    if ce_result['targets']['target_2'] > 80: # 应该有潜力
        print("SUCCESS: Cause & Effect targets are calculated.")
    else:
        print("FAILURE: Cause & Effect targets are missing or 0.")

if __name__ == "__main__":
    try:
        test_ps_sc_sequence()
        test_cause_effect()
    except Exception as e:
        print(f"An error occurred during testing: {e}")
