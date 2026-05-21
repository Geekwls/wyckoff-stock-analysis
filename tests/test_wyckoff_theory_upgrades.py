"""
tests/test_wyckoff_theory_upgrades.py - 针对威科夫理论偏差修正五项核心升级的单元与回归测试
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from src.wyckoff.core.pattern_detector import WyckoffPatternDetector
from src.wyckoff.core.detectors.reversal_detector import ReversalDetector
from src.wyckoff.core.detectors.meng_trend_detector import MengTrendDetector
from src.wyckoff.core.detectors.trend_detector import TrendDetector
from src.wyckoff.core.recommendation_engine import RecommendationEngine
from src.wyckoff.core.phase_coordinator import PhaseCoordinator
from src.wyckoff.core.point_and_figure import PointAndFigureCalculator
from src.wyckoff.core.laws.effort_result import EffortResultMixin
from src.wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from src.wyckoff.schemas import SignalQualityModel, PositionSizingModel, StopLossModel


def test_spring_type_1_and_st_confirmation():
    # Setup detector with minimal mock data
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    
    # 1. 测试二次测试（ST）校验函数
    dates = pd.date_range("2026-01-01", periods=30)
    data = pd.DataFrame({
        "Open": [100.0] * 30,
        "High": [105.0] * 30,
        "Low": [98.0] * 30,
        "Close": [100.0] * 30,
        "Volume": [1000.0] * 30,
    }, index=dates)
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    data["ATR"] = 2.0
    
    # 实例化反转检测器
    detector = ReversalDetector(data, config, thresholds, None)
    
    spring_dict = {
        'date': dates[5],
        'breakdown_price': {'value': 90.0},
        'breakdown_volume': 3000.0,
        'spring_type': 'type_1_dangerous'
    }
    
    # 情况 A：后续低点保持在 Spring 低点之上，且成交量显著萎缩（< 2100）
    for i in range(6, 15):
        data.loc[dates[i], 'Low'] = 92.0
        data.loc[dates[i], 'Volume'] = 1500.0
        
    detector.data = data
    assert detector._verify_spring_st(spring_dict) is True
    
    # 情况 B：后续价格打破了 Spring 的最低价
    data.loc[dates[7], 'Low'] = 89.0
    detector.data = data
    assert detector._verify_spring_st(spring_dict) is False

    # 2. 测试推荐引擎拦截 (未确认 ST 时强制拦截改签观望)
    engine = RecommendationEngine()
    rec_data = pd.DataFrame({
        "Open": [100.0, 100.0],
        "High": [105.0, 105.0],
        "Low": [98.0, 98.0],
        "Close": [101.0, 101.0],
        "Volume": [1000.0, 1000.0],
    })
    rec_data["ATR"] = 2.0
    
    # 需要ST，但是 st_confirmed = False -> 应当强行被覆写为 '观望'
    pattern_results = {
        'phase': 'Phase C',
        'spring': {
            'detected': True,
            'latest_spring': {
                'spring_type': 'type_1_dangerous',
                'needs_secondary_test': True,
                'st_confirmed': False,
                'breakdown_price': {'value': 90.0}
            }
        }
    }
    
    plan = engine.generate_trading_plan(rec_data, pattern_results, {})
    assert plan.direction == "观望"
    assert plan.entry_zone == "等待低点高于 Spring 且缩量的二次测试确认"
    assert plan.position_sizing.conservative == "0%"


def test_adaptive_weis_wave_window(monkeypatch):
    # 构建测试 EffortResultMixin 混入类的哑类
    class DummyEffortResult(EffortResultMixin):
        def __init__(self, data):
            self.data = data
            
    dates = pd.date_range("2026-01-01", periods=100)
    
    # 情况 A: 低 ATR%（波动小） -> w_len 应自适应放大（最大到 12）
    data_low = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [100.5] * 100,
        "Low": [100.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [1000.0] * 100,
        "ATR": [0.5] * 100
    }, index=dates)
    
    # 模拟 WeisWave 缺失以强制触发降级 Fallback 模式
    try:
        from src.wyckoff.core.weis_wave import WeisWaveGenerator
        monkeypatch.setattr("src.wyckoff.core.weis_wave.WeisWaveGenerator", lambda *args, **kwargs: 1/0)
    except Exception:
        pass
        
    engine_low = DummyEffortResult(data_low)
    res_low = engine_low._analyze_wave_efficiency(data_low)
    
    assert res_low["status"] == "ok"
    assert res_low["method"] == "legacy_adaptive_window"
    
    # 情况 B: 高 ATR%（波动大） -> w_len 应自适应缩小（最小到 5）
    data_high = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [105.0] * 100,
        "Low": [100.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [1000.0] * 100,
        "ATR": [5.0] * 100
    }, index=dates)
    
    engine_high = DummyEffortResult(data_high)
    res_high = engine_high._analyze_wave_efficiency(data_high)
    
    assert res_high["status"] == "ok"
    assert res_high["method"] == "legacy_adaptive_window"


def test_redistribution_phase_override_and_long_blocking(monkeypatch):
    from src.wyckoff.core.phase_coordinator import PhaseCoordinator
    
    class MockDetector:
        def __init__(self):
            self.data = pd.DataFrame()
        def detect_choch(self):
            return {'detected': False}
            
    detector = MockDetector()
    coordinator = PhaseCoordinator(detector)
    
    # 强制将前序趋势判断返回 markdown
    monkeypatch.setattr(coordinator, "_detect_prior_trend", lambda: "markdown")
    
    class MockSpring:
        def __init__(self, detected=False, signals=None):
            self.detected = detected
            self.signals = signals or []
            
    class MockEvents:
        def __init__(self):
            self.breakout_analysis = None
            self.trading_range = None
            self.spring_upthrust = None
            self.spring = MockSpring(detected=False)
            self.sos_sow = None
            
    events = MockEvents()
    
    # 验证在吸筹阶段且前序为熊市趋势时，一票否决定性为 "再派发"
    final_phase, logs = coordinator.validate_phase_consistency(
        preliminary_phase="Accumulation Phase A",
        events=events
    )
    
    assert "Re-distribution" in final_phase
    assert "前序趋势否决" in "".join(logs)
    
    # 验证做多信号在该阶段被推荐引擎与交易计划拦截并强制观望
    engine = RecommendationEngine()
    rec_data = pd.DataFrame({
        "Open": [100.0, 100.0],
        "High": [105.0, 105.0],
        "Low": [98.0, 98.0],
        "Close": [101.0, 101.0],
        "Volume": [1000.0, 1000.0],
    })
    rec_data["ATR"] = 2.0
    
    pattern_results = {
        'phase': 'Distribution (Re-distribution) Phase B',
        'spring': {'detected': True, 'latest_spring': {'spring_type': 'type_3_safe', 'needs_secondary_test': False, 'st_confirmed': True}}
    }
    
    plan = engine.generate_trading_plan(rec_data, pattern_results, {})
    assert plan.direction == "观望"
    assert "等待再派发区间破位" in plan.entry_zone


def test_point_and_figure_count_line():
    # 实例化点数图计算器
    calculator = PointAndFigureCalculator(box_size_pct=1.0, reversal_boxes=3)
    
    # 构造点数图数据
    columns = [
        {'low': 98.0, 'high': 102.0, 'start_idx': 0, 'direction': 'up'},
        {'low': 99.0, 'high': 103.0, 'start_idx': 10, 'direction': 'down'},
        {'low': 100.0, 'high': 104.0, 'start_idx': 20, 'direction': 'up'},
        {'low': 102.0, 'high': 106.0, 'start_idx': 30, 'direction': 'down'},
        {'low': 95.0, 'high': 98.0, 'start_idx': 40, 'direction': 'up'},
    ]
    pnf_data = {'columns': columns}
    
    # 构造包含成交量的高精度价格 DataFrame
    dates = pd.date_range("2026-01-01", periods=50)
    data = pd.DataFrame({
        "Open": [100.0] * 50,
        "High": [105.0] * 50,
        "Low": [95.0] * 50,
        "Close": [100.0] * 50,
        "Volume": [1000.0] * 50,
    }, index=dates)
    
    # 运行密集水平计数计算
    res = calculator.calculate_horizontal_count(
        pnf_data=pnf_data,
        accumulation_start=0,
        accumulation_end=4,
        phase="Accumulation Phase A",
        data=data,
        dynamic_threshold=1
    )
    
    # 验证成功找到最大密集线且列数被正确约束在重叠的范围
    assert res['horizontal_count'] > 0
    assert res['horizontal_count'] <= 5


def test_joc_overload_protection():
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    thresholds.JOC_UPPER_SHADOW_RATIO = 0.80
    thresholds.JOC_BODY_RATIO = 0.10
    
    # 构造天量（3倍均量）且留长上影线（收盘不佳）的 JOC Breakout 数据
    dates = pd.date_range("2026-01-01", periods=80)
    data = pd.DataFrame({
        "Open": [100.0] * 80,
        "High": [102.0] * 80,
        "Low": [98.0] * 80,
        "Close": [100.0] * 80,
        "Volume": [1000.0] * 80,
    }, index=dates)
    
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    data["MA20"] = data["Close"].rolling(20, min_periods=1).mean()
    data["MA50"] = data["Close"].rolling(50, min_periods=1).mean()
    data["MA200"] = data["Close"].rolling(200, min_periods=1).mean()
    
    # 制造在 index 75 的假突破天量日
    breakout_idx = 75
    data.loc[dates[breakout_idx], 'Open'] = 100.0
    data.loc[dates[breakout_idx], 'High'] = 110.0
    data.loc[dates[breakout_idx], 'Low'] = 100.0
    data.loc[dates[breakout_idx], 'Close'] = 103.0  # 收盘位置 30% (< 60%)
    data.loc[dates[breakout_idx], 'Volume'] = 5000.0  # 5倍均量
    
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    
    # 1. 验证 孟洪涛 趋势检测器 JOC 向量化模式
    meng_detector = MengTrendDetector(data, config, thresholds)
    meng_detector._detect_trading_range = lambda df, window: {"is_consolidation": True, "high": 102.0, "low": 98.0}
    meng_detector._calculate_adaptive_creek = lambda df, window: 102.0
    
    res_vec = meng_detector._detect_joc_enhanced_vectorized()
    assert res_vec['detected'] is False
    assert res_vec['joc_overload_warning'] is True
    
    # 2. 验证 孟洪涛 趋势检测器 JOC 迭代模式
    res_iter = meng_detector._detect_joc_enhanced_iterative()
    assert res_iter['detected'] is False
    assert res_iter['joc_overload_warning'] is True
    
    # 3. 验证 经典 趋势检测器 JOC 模式
    trend_detector = TrendDetector(data, config, thresholds, None)
    res_trend = trend_detector.detect_joc(lookback=80, trading_range={"high": 102.0, "low": 98.0})
    assert res_trend['detected'] is False
    assert res_trend['joc_overload_warning'] is True
    
    # 4. 验证 推荐引擎拦截 JOC Overload 并提供买入高潮警戒 (观望，0仓位)
    engine = RecommendationEngine()
    rec_data = data.copy()
    rec_data["ATR"] = 2.0
    
    pattern_results = {
        'phase': 'Phase D',
        'joc': {
            'detected': False,
            'joc_overload_warning': True
        }
    }
    
    plan = engine.generate_trading_plan(rec_data, pattern_results, {})
    assert plan.direction == "观望"
    assert "警惕买入高潮" in plan.entry_zone
    assert plan.position_sizing.conservative == "0%"


class MockCache:
    def get_or_compute(self, key, func, *args, **kwargs):
        return func(*args, **kwargs)


def test_sc_bc_bar_color_and_close_position_relaxation():
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    cache = MockCache()
    
    dates = pd.date_range("2026-01-01", periods=80)
    data = pd.DataFrame({
        "Open": [100.0] * 80,
        "High": [100.0] * 80,
        "Low": [100.0] * 80,
        "Close": [100.0] * 80,
        "Volume": [1000.0] * 80,
    }, index=dates)
    
    for i in range(60):
        data.loc[dates[i], ["Open", "High", "Low", "Close"]] = 120.0
        
    sc_idx = 70
    data.loc[dates[sc_idx], "Open"] = 100.0
    data.loc[dates[sc_idx], "High"] = 102.0
    data.loc[dates[sc_idx], "Low"] = 90.0
    data.loc[dates[sc_idx], "Close"] = 101.0
    data.loc[dates[sc_idx], "Volume"] = 5000.0
    
    for i in range(sc_idx + 1, sc_idx + 6):
        data.loc[dates[i], "High"] = 105.0
        
    detector = ReversalDetector(data, config, thresholds, cache)
    res = detector.detect_climax()
    assert res['detected'] is True
    assert res['type'] == 'selling_climax'
    assert res['is_confirmed'] is True
    
    # Positive bar but close position < 40% (e.g. close is near low) -> Rejected
    data.loc[dates[sc_idx], "Open"] = 91.0
    data.loc[dates[sc_idx], "Close"] = 92.0
    detector = ReversalDetector(data, config, thresholds, cache)
    res = detector.detect_climax()
    assert res.get('type') != 'selling_climax'


def test_ar_lookback_swing_extreme_detection():
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    cache = MockCache()
    
    dates = pd.date_range("2026-01-01", periods=50)
    data = pd.DataFrame({
        "Open": [100.0] * 50,
        "High": [100.0] * 50,
        "Low": [100.0] * 50,
        "Close": [100.0] * 50,
        "Volume": [1000.0] * 50,
    }, index=dates)
    
    detector = ReversalDetector(data, config, thresholds, cache)
    climax_res = {
        'detected': True,
        'type': 'selling_climax',
        'date': dates[10],
        'price': 90.0,
        'volume': 5000.0
    }
    
    # Set high prices before dates[16] as strictly increasing
    # and after dates[16] as strictly decreasing to avoid false flat swing highs
    for idx, d in enumerate(dates[11:26]):
        data.loc[d, "High"] = 90.0 + idx
        
    data.loc[dates[16], "High"] = 105.0
    data.loc[dates[17], "High"] = 94.0
    data.loc[dates[18], "High"] = 93.0
    data.loc[dates[19], "High"] = 92.0
    data.loc[dates[20], "High"] = 91.0
    
    detector.data = data
    ar_res = detector.detect_automatic_reaction(climax_res)
    
    assert ar_res['detected'] is True
    assert ar_res['price'] == 105.0
    assert ar_res['date'] == dates[16]


def test_utad_st_symmetry_and_falsification_protection():
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    cache = MockCache()
    
    dates = pd.date_range("2026-01-01", periods=100)
    data = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [100.0] * 100,
        "Low": [100.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [1000.0] * 100,
    }, index=dates)
    
    for i in range(60):
        data.loc[dates[i], ["Open", "High", "Low", "Close"]] = 80.0
        
    data.loc[dates[70], "High"] = 100.0
    data.loc[dates[70], "Volume"] = 5000.0
    
    utad_idx = 80
    data.loc[dates[utad_idx], "High"] = 110.0
    data.loc[dates[utad_idx], "Low"] = 100.0
    data.loc[dates[utad_idx], "Open"] = 100.0
    data.loc[dates[utad_idx], "Close"] = 101.0
    data.loc[dates[utad_idx], "Volume"] = 6000.0
    
    data.loc[dates[utad_idx + 1], "Close"] = 97.0
    data.loc[dates[utad_idx + 2], "Close"] = 97.0
    
    for i in range(utad_idx + 3, utad_idx + 13):
        data.loc[dates[i], "High"] = 105.0
        data.loc[dates[i], "Volume"] = 1000.0
        data.loc[dates[i], "Open"] = 100.0
        data.loc[dates[i], "Close"] = 101.0
        
    detector = ReversalDetector(data, config, thresholds, cache)
    detector._current_phase = "Distribution Phase C"
    utad_res = detector.detect_utad()
    
    assert utad_res['detected'] is True
    assert utad_res['st_confirmed'] is True
    
    engine = RecommendationEngine()
    plan = engine.generate_trading_plan(data, {'phase': 'Distribution Phase C', 'utad': utad_res}, {})
    assert plan.direction != "做多"
    
    data.loc[dates[85], "Volume"] = 4500.0
    detector = ReversalDetector(data, config, thresholds, cache)
    detector._current_phase = "Distribution Phase C"
    utad_res_fail = detector.detect_utad()
    
    assert utad_res_fail['detected'] is True
    assert utad_res_fail['st_confirmed'] is False
    
    plan_falsified = engine.generate_trading_plan(data, {'phase': 'Distribution Phase C', 'utad': utad_res_fail}, {})
    assert plan_falsified.direction == "做多"
    assert "诱多证伪" in plan_falsified.entry_zone
    assert plan_falsified.position_sizing.moderate == "50%"

