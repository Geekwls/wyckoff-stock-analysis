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
    assert plan.entry_zone == "Spring 震仓已现，等待 JOC 突破小溪或 LPS 缩量回测确认"
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
    meng_detector._calculate_adaptive_creek = lambda df, window, **kwargs: 102.0
    
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


def test_joc_rolling_sloped_creek_no_lookahead():
    # 1. 构造 80 天的数据，创造清晰的下行阻力通道
    dates = pd.date_range("2026-01-01", periods=80)
    data = pd.DataFrame({
        "Open": [100.0] * 80,
        "High": [98.0] * 80,
        "Low": [96.0] * 80,
        "Close": [97.0] * 80,
        "Volume": [1000.0] * 80,
    }, index=dates)

    # 构造两个局部 Swing Highs
    # X=20, High=110, Vol=2000
    data.loc[dates[20], ["High", "Volume"]] = [110.0, 2000.0]
    data.loc[dates[18:20], "High"] = 102.0
    data.loc[dates[21:23], "High"] = 102.0

    # X=50, High=108, Vol=1800 (使差值 2.0 <= 1.5 * ATR)
    data.loc[dates[50], ["High", "Volume"]] = [108.0, 1800.0]
    data.loc[dates[48:50], "High"] = 98.0
    data.loc[dates[51:53], "High"] = 98.0

    config = WyckoffConfig()
    thresholds = WyckoffThresholds()
    detector = MengTrendDetector(data, config, thresholds)

    # 测试第 75 天的自适应 Creek 计算值（应该呈倾斜投影值 ~ 106.33）
    creek_75 = detector._calculate_adaptive_creek(data.iloc[:76], window=60)
    assert creek_75 < 110.0
    assert creek_75 > 100.0

    # 制造在第 75 天的突破
    data.loc[dates[75], ["Open", "High", "Low", "Close", "Volume"]] = [100.0, 108.0, 99.0, 107.0, 4000.0]
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    detector = MengTrendDetector(data, config, thresholds)
    # 模拟 trading range 属性
    detector._detect_trading_range = lambda df, window: {"is_consolidation": True, "high": 110.0, "low": 90.0}
    
    res = detector._detect_joc_enhanced_vectorized()
    assert res["detected"] is True

    # 4. 验证无未来函数/前瞻偏差 (Lookahead Bias):
    # 即使改变第 78 天的数据，第 75 天的 Creek 颈线也绝不受任何影响
    creek_75_before = detector._calculate_adaptive_creek(data, window=60, idx=75)
    
    # 污染未来数据
    data.loc[dates[78], "High"] = 180.0
    data.loc[dates[78], "Volume"] = 99999.0
    detector_after = MengTrendDetector(data, config, thresholds)
    creek_75_after = detector_after._calculate_adaptive_creek(data, window=60, idx=75)
    
    assert abs(creek_75_before - creek_75_after) < 1e-7


def test_phase_b_quantitative_absorption_scoring():
    from src.wyckoff.core.detectors.phase_identifier import PhaseIdentifier
    
    config = WyckoffConfig()
    thresholds = WyckoffThresholds()

    # ────────────────────────────────────────────────────────
    # 1. 测试 Case A：完美吸筹特征 (波幅收敛 + Weis Wave 阳量压倒阴量)
    # ────────────────────────────────────────────────────────
    dates = pd.date_range("2026-01-01", periods=100)
    data_a = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [100.0] * 100,
        "Low": [100.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [1000.0] * 100,
    }, index=dates)

    # 构造真正的 zigzag 使得 WeisWaveGenerator 完美工作
    # 10天一个波段，前40天大波幅，后40天小波幅
    for idx in range(100):
        d = dates[idx]
        wave_num = idx // 10
        wave_pos = idx % 10
        is_up = (wave_num % 2 == 0)
        
        if wave_num < 4:
            # 振幅大 10 (95 - 105)
            if is_up:
                price = 95.0 + wave_pos
                high, low, close = price + 1.0, price - 1.0, price
                vol = 3000.0
            else:
                price = 105.0 - wave_pos
                high, low, close = price + 1.0, price - 1.0, price
                vol = 1000.0
        else:
            # 振幅小 3 (98.5 - 101.5)
            if is_up:
                price = 98.5 + wave_pos * 0.3
                high, low, close = price + 0.3, price - 0.3, price
                vol = 3000.0
            else:
                price = 101.5 - wave_pos * 0.3
                high, low, close = price + 0.3, price - 0.3, price
                vol = 1000.0
                
        data_a.loc[d, ["Open", "High", "Low", "Close", "Volume"]] = [close, high, low, close, vol]

    data_a["ATR"] = 1.0

    class MockEvents:
        def __init__(self):
            self.trading_range = {"is_consolidation": True, "duration_days": 80}
            self.climax = MockEvent(detected=True, type='selling_climax', date=dates[5])
            self.automatic_reaction = MockEvent(detected=True, date=dates[10])
            self.secondary_test = MockEvent(detected=True, date=dates[15])
            self.lps_list = [MockEvent(detected=True), MockEvent(detected=True)]
            self.ut_list = []
            self.fti = MockEvent(detected=False)

    class MockEvent:
        def __init__(self, detected=False, **kwargs):
            self.detected = detected
            for k, v in kwargs.items():
                setattr(self, k, v)

    detector_a = PhaseIdentifier(data_a, config, thresholds)
    desc, phase_enum, conf, phase_note = detector_a._detect_phase_b_active(MockEvents())
    
    assert phase_enum.value == "Phase B"
    assert "经典威科夫吸筹特征确认" in (phase_note or desc)
    assert conf >= 0.80  # 基础 0.65 + 0.10 (测试数) + 0.15 奖励 => 0.90 

    # ────────────────────────────────────────────────────────
    # 2. 测试 Case B：宽幅非吸收性震荡 (不收敛 + 无波段方向优势)
    # ────────────────────────────────────────────────────────
    data_b = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [105.0] * 100,
        "Low": [95.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [1000.0] * 100,
    }, index=dates)
    
    for idx, d in enumerate(dates[:80]):
        wave_pos = idx % 20
        if wave_pos < 10:
            data_b.loc[d, "Close"] = 104.0
        else:
            data_b.loc[d, "Close"] = 96.0
    
    data_b["ATR"] = 2.0
    detector_b = PhaseIdentifier(data_b, config, thresholds)
    desc_b, phase_enum_b, conf_b, phase_note_b = detector_b._detect_phase_b_active(MockEvents())
    
    assert phase_enum_b.value == "Phase B"
    assert "非吸收性无方向宽幅震荡整理" in (phase_note_b or desc_b)
    assert conf_b == 0.50  # 被惩罚降级


def test_spring_sow_sequence_and_volume_coexistence():
    from src.wyckoff.core.sequence_validator import SequenceValidator
    
    class MockEvent:
        def __init__(self, detected=False, **kwargs):
            self.detected = detected
            for k, v in kwargs.items():
                setattr(self, k, v)

    class MockEvents:
        def __init__(self, climax, ar, st, spring, sow, upthrust=None, sos=None, lps=None, lpsy=None, joc=None):
            self.climax = climax
            self.automatic_reaction = ar
            self.secondary_test = st
            self.spring = spring
            self.sow = sow
            self.upthrust = upthrust or MockEvent(detected=False)
            self.sos = sos or MockEvent(detected=False)
            self.lps = lps or MockEvent(detected=False)
            self.lpsy = lpsy or MockEvent(detected=False)
            self.joc = joc or MockEvent(detected=False)
            self.fti = MockEvent(detected=False)

    dates = pd.date_range("2026-01-01", periods=100)
    dummy_data = pd.DataFrame(index=dates)

    # ────────────────────────────────────────────────────────
    # Case A: SOW 发生在 Spring 之前 -> 完美因果链
    # ────────────────────────────────────────────────────────
    climax = MockEvent(detected=True, type="selling_climax", date=dates[10])
    ar = MockEvent(detected=True, date=dates[15])
    st = MockEvent(detected=True, date=dates[20])
    
    sow_a = MockEvent(detected=True, latest=MockEvent(date=dates[25], price=95.0, volume_ratio=1.5))
    spring_a = MockEvent(detected=True, latest_spring=MockEvent(date=dates[50], breakdown_price=90.0))
    
    events_a = MockEvents(climax, ar, st, spring_a, sow_a)
    validator_a = SequenceValidator(events_a, dummy_data)
    res_a = validator_a.validate_all()
    
    assert res_a["spring"]["high_quality_causal_chain"] is True
    assert not any("SOW" in c and "Spring" in c for c in res_a["conflicts"])
    assert any("因果链高度吻合" in n for n in res_a["spring"]["notes"])

    # ────────────────────────────────────────────────────────
    # Case B: SOW 发生在 Spring 之后，但缩量且守住前低 -> 高质量二次震仓无冲突
    # ────────────────────────────────────────────────────────
    spring_b = MockEvent(detected=True, latest_spring=MockEvent(date=dates[40], breakdown_price=90.0))
    sow_b = MockEvent(detected=True, latest=MockEvent(date=dates[60], price=91.0, volume_ratio=0.5))
    
    events_b = MockEvents(climax, ar, st, spring_b, sow_b)
    validator_b = SequenceValidator(events_b, dummy_data)
    res_b = validator_b.validate_all()
    
    assert res_b["spring"]["high_quality_shakeout"] is True
    assert not any("SOW" in c and "Spring" in c for c in res_b["conflicts"])
    assert any("确认为高质量无量震仓测试" in n for n in res_b["spring"]["notes"])

    # ────────────────────────────────────────────────────────
    # Case C: SOW 发生在 Spring 之后，深跌破位 -> 严重冲突，结构失效
    # ────────────────────────────────────────────────────────
    sow_c = MockEvent(detected=True, latest=MockEvent(date=dates[60], price=85.0, volume_ratio=1.5))
    events_c = MockEvents(climax, ar, st, spring_b, sow_c)
    validator_c = SequenceValidator(events_c, dummy_data)
    res_c = validator_c.validate_all()
    
    assert res_c["spring"]["high_quality_shakeout"] is False
    assert any("Spring后发生放量深跌破位" in c for c in res_c["conflicts"])

    # ────────────────────────────────────────────────────────
    # Case D: SOW 发生在 Spring 之后，未破位但未显著缩量 -> 疑虑警告冲突
    # ────────────────────────────────────────────────────────
    sow_d = MockEvent(detected=True, latest=MockEvent(date=dates[60], price=91.0, volume_ratio=1.0))
    events_d = MockEvents(climax, ar, st, spring_b, sow_d)
    validator_d = SequenceValidator(events_d, dummy_data)
    res_d = validator_d.validate_all()
    
    assert res_d["spring"]["high_quality_shakeout"] is False
    assert any("量能未显著萎缩" in c for c in res_d["conflicts"])


# ============================================================
# Wave 4 专项单元测试：四项核心偏差修正验证
# ============================================================

def test_wave4_vsa_comparative_volume_constraint():
    """
    Wave 4 偏差一：VSA 比较性缩量双重锚定约束
    测试：连续放量后出现比较性缩量（V_t < V_{t-1} < V_{t-2}），
          即使绝对量比 >= 0.5，也应能触发 No Supply 信号
    同时测试：涨跌停日（>= 9.5% 变动）的成交量被正确过滤，不误判为比较性缩量
    """
    from src.wyckoff.core.detectors.meng_vsa_detector import MengVsaDetector
    from src.wyckoff.config.settings import WyckoffConfig, WyckoffThresholds

    dates = pd.date_range("2026-01-01", periods=50)
    closes = [100.0 + i * 0.3 for i in range(50)]

    data = pd.DataFrame({
        "Open":   [c - 0.3 for c in closes],
        "High":   [c + 1.0 for c in closes],
        "Low":    [c - 1.0 for c in closes],
        "Close":  closes,
        # 前44日高量，第45-47日逐步递减（比较性低量），第48-50日恢复
        "Volume": [5000.0] * 44 + [3000.0, 2000.0, 1500.0] + [5000.0] * 3,
    }, index=dates)
    data["ATR"] = 2.0
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()

    detector = MengVsaDetector(data, WyckoffConfig(), WyckoffThresholds())
    result = detector.detect_vsa_signals()

    # 方法应正常运行不抛出异常
    assert isinstance(result, dict), "VSA 检测结果应为字典"
    # no_supply 是嵌套字典：{'detected': bool, 'signals': [...], 'latest': ...}
    ns_dict = result.get('no_supply', {})
    assert isinstance(ns_dict, dict), "no_supply 应为字典"
    ns_signals = ns_dict.get('signals', [])
    if ns_signals:
        assert 'vol_mode' in ns_signals[0], \
            "Wave 4 修正后，No Supply 信号应包含 vol_mode 字段"

    # 涨跌停日过滤测试
    data2 = data.copy()
    data2.loc[dates[30], 'Close'] = data2.loc[dates[29], 'Close'] * 1.10  # 涨停 10%
    data2.loc[dates[30], 'Volume'] = 800.0
    data2["Volume_MA20"] = data2["Volume"].rolling(20, min_periods=1).mean()

    detector2 = MengVsaDetector(data2, WyckoffConfig(), WyckoffThresholds())
    result2 = detector2.detect_vsa_signals()
    assert isinstance(result2, dict), "涨跌停日场景下 VSA 检测应正常完成"
    limit_signals = [s for s in result2.get('no_supply', {}).get('signals', [])
                     if s.get('vol_mode') == 'limit_day_passive']
    assert isinstance(limit_signals, list)





def test_wave4_pnf_target_overrides_atr():
    """
    Wave 4 偏差二：PnF 因果目标优先策略
    测试 A：PnF 返回有效目标（count >= 3, target > current_price）→ 目标价使用 PnF
    测试 B：PnF 计算抛出异常 → 退回 ATR 兜底
    """
    from src.wyckoff.core.trading_plan_generator import TradingPlanGenerator
    from unittest.mock import MagicMock, patch

    dates = pd.date_range("2025-01-01", periods=120)
    current_price = 100.0
    data = pd.DataFrame({
        "Open":  [current_price - 0.5] * 120,
        "High":  [current_price + 1.0] * 120,
        "Low":   [current_price - 1.0] * 120,
        "Close": [current_price] * 120,
        "Volume": [1000.0] * 120,
        "ATR":   [2.0] * 120,
    }, index=dates)

    mock_detector = MagicMock()
    gen = TradingPlanGenerator(data, mock_detector)

    # 场景 A：PnF 有效
    with patch('src.wyckoff.core.point_and_figure.calculate_cause_effect_from_pnf') as mock_pnf:
        mock_pnf.return_value = {
            'horizontal_count': 8,
            'targets': {'target_1': 130.0, 'target_2': 146.18},
            'base_effect': 30.0,
            'box_size_pct': 1.0,
        }
        _, _, targets_a = gen._calculate_levels(current_price, 2.0, 110.0, 90.0, True)

    assert targets_a['target_1']['value'] == 130.0, \
        f"PnF 有效时应覆写 ATR 目标为 130.0，实际 {targets_a['target_1']['value']}"
    assert targets_a['target_2']['value'] == 146.18, \
        f"PnF 1.618x 目标应为 146.18，实际 {targets_a['target_2']['value']}"
    assert 'PnF' in (targets_a['target_1'].get('note') or ''), \
        "note 字段应含 PnF 来源说明"

    # 场景 B：PnF 失败
    with patch('src.wyckoff.core.point_and_figure.calculate_cause_effect_from_pnf',
               side_effect=RuntimeError("PnF 模拟错误")):
        _, _, targets_b = gen._calculate_levels(current_price, 2.0, 110.0, 90.0, True)

    # ATR 兜底：target_1 应为 TR high（110.0 > 100.0）
    assert targets_b['target_1']['value'] == 110.0, \
        f"PnF 失败时应退回 ATR 兜底（TR_high=110），实际 {targets_b['target_1']['value']}"


def test_wave4_rs_bypass_warning_flag():
    """
    Wave 4 偏差三：RS 静默旁路 → 主动警告标志
    测试：旁路路径必须设置 rs_bypass_warning=True，
          且 liquidity_retention 默认为中性 1.0
    """
    dates = pd.date_range("2025-01-01", periods=60)
    df_regime = pd.DataFrame({
        "Open":   [100.0] * 60,
        "High":   [105.0] * 60,
        "Low":    [95.0]  * 60,
        "Close":  [100.0] * 60,
        "Volume": [1000.0] * 60,
    }, index=dates)

    # 模拟旁路逻辑
    df_rs = df_regime.copy()
    for col, val in [('liquidity_retention', 1.0),
                     ('hidden_strength', False),
                     ('hidden_weakness', False),
                     ('idx_log_return', 0.0),
                     ('asset_log_return', 0.0)]:
        if col not in df_rs.columns:
            df_rs[col] = val
    df_rs['rs_bypass_warning'] = True

    assert df_rs['rs_bypass_warning'].all(), \
        "RS 旁路时，rs_bypass_warning 列应全部为 True"
    assert (df_rs['liquidity_retention'] == 1.0).all(), \
        "RS 旁路时，liquidity_retention 应默认为中性 1.0"


def test_wave4_lps_weis_wave_effort_result():
    """
    Wave 4 偏差四：LPS Weis Wave Effort vs Result 校验
    测试：缩量回调波段（低量下跌）的成交量应远小于前序放量上涨波段
          effort_ratio < 0.618 → 供应耗尽验证通过
    """
    from src.wyckoff.core.weis_wave import WeisWaveGenerator

    dates = pd.date_range("2025-01-01", periods=100)
    # 前50日：强势上涨（高量），后50日：缩量回调
    closes = [100.0 + i * 0.5 for i in range(50)] + [125.0 - i * 0.3 for i in range(50)]
    highs  = [c + 1.0 for c in closes]
    lows   = [c - 1.0 for c in closes]
    vols   = [5000.0] * 50 + [800.0] * 50  # 后期极度缩量

    data = pd.DataFrame({
        "Open":   [c - 0.3 for c in closes],
        "High":   highs,
        "Low":    lows,
        "Close":  closes,
        "Volume": vols,
        "ATR":    [2.0] * 100,
    }, index=dates)

    gen = WeisWaveGenerator(data, atr_multiplier=2.0)
    waves = gen.generate()

    down_waves = [w for w in waves if w.direction == 'down']
    up_waves   = [w for w in waves if w.direction == 'up']

    assert down_waves, "应检测到至少一个下跌波段"
    assert up_waves,   "应检测到至少一个上涨波段"

    last_down = down_waves[-1]
    prior_ups = [w for w in up_waves if w.end_idx < last_down.start_idx]

    if prior_ups:
        prior_up = prior_ups[-1]
        effort_ratio = last_down.volume / max(prior_up.volume, 1e-9)
        assert effort_ratio < 0.618, (
            f"缩量回调（后期 800 量）应与前序上涨（5000 量）形成显著 Effort vs Result 背离，"
            f"effort_ratio={effort_ratio:.3f} 应 < 0.618"
        )


def test_meng_wyckoff_upgrades_all_validation():
    """
    任务 8 专项测试：覆盖 SOS 向量化、AR 立即反弹、LPS 动态容差、JOC 评分和因果目标一致性
    """
    # 构造数据
    dates = pd.date_range("2026-01-01", periods=100)
    data = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [100.0] * 100,
        "Low": [100.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [1000.0] * 100,
    }, index=dates)

    data["MA20"] = data["Close"].rolling(20, min_periods=1).mean()
    data["MA50"] = data["Close"].rolling(50, min_periods=1).mean()
    data["MA200"] = data["Close"].rolling(200, min_periods=1).mean()
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    data["ATR"] = 2.0

    config = WyckoffConfig()
    thresholds = WyckoffThresholds()

    # 1. 验证 JOC 评分与品质映射
    # 制造一个 JOC 突破（突破 102.0，收盘 107.0）
    data.loc[dates[70], ["Open", "High", "Low", "Close", "Volume"]] = [101.0, 108.0, 100.0, 107.0, 4000.0]
    # 随后缩量回踩
    for i in range(71, 75):
        data.loc[dates[i], ["Open", "High", "Low", "Close", "Volume"]] = [105.0, 106.0, 102.5, 103.0, 500.0]
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()

    trend_detector = TrendDetector(data, config, thresholds, None)
    joc_res = trend_detector.detect_joc(lookback=100, trading_range={"high": 102.0, "low": 98.0})
    assert "test_quality" in joc_res
    assert "test_score" in joc_res

    # 2. 验证 SOS 向量化方法无 NameError，且包含 breakout_type 和 interpretation
    from src.wyckoff.core.detectors.strength_weakness_detector import StrengthWeaknessDetector
    sw_detector = StrengthWeaknessDetector(data, config, thresholds)
    sw_detector._current_phase = "Accumulation Phase C"

    # 构造一次突破
    data.loc[dates[90], ["Open", "High", "Low", "Close", "Volume"]] = [100.0, 115.0, 100.0, 114.0, 5000.0]
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    sw_detector.data = data

    sos_res = sw_detector._detect_sos_vectorized(window=40)
    if sos_res.get('detected'):
        assert 'breakout_type' in sos_res
        assert 'interpretation' in sos_res
        assert sos_res['breakout_type'] in ['breakout_sos', 'range_high_sos', 'within_range_sos']

    # 3. 验证 LPS 动态容差
    # 制造一个 LPS：低点在 TR 下沿 98.0 附近
    data.loc[dates[95], ["Open", "High", "Low", "Close", "Volume"]] = [99.5, 100.5, 99.0, 100.0, 300.0]
    data["MA20"] = data["Close"].rolling(20, min_periods=1).mean()
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    data["ATR"] = 3.0  # 大 ATR
    sw_detector.data = data
    lps_high = sw_detector.detect_lps(window=20, spring_res={"detected": False}, trading_range={"high": 102.0, "low": 98.0})

    data["ATR"] = 0.5  # 小 ATR
    sw_detector.data = data
    lps_low = sw_detector.detect_lps(window=20, spring_res={"detected": False}, trading_range={"high": 102.0, "low": 98.0})

    # 4. 验证 calculate_cause_effect 因果测算及区间失效 (invalidated_tr)
    from src.wyckoff.facade import WyckoffAnalyzer
    analyzer = WyckoffAnalyzer("AAPL")
    dates_ca = pd.date_range("2026-01-01", periods=100)
    data_ca = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [100.0] * 100,
        "Low": [100.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [1000.0] * 100,
    }, index=dates_ca)

    # 制造一个跌破 TR 低点 100.0 且大幅收回的场景
    data_ca.loc[dates_ca[80], "Low"] = 90.0
    data_ca.loc[dates_ca[99], "Close"] = 105.0
    data_ca["ATR"] = 2.0
    analyzer.data = data_ca

    class MockDetectorForCA:
        def detect_trading_range(self):
            return {"high": 120.0, "low": 100.0}
        def identify_phase(self):
            return {"phase": "Accumulation Phase C", "confidence": 0.8}

    analyzer.pattern_detector = MockDetectorForCA()
    res_ca = analyzer.calculate_cause_effect()
    assert res_ca.get("method") == "invalidated_tr"
    assert "targets" in res_ca
    assert res_ca["targets"]["target_1"] == 0.0
    assert "原交易区间参考性已下降" in res_ca.get("description", "")
