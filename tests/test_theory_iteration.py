import pytest
import pandas as pd
import numpy as np
from src.wyckoff.core.trading_plan_generator import TradingPlanGenerator
from src.wyckoff.facade import WyckoffAnalyzer
from src.wyckoff.core.reports.section_builders.conclusion_section import ConclusionSection


class DummyPatternDetector:
    def detect_trading_range(self):
        return {"high": 110.0, "low": 90.0}
    
    def identify_phase(self):
        return {"phase": "Unknown", "confidence": 0.5}


def test_plan_generator_early_distribution_intercept():
    """验证 TradingPlanGenerator 在 Phase A/B 派发早期能够 100% 成功拦截所有做空位、目标位并输出统一的绝对观望警告"""
    # 构造 K线数据
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    close = np.linspace(100, 105, 100)
    high = close + 1.0
    low = close - 1.0
    open_ = close - 0.1
    volume = np.ones(100) * 1000000.0
    
    data = pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": volume,
    }, index=dates)
    data["MA20"] = data["Close"].rolling(20, min_periods=1).mean()
    data["MA50"] = data["Close"].rolling(50, min_periods=1).mean()
    data["MA200"] = data["Close"].rolling(200, min_periods=1).mean()
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    data["ATR"] = (data["High"] - data["Low"]).rolling(14, min_periods=1).mean()
    
    detector = DummyPatternDetector()
    generator = TradingPlanGenerator(data, detector)
    
    # 1. 测试在 Phase A 派发初期拦截 (英文大写形式)
    plan_a = generator.generate(phase_str="Distribution Phase A")
    assert plan_a["direction"] == "观望"
    assert plan_a["entry_zone"] == "绝对观望"
    assert plan_a["position_sizing"]["status"] == "绝对观望"
    assert plan_a["position_sizing"]["conservative"] == "0%"
    assert plan_a["position_sizing"]["moderate"] == "0%"
    assert plan_a["position_sizing"]["aggressive"] == "0%"
    assert plan_a["scale_in_triggers"]["observation"]["price"] == 0.0
    assert "等待进入 Phase C/D" in plan_a["scale_in_triggers"]["observation"]["condition"]
    assert "当前处于派发初期（Phase A）" in plan_a["dynamic_warning"]
    
    # 验证止损与目标清零
    assert plan_a["stop_loss"]["conservative"]["value"] == 0.0
    assert "不提供做空建议" in plan_a["stop_loss"]["conservative"]["note"]
    assert plan_a["stop_loss"]["aggressive"]["value"] == 0.0
    assert plan_a["stop_loss"]["atr_dynamic_stop"]["value"] == 0.0
    assert plan_a["targets"]["target_1"]["value"] == 0.0
    assert "不提供做空目标" in plan_a["targets"]["target_1"]["note"]
    assert plan_a["targets"]["target_2"]["value"] == 0.0
    
    # 2. 测试中文 "派发阶段A/B" 拦截形式
    plan_cn = generator.generate(phase_str="派发 阶段A/B")
    assert plan_cn["direction"] == "观望"
    assert plan_cn["entry_zone"] == "绝对观望"
    assert plan_cn["stop_loss"]["conservative"]["value"] == 0.0
    assert plan_cn["targets"]["target_1"]["value"] == 0.0
    
    # 3. 验证非派发早期不受影响 (如 Markup)
    plan_markup = generator.generate(phase_str="Markup Phase C")
    assert plan_markup["direction"] == "做多"
    assert plan_markup["stop_loss"]["conservative"]["value"] > 0.0
    assert plan_markup["targets"]["target_1"]["value"] > 0.0


def test_tr_invalidation_and_cause_effect(monkeypatch):
    """验证跌破拉回情况下的自适应 TR 失效检测与报告中文字样渲染"""
    # 构造价格序列：
    # 设定交易区间的支撑下沿为 100.0，阻力上沿为 120.0
    # 最近 60 日曾跌破 100.0 (跌至 93.0)
    # 但最后一天的收盘价拉回到 108.41 (>= 100.0 * 1.03 = 103.0)
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    close = np.ones(100) * 105.0
    low = np.ones(100) * 104.0
    high = np.ones(100) * 106.0
    
    # 在第 80 天（最近 60 天内），最低价跌至 93.0
    low[80] = 93.0
    close[80] = 94.0
    
    # 最后一天的收盘价为 108.41，低点为 107.0，高点为 109.0
    close[-1] = 108.41
    low[-1] = 107.0
    high[-1] = 109.0
    
    data = pd.DataFrame({
        "Open": close - 0.2, "High": high, "Low": low,
        "Close": close, "Volume": 1000000.0
    }, index=dates)
    data["MA20"] = data["Close"].rolling(20, min_periods=1).mean()
    data["MA50"] = data["Close"].rolling(50, min_periods=1).mean()
    data["MA200"] = data["Close"].rolling(200, min_periods=1).mean()
    data["Volume_MA20"] = data["Volume"].rolling(20, min_periods=1).mean()
    data["ATR"] = (data["High"] - data["Low"]).rolling(14, min_periods=1).mean()
    
    analyzer = WyckoffAnalyzer("600519.SH")
    analyzer.data = data
    
    # Mock pattern_detector 的 detect_trading_range
    class MockDetector:
        def detect_trading_range(self):
            return {"high": 120.0, "low": 100.0}
        def identify_phase(self):
            return {"phase": "Distribution Phase A", "confidence": 0.8}
            
    monkeypatch.setattr(analyzer, "pattern_detector", MockDetector())
    
    # 1. 验证 calculate_cause_effect
    res = analyzer.calculate_cause_effect()
    assert res["method"] == "invalidated_tr"
    assert res["targets"]["target_1"] == 0.0
    assert res["targets"]["target_2"] == 0.0
    assert "原交易区间参考性已下降" in res["description"]
    assert res["tr_low"] == 100.0
    assert res["tr_high"] == 120.0
    assert res["current_price"] == 108.41
    
    # 2. 验证 ConclusionSection 渲染的区间失效中文字样
    class MockGenerator:
        def __init__(self, analyzer):
            self.analyzer = analyzer
            self.data = analyzer.data
            self.config = analyzer.config
            self.symbol = analyzer.symbol
            self.pattern_detector = analyzer.pattern_detector
            self.thresholds = getattr(analyzer, "thresholds", None)

    builder = ConclusionSection(MockGenerator(analyzer))
    # mock ConclusionSection 的 identify_phase 方法以供其他渲染使用
    monkeypatch.setattr(builder, "_get_tr_value", lambda self_obj, key, default=0: 100.0 if key == "low" else 120.0)
    
    phase_res = {"phase": "Distribution Phase A", "confidence": 0.8}
    tr = {"high": 120.0, "low": 100.0, "is_broken": False}
    conflict = {"has_conflict": False}
    quality_data = {"score": 5, "max_score": 10}
    empty_dict = {"detected": False}
    
    report_text = builder.build(
        phase_result=phase_res,
        trading_range=tr,
        cause_effect=res,
        conflict=conflict,
        quality_data=quality_data,
        joc=empty_dict,
        spring=empty_dict,
        sos=empty_dict,
        lps=empty_dict,
        fti=empty_dict,
        upthrust=empty_dict,
        sow=empty_dict,
        lpsy=empty_dict,
        mtf={},
        boring_res={},
        dead_corner={},
        market_env={}
    )
    
    # 检验报告包含预期的中文内容
    assert "点数图 (P&F) 因果测算目标推演 - 暂停测算" in report_text
    assert "原交易区间参考性已下降（已失效）" in report_text
    assert "支撑位 100.00 元曾被跌破，但当前价格已强劲收回至 108.41 元" in report_text
    assert "系统已自适应暂停目标测算，等待新的有效 TR 形成" in report_text
    assert "后续观察指南" in report_text
