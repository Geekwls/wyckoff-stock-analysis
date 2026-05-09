import pytest
import pandas as pd
import numpy as np
from src.wyckoff.core.report_generator import WyckoffReportGenerator
from src.wyckoff.config.settings import ScoringConfig, PositionSizingConfig, WyckoffConfig
from src.wyckoff.core.enums import MarketEnvironment, MarketSide
from datetime import datetime

class MockAnalyzer:
    def __init__(self, data):
        self.data = data
        self.config = WyckoffConfig()
        self.symbol = "TEST"
        self.pattern_detector = self
        self.law_analyzer = self
    
    def identify_phase(self):
        return {"phase": "Accumulation Phase D", "confidence": 0.8}
    
    def detect_trading_range(self): return {"is_consolidation": False}
    def detect_spring(self): return {"detected": False}
    def detect_spring_menhongtao(self): return {"detected": False}
    def detect_joc_menhongtao(self): return {"detected": False}
    def detect_vsa_menhongtao(self): return {}
    def detect_upthrust(self): return {"detected": False}
    def detect_sos(self): return {"detected": False}
    def detect_sow(self): return {"detected": False}
    def detect_lps(self): return {"detected": False}
    def detect_lpsy(self): return {"detected": False}
    def detect_joc(self): return {"detected": False}
    def detect_fti(self): return {"detected": False}
    def detect_vsa_signals(self): return {}
    def detect_climax(self): return {"detected": False}
    def detect_automatic_reaction(self, climax): return {"detected": False}
    def detect_secondary_test(self, climax, ar): return {"detected": False}
    def detect_boring_zone(self): return {"detected": False}
    def detect_dead_corner_breakout(self): return {"detected": False}
    def calculate_cause_effect(self): 
        return {
            'cause_bars': 40,
            'breakout_direction': 'up',
            'targets': {
                'target_1': 100,
                'target_2': 120,
                'target_3': 150
            }
        }
    
    def _collect_all_events(self):
        return {
            'events_detected': {},
            'phase': 'Unknown',
            'sequence_validation': {}
        }
    def identify_phase_with_rs(self): return self.identify_phase()
    def _analyze_market_environment(self): return {"environment": MarketEnvironment.UNKNOWN}
    def _get_baseline_index_symbol(self): return "SPY"
    def _get_cached_index_analyzer(self): return None
    def _is_a_stock(self, symbol): return False
    def analyze_supply_demand_law(self): return {}
    def analyze_effort_vs_result_law(self): return {}
    def analyze_cause_effect_law_enhanced(self): return {}

def create_mock_data(close_vals, vol_vals, vol_ma20=1000, atr=None):
    df = pd.DataFrame({
        'Close': close_vals,
        'High': [c * 1.01 for c in close_vals],
        'Low': [c * 0.99 for c in close_vals],
        'Volume': vol_vals,
        'MA50': [100.0] * len(close_vals),
        'MA200': [90.0] * len(close_vals),
        'Volume_MA20': [vol_ma20] * len(close_vals)
    })
    if atr:
        df['ATR'] = [atr] * len(close_vals)
    else:
        df['ATR'] = [2.0] * len(close_vals)
    return df

def test_calculate_signal_quality_bullish_resonance():
    # Bullish setup: Price > MA50 > MA200, Volume Spike, Bullish Market
    data = create_mock_data([110.0, 115.0], [1000, 2000], vol_ma20=1000)
    analyzer = MockAnalyzer(data)
    generator = WyckoffReportGenerator(analyzer)
    
    market_phase = {'environment': MarketEnvironment.BULL}
    result = generator.calculate_signal_quality(market_phase)
    
    # Expected score:
    # Vol Spike (>1.5x): +3
    # Trend alignment (115 > 100 > 90): +3
    # Market environment (Bull + Accumulation): +4
    # Total: 10
    assert result['score'] == 10
    assert "成交量强力确认" in str(result['reasons'])
    assert "多时间框架一致" in str(result['reasons'])
    assert "顺应大盘多头" in str(result['reasons'])

def test_calculate_signal_quality_range_bound():
    data = create_mock_data([100.0, 101.0], [1000, 1100], vol_ma20=1000)
    analyzer = MockAnalyzer(data)
    generator = WyckoffReportGenerator(analyzer)
    
    market_phase = {'environment': MarketEnvironment.RANGE_BOUND}
    result = generator.calculate_signal_quality(market_phase)
    
    # Expected score:
    # Vol Moderate (>1.0x): +1
    # Trend alignment (101 > 100 > 90): +3
    # Market environment (Range Bound): +2
    # Total: 6
    assert result['score'] == 6

def test_position_sizing_volatility_cap():
    # High volatility: ATR = 10, Price = 100 (10% ATR ratio > 4% cap)
    data = create_mock_data([100.0, 100.0], [1000, 1000], vol_ma20=2000000, atr=10.0)
    analyzer = MockAnalyzer(data)
    generator = WyckoffReportGenerator(analyzer)
    
    signal_quality = {"score": 10, "max_score": 10}
    trading_plan = {"direction": "做多", "stop_loss": {"conservative": 90, "aggressive": 85}}
    
    advice = generator.generate_risk_advice(signal_quality, trading_plan)
    
    # Base aggressive pos is 20%.
    # Safety multiplier: 0.04 / 0.10 = 0.4
    # Final pos: 20% * 0.4 = 8.0%
    assert advice['aggressive']['position'] == "8.0% 仓位上限"

def test_position_sizing_liquidity_penalty():
    # Low liquidity: Vol MA20 = 500,000 (below 1,000,000 threshold)
    data = create_mock_data([100.0, 100.0], [1000, 1000], vol_ma20=500000, atr=1.0)
    analyzer = MockAnalyzer(data)
    generator = WyckoffReportGenerator(analyzer)
    
    signal_quality = {"score": 10, "max_score": 10}
    trading_plan = {"direction": "做多", "stop_loss": {"conservative": 90, "aggressive": 85}}
    
    advice = generator.generate_risk_advice(signal_quality, trading_plan)
    
    # Volatility ratio: 1/100 = 0.01 < 0.04 (no penalty)
    # Liquidity ratio: 500k / 1M = 0.5
    # Final pos: 20% * 0.5 = 10.0%
    assert advice['aggressive']['position'] == "10.0% 仓位上限"

def test_stop_loss_description_rules():
    data = create_mock_data([100.0, 100.0], [1000, 1000])
    analyzer = MockAnalyzer(data)
    generator = WyckoffReportGenerator(analyzer)
    
    advice = generator.generate_risk_advice({"score": 10}, {"direction": "做多"})
    
    assert "若开盘跳空跌破止损线" in advice['aggressive']['stop_loss']
    assert "不计较滑点" in advice['aggressive']['stop_loss']

def test_signal_conflict_detection():
    data = create_mock_data([100.0, 110.0], [1000, 2000])
    analyzer = MockAnalyzer(data)
    generator = WyckoffReportGenerator(analyzer)
    
    # Mock both JOC (Bullish) and Upthrust (Bearish) detected
    generator.pattern_detector.detect_joc_menhongtao = lambda: {
        'detected': True, 'test_detected': True, 'creek_level': 105, 
        'date': datetime.now(), 'close_price': 108, 'breakout_pct': 0.03, 'volume_ratio': 2.0, 'confidence': 0.9
    }
    generator.pattern_detector.detect_upthrust = lambda: {
        'detected': True, 
        'latest_upthrust': {
            'date': datetime.now(), 'breakout_price': 112, 'resistance_level': 110,
            'rejection_price': 109, 'rejection_days': 2, 'close_from_high': 0.05
        }
    }
    generator.pattern_detector.detect_lps = lambda: {'detected': False}
    generator.pattern_detector.detect_lpsy = lambda: {'detected': False}
    generator.pattern_detector.detect_spring_menhongtao = lambda: {'detected': False}
    generator.pattern_detector.detect_fti = lambda: {'detected': False}
    generator.pattern_detector.detect_trading_range = lambda: {
        'is_consolidation': True, 'low': 100, 'high': 110, 'range_pct': 0.1, 
        'position': 0.5, 'volume_trend': 'neutral'
    }
    
    # Mock _collect_all_events to return events with enough signals for quality score
    generator.pattern_detector._collect_all_events = lambda: {
        'events_detected': {
            'joc': {'detected': True, 'volume_ratio': 2.0, 'confidence': 0.9, 'date': datetime.now()},
            'upthrust': {'detected': True, 'volume_ratio': 1.5, 'confidence': 0.8, 'date': datetime.now()}
        },
        'phase': 'Distribution Phase A',
        'sequence_validation': {'score': {'rating': 'B'}}
    }
    
    # Mock cross-timeframe conflict to not gate signal conflict detection
    generator._cross_timeframe_conflict_warning = lambda **kwargs: {
        'has_conflict': False,
        'daily_side': 'bullish',
        'weekly_trend': 'unknown',
        'monthly_trend': 'unknown',
        'agreement': 'unknown',
        'conflict_reason': '',
        'monthly_warning': '',
        'action': 'normal'
    }
    
    report = generator.generate_report()
    print(f"DEBUG REPORT:\n{report}")
    assert "信号冲突警示" in report
    assert "市场多空分歧剧烈" in report

def test_threshold_gating_low_score():
    data = create_mock_data([100.0, 101.0], [1000, 1100], vol_ma20=1000)
    analyzer = MockAnalyzer(data)
    generator = WyckoffReportGenerator(analyzer)
    
    # Low score setup (Market Unknown + Low Vol)
    # Vol 1.1x -> +1
    # Trend 101 > 100 > 90 -> +3
    # Market Unknown -> +0
    # Total = 4 (Right at the threshold, let's make it lower)
    
    # Mock very low score
    generator.calculate_signal_quality = lambda x: {"score": 2, "max_score": 10}
    
    report = generator.generate_report()
    assert "观望等待（信号质量不足）" in report
    assert "信号强度或可靠性低于执行阈值" in report

def test_market_aware_direction_a_stock():
    from src.wyckoff.core.trading_plan_generator import TradingPlanGenerator
    data = create_mock_data([100.0, 100.0], [1000, 1000])
    # detect_trading_range in generator is called without args, but my mock might be receiving self.
    pattern_detector = type('obj', (object,), {'detect_trading_range': lambda self: {}})()
    generator = TradingPlanGenerator(data, pattern_detector)
    
    # Bearish case for A-stock
    plan = generator.generate(phase_str="Distribution Phase E", is_a_stock=True)
    assert plan['direction'] == "减仓/观望"
    assert "A股无法直接做空" in plan['market_constraint']
    
    # Bearish case for Non-A-stock
    plan = generator.generate(phase_str="Distribution Phase E", is_a_stock=False)
    assert plan['direction'] == "做空"
    assert plan.get('market_constraint') is None
