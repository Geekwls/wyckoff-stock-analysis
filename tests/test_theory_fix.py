import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.wyckoff.core.pattern_detector import WyckoffPatternDetector
from src.wyckoff.config.settings import WyckoffConfig, WyckoffThresholds

class MockCache:
    def get_or_compute(self, key, func, *args, **kwargs):
        return func(*args, **kwargs)

class TestTheoryFix(unittest.TestCase):
    def setUp(self):
        self.config = WyckoffConfig()
        self.thresholds = WyckoffThresholds()
        self.cache = MockCache()
        
    def _create_mock_data(self, periods=200, base_price=200):
        dates = pd.date_range(end=datetime.now(), periods=periods)
        data = pd.DataFrame({
            'Open': np.random.uniform(base_price, base_price+5, periods),
            'High': np.random.uniform(base_price+5, base_price+10, periods),
            'Low': np.random.uniform(base_price-5, base_price, periods),
            'Close': np.random.uniform(base_price, base_price+5, periods),
            'Volume': np.random.uniform(1000, 1500, periods)
        }, index=dates)
        
        data['Volume_MA20'] = data['Volume'].rolling(20).mean()
        data['MA20'] = data['Close'].rolling(20).mean()
        data['MA50'] = data['Close'].rolling(50).mean()
        data['MA200'] = data['Close'].rolling(200).mean()
        data['High_Max_20'] = data['High'].rolling(20).max()
        data['Low_Min_20'] = data['Low'].rolling(20).min()
        return data

    def test_ar_baseline_correction(self):
        """测试 AR 反弹基准修正"""
        data = self._create_mock_data(200, base_price=200)
        # 放在倒数第 20 天
        sc_idx = 180
        data.loc[data.index[sc_idx], 'Low'] = 80
        data.loc[data.index[sc_idx], 'Open'] = 90
        data.loc[data.index[sc_idx], 'Close'] = 85
        data.loc[data.index[sc_idx], 'Volume'] = 10000 
        
        # 制造一个 AR
        ar_idx = 185
        data.loc[data.index[ar_idx], 'High'] = 100
        
        detector = WyckoffPatternDetector(data, self.config, self.cache)
        # 我们直接调用内部检测器以确保它看到正确的切片
        ar_res = detector.detect_automatic_rally()
        
        self.assertTrue(ar_res['detected'])
        self.assertAlmostEqual(ar_res['rebound_pct'], (100 - 87.5) / 87.5 * 100, places=2)

    def test_phase_revision_mechanism(self):
        """测试阶段证伪机制"""
        data = self._create_mock_data(200, base_price=200)
        
        # 1. 制造 Buying Climax
        bc_idx = 150
        data.loc[data.index[bc_idx], 'High'] = 300
        data.loc[data.index[bc_idx], 'Open'] = 290
        data.loc[data.index[bc_idx], 'Close'] = 295
        data.loc[data.index[bc_idx], 'Volume'] = 10000
        
        # 制造 AR 配合 BC 触发 Distribution Phase A
        ar_idx = 155
        data.loc[data.index[ar_idx], 'Low'] = 250
        
        # 2. 制造 Spring
        # 这里的支撑位检测依赖于 TradingRangeDetector
        # 我们模拟一个支撑位
        data.loc[data.index[140:170], 'Low'] = 240
        data.loc[data.index[140:170], 'High'] = 260
        
        spring_idx = 180
        data.loc[data.index[spring_idx], 'Low'] = 220 
        data.loc[data.index[spring_idx], 'Close'] = 245 
        data.loc[data.index[spring_idx], 'Volume'] = 5000
        
        # 3. 制造 JOC
        joc_idx = 195
        data.loc[data.index[joc_idx], 'Close'] = 310 
        data.loc[data.index[joc_idx], 'Volume'] = 8000
        
        detector = WyckoffPatternDetector(data, self.config, self.cache)
        events = detector._collect_all_events()
        
        print(f"DEBUG: Revision Log: {events['phase_revision_log']}")
        self.assertTrue(any("修正为再吸筹" in log for log in events['phase_revision_log']))

if __name__ == '__main__':
    unittest.main()
