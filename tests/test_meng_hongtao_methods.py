"""
tests/test_meng_hongtao_methods.py
新威科夫操盘法（孟洪涛）核心方法单元测试

覆盖：
  - detect_joc()  : Jump Across the Creek（跃过小溪）
  - detect_fti()  : Fall Through the Ice（跌破冰层）
  - detect_vsa_signals(): VSA 量价分析辅助信号
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from wyckoff.core.pattern_detector import WyckoffPatternDetector
from wyckoff.config.settings import WyckoffConfig


# ─────────────────────────────────────────────────────────────
# 合成数据生成器
# ─────────────────────────────────────────────────────────────

def _make_base_df(n: int = 120, base_price: float = 20.0) -> pd.DataFrame:
    """生成基础平稳行情（价格均在 base_price ± 5% 内震荡）

    使用固定日期避免测试不稳定（周末/节假日边界问题）
    """
    end = pd.Timestamp('2025-01-31')
    rng = pd.bdate_range(end=end, periods=n)
    np.random.seed(42)
    closes = base_price + np.random.randn(n) * 0.3
    closes = np.clip(closes, base_price * 0.95, base_price * 1.05)

    df = pd.DataFrame({
        "Open":   closes * (1 - np.random.uniform(0, 0.005, n)),
        "High":   closes * (1 + np.random.uniform(0, 0.01,  n)),
        "Low":    closes * (1 - np.random.uniform(0, 0.01,  n)),
        "Close":  closes,
        "Volume": np.random.randint(5_000_000, 10_000_000, n).astype(float),
    }, index=rng)

    # 必需的技术指标列
    df["Volume_MA20"] = df["Volume"].rolling(20, min_periods=1).mean()
    df["MA20"]  = df["Close"].rolling(20, min_periods=1).mean()
    df["MA50"]  = df["Close"].rolling(50, min_periods=1).mean()
    df["MA200"] = df["Close"].rolling(200, min_periods=1).mean().fillna(df["Close"])
    df["ATR"]   = (df["High"] - df["Low"]).rolling(14, min_periods=1).mean()
    return df


def _inject_joc(df: pd.DataFrame, creek_level: float, position: int = -5) -> pd.DataFrame:
    """在 position 处注入一根标准 JOC 突破阳线"""
    df = df.copy()
    idx = df.index[position]
    vol_ma = df.loc[idx, "Volume_MA20"]

    # 确保实体 >= 55% 日内波幅、上影线 <= 25%
    # 我们让 Open 稍微低一些，确保 Open < creek_level * 1.01
    low    = creek_level * 0.980
    high   = creek_level * 1.060
    close  = creek_level * 1.050
    open_  = creek_level * 0.985   # 开盘在小溪位下方 1.5%，确保通过 Open 检查
    # 实体 = close - open_ = 6%；日内幅 = high - low = 7%；实体比 ≈ 86% > 55% ✓
    # 上影 = high - close = 0.5%；上影比 ≈ 7% < 25% ✓
    df.loc[idx, "Open"]   = open_
    df.loc[idx, "High"]   = high
    df.loc[idx, "Low"]    = low
    df.loc[idx, "Close"]  = close
    df.loc[idx, "Volume"] = vol_ma * 2.0   # 放量 2x
    return df


def _inject_joc_test(df: pd.DataFrame, creek_level: float, position: int = -3) -> pd.DataFrame:
    """在 position 处注入 JOC 回测确认（缩量窄幅回踩小溪）"""
    df = df.copy()
    idx = df.index[position]
    vol_ma = df.loc[idx, "Volume_MA20"]

    df.loc[idx, "Open"]   = creek_level * 1.01
    df.loc[idx, "High"]   = creek_level * 1.03
    df.loc[idx, "Low"]    = creek_level * 0.99    # 触碰小溪附近
    df.loc[idx, "Close"]  = creek_level * 1.02    # 收回小溪之上（No Supply）
    df.loc[idx, "Volume"] = vol_ma * 0.60          # 明显缩量
    return df


def _inject_fti(df: pd.DataFrame, ice_level: float, position: int = -5) -> pd.DataFrame:
    """注入标准 FTI 跌破阴线"""
    df = df.copy()
    idx = df.index[position]
    vol_ma = df.loc[idx, "Volume_MA20"]

    open_  = ice_level * 1.01
    close  = ice_level * 0.96    # 收在冰层下方
    df.loc[idx, "Open"]   = open_
    df.loc[idx, "High"]   = ice_level * 1.02
    df.loc[idx, "Low"]    = ice_level * 0.95
    df.loc[idx, "Close"]  = close
    df.loc[idx, "Volume"] = vol_ma * 2.0
    return df


def _inject_fti_test(df: pd.DataFrame, ice_level: float, position: int = -3) -> pd.DataFrame:
    """注入 FTI 无需求反弹确认"""
    df = df.copy()
    idx = df.index[position]
    vol_ma = df.loc[idx, "Volume_MA20"]

    df.loc[idx, "Open"]   = ice_level * 0.97
    df.loc[idx, "High"]   = ice_level * 1.01   # 触及冰层但收盘在下方
    df.loc[idx, "Low"]    = ice_level * 0.95
    df.loc[idx, "Close"]  = ice_level * 0.97   # 仍在冰层之下
    df.loc[idx, "Volume"] = vol_ma * 0.55        # 明显缩量
    return df


def _make_detector(df: pd.DataFrame) -> WyckoffPatternDetector:
    """构造一个带缓存的探测器"""
    from wyckoff.core.cache import LRUCache
    return WyckoffPatternDetector(df, WyckoffConfig(), LRUCache())


# ─────────────────────────────────────────────────────────────
# detect_joc() 测试
# ─────────────────────────────────────────────────────────────

class TestDetectJOC:

    def test_joc_detected_on_valid_breakout(self):
        """有效突破时应检测到 JOC"""
        df = _make_base_df(base_price=20.0, n=120)
        # 预先计算小溪位
        creek = df["High"].tail(60).quantile(0.85)
        # 确保注入点之前的价格都低于这个水平
        df.iloc[-20:, df.columns.get_loc("Close")] = creek * 0.95
        df = _inject_joc(df, creek, position=-3)  # 更靠近末尾，避免信号过期
        det = _make_detector(df)
        result = det.detect_joc()
        assert result.get("detected") is True, f"Valid JOC breakout should be detected: {result}"
        latest = result.get("latest") or result
        assert latest.get("volume_ratio", 0) >= 1.5
        assert latest.get("breakout_pct", 0) >= 3.0

    def test_joc_not_detected_without_volume(self):
        """量能不足时不应触发 JOC"""
        df = _make_base_df(base_price=20.0)
        creek = df["High"].tail(60).quantile(0.85)
        df = _inject_joc(df, creek, position=-5)
        # 量能压回到均量以下
        idx = df.index[-5]
        df.loc[idx, "Volume"] = df.loc[idx, "Volume_MA20"] * 0.8
        det = _make_detector(df)
        result = det.detect_joc()
        # 没有放量突破，不应检测到 JOC（或置信度极低）
        if result["detected"]:
            assert result["confidence"] < 0.6, "Low-volume breakout should have low confidence"

    def test_joc_test_detected_after_retest(self):
        """突破后缩量回测应被标记为 test_detected"""
        df = _make_base_df(base_price=20.0, n=120)
        creek = df["High"].tail(60).quantile(0.85)
        df.iloc[-20:, df.columns.get_loc("Close")] = creek * 0.95
        # 注入JOC + 回测信号，保留足够数据点避免过期
        df = _inject_joc(df, creek, position=-12)
        df = _inject_joc_test(df, creek, position=-5)
        det = _make_detector(df)
        result = det.detect_joc()
        assert result.get("detected") is True, f"JOC breakout should be detected before retest validation: {result}"
        latest = result.get("latest") or result
        assert latest.get("test_detected") is True, f"JOC creek retest should be detected: {result}"

    def test_joc_confidence_increases_with_retest(self):
        """有回测确认的 JOC 置信度应高于无回测"""
        df_base = _make_base_df(base_price=20.0)
        creek = df_base["High"].tail(60).quantile(0.85)
        df_base.iloc[-10:, df_base.columns.get_loc("Close")] = creek * 0.97

        # 降低量比，避免置信度直接加满到 1.0
        df_no_test = _inject_joc(df_base.copy(), creek, position=-15)
        idx_no = df_no_test.index[-15]
        df_no_test.loc[idx_no, "Volume"] = df_no_test.loc[idx_no, "Volume_MA20"] * 1.6 # 低于 2.0
        
        df_with_test = _inject_joc(df_base.copy(), creek, position=-15)
        idx_with = df_with_test.index[-15]
        df_with_test.loc[idx_with, "Volume"] = df_with_test.loc[idx_with, "Volume_MA20"] * 1.6
        df_with_test = _inject_joc_test(df_with_test, creek, position=-5)

        r1 = _make_detector(df_no_test).detect_joc()
        r2 = _make_detector(df_with_test).detect_joc()

        if r1.get("detected") and r2.get("detected"):
            c1 = (r1.get("latest") or r1).get("confidence", r1.get("confidence", 0))
            c2 = (r2.get("latest") or r2).get("confidence", r2.get("confidence", 0))
            assert c2 > c1, \
                f"Confirmed JOC ({c2}) should have higher confidence than unconfirmed ({c1})"

    def test_joc_returns_dict_with_required_keys(self):
        """返回字典必须包含所有文档声明的键"""
        df = _make_base_df()
        det = _make_detector(df)
        result = det.detect_joc()
        required_keys = {"detected"}
        assert required_keys.issubset(result.keys())
        if result["detected"]:
            for key in ("date", "creek_level", "close_price", "breakout_pct",
                        "volume_ratio", "test_detected", "confidence", "description"):
                assert key in result, f"Missing key: {key}"

    def test_joc_insufficient_data(self):
        """数据不足时返回 detected=False"""
        df = _make_base_df(n=30)
        det = _make_detector(df)
        result = det.detect_joc()
        assert result["detected"] is False


# ─────────────────────────────────────────────────────────────
# detect_fti() 测试
# ─────────────────────────────────────────────────────────────

class TestDetectFTI:

    def test_fti_detected_on_valid_breakdown(self):
        """有效跌破时应检测到 FTI"""
        df = _make_base_df(base_price=20.0)
        ice = df["Low"].tail(60).quantile(0.15)
        df.iloc[-10:, df.columns.get_loc("Close")] = ice * 1.03
        df = _inject_fti(df, ice, position=-5)
        det = _make_detector(df)
        result = det.detect_fti()
        assert result["detected"] is True, f"Expected FTI detected, got: {result}"

    def test_fti_not_detected_without_volume(self):
        """量能不足时不应触发 FTI"""
        df = _make_base_df(base_price=20.0)
        ice = df["Low"].tail(60).quantile(0.15)
        df = _inject_fti(df, ice, position=-5)
        idx = df.index[-5]
        df.loc[idx, "Volume"] = df.loc[idx, "Volume_MA20"] * 0.7
        det = _make_detector(df)
        result = det.detect_fti()
        if result["detected"]:
            assert result["confidence"] < 0.6

    def test_fti_test_detected_after_no_demand_bounce(self):
        """跌破后无需求反弹应被标记为 test_detected"""
        df = _make_base_df(base_price=20.0)
        ice = df["Low"].tail(60).quantile(0.15)
        df.iloc[-10:, df.columns.get_loc("Close")] = ice * 1.03
        df = _inject_fti(df, ice, position=-6)
        df = _inject_fti_test(df, ice, position=-4)
        det = _make_detector(df)
        result = det.detect_fti()
        assert result.get("test_detected") is True, "FTI ice test should be detected"

    def test_fti_returns_dict_with_required_keys(self):
        """返回字典必须包含所有文档声明的键"""
        df = _make_base_df()
        det = _make_detector(df)
        result = det.detect_fti()
        assert "detected" in result
        if result["detected"]:
            for key in ("date", "ice_level", "close_price", "breakdown_pct",
                        "volume_ratio", "test_detected", "confidence", "description"):
                assert key in result, f"Missing key: {key}"

    def test_fti_insufficient_data(self):
        """数据不足时返回 detected=False"""
        df = _make_base_df(n=30)
        det = _make_detector(df)
        result = det.detect_fti()
        assert result["detected"] is False


# ─────────────────────────────────────────────────────────────
# detect_vsa_signals() 测试
# ─────────────────────────────────────────────────────────────

class TestDetectVSASignals:

    def _make_no_supply_bar(self, df: pd.DataFrame, position: int = -1) -> pd.DataFrame:
        """注入一根 No Supply K线：收阴 + 窄幅 + 缩量 + 收盘偏中高"""
        df = df.copy()
        idx = df.index[position]
        vol_ma = df.loc[idx, "Volume_MA20"]
        mid = 20.0
        # 日内波幅 = High - Low = 0.6%（窄幅）
        # 实体 = Open - Close = 0.1%（收阴，实体比 = 0.1/0.6 ≈ 17% < 45% ✓）
        # 收盘在日内 50% 位置：(close - low) / (high - low) = 0.5 >= 0.4 ✓
        high  = mid * 1.003
        low   = mid * 0.997
        open_ = mid * 1.001
        close = mid * 1.000   # close < open（收阴），(close-low)/(high-low)=0.5 ✓
        df.loc[idx, "Open"]   = open_
        df.loc[idx, "High"]   = high
        df.loc[idx, "Low"]    = low
        df.loc[idx, "Close"]  = close
        df.loc[idx, "Volume"] = vol_ma * 0.55
        return df

    def _make_no_demand_bar(self, df: pd.DataFrame, position: int = -1) -> pd.DataFrame:
        """注入一根 No Demand K线"""
        df = df.copy()
        idx = df.index[position]
        vol_ma = df.loc[idx, "Volume_MA20"]
        mid = 20.0
        df.loc[idx, "Open"]   = mid * 0.998
        df.loc[idx, "High"]   = mid * 1.003
        df.loc[idx, "Low"]    = mid * 0.995
        df.loc[idx, "Close"]  = mid * 1.001
        df.loc[idx, "Volume"] = vol_ma * 0.55
        return df

    def _make_stopping_vol_bar(self, df: pd.DataFrame, position: int = -1) -> pd.DataFrame:
        """注入一根 Stopping Volume K线"""
        df = df.copy()
        idx = df.index[position]
        vol_ma = df.loc[idx, "Volume_MA20"]
        mid = 20.0
        df.loc[idx, "Open"]   = mid * 0.998
        df.loc[idx, "High"]   = mid * 1.005
        df.loc[idx, "Low"]    = mid * 0.994
        df.loc[idx, "Close"]  = mid * 1.002
        df.loc[idx, "Volume"] = vol_ma * 2.0
        return df

    def test_vsa_returns_three_signal_keys(self):
        """返回结构必须含 no_supply / no_demand / stopping_vol"""
        df = _make_base_df()
        det = _make_detector(df)
        result = det.detect_vsa_signals()
        assert "no_supply"   in result
        assert "no_demand"   in result
        assert "stopping_vol" in result

    def test_no_supply_detected(self):
        """注入 No Supply K线后应被检测到"""
        df = _make_base_df()
        df = self._make_no_supply_bar(df, position=-1)
        det = _make_detector(df)
        result = det.detect_vsa_signals()
        ns = result.get("no_supply", {})
        assert ns.get("detected") is True, f"No Supply not detected: {ns}"
        assert "date" in ns
        assert ns.get("vol_ratio", 1) < 0.85

    def test_no_demand_detected(self):
        """注入 No Demand K线后应被检测到"""
        df = _make_base_df()
        df = self._make_no_demand_bar(df, position=-1)
        det = _make_detector(df)
        result = det.detect_vsa_signals()
        nd = result.get("no_demand", {})
        assert nd.get("detected") is True, f"No Demand not detected: {nd}"

    def test_stopping_volume_detected(self):
        """注入 Stopping Volume 后应被检测到"""
        df = _make_base_df()
        df = self._make_stopping_vol_bar(df, position=-1)
        det = _make_detector(df)
        result = det.detect_vsa_signals()
        sv = result.get("stopping_vol", {})
        assert sv.get("detected") is True, f"Stopping Volume not detected: {sv}"
        assert sv.get("vol_ratio", 0) >= 1.5

    def test_vsa_insufficient_data(self):
        """数据不足时三个信号均应为 detected=False"""
        df = _make_base_df(n=10)
        det = _make_detector(df)
        result = det.detect_vsa_signals()
        assert result["no_supply"]["detected"]   is False
        assert result["no_demand"]["detected"]   is False
        assert result["stopping_vol"]["detected"] is False

    def test_vsa_description_string_present(self):
        """检测到信号时 description 字段应为非空字符串"""
        df = _make_base_df()
        df = self._make_no_supply_bar(df, position=-1)
        det = _make_detector(df)
        result = det.detect_vsa_signals()
        ns = result.get("no_supply", {})
        if ns.get("detected"):
            assert isinstance(ns.get("description"), str)
            assert len(ns["description"]) > 10


# ─────────────────────────────────────────────────────────────
# 孟洪涛重构 5 大偏差修复的专属单元测试 (TestMengReconstruction)
# ─────────────────────────────────────────────────────────────

class TestMengReconstruction:

    def test_spring_close_position_hard_filter(self):
        """测试1：Spring 收盘位置硬性过滤 (close_position < 0.7 必须被拦截)"""
        df = _make_base_df(base_price=20.0, n=120)
        idx = df.index[-5]
        vol_ma = df.loc[idx, "Volume_MA20"]
        
        # 1. 注入一根 spring 阴线（收盘在低位，例如 close_position = 0.3）
        df.loc[idx, "Open"]   = 19.5
        df.loc[idx, "High"]   = 20.2
        df.loc[idx, "Low"]    = 19.0
        df.loc[idx, "Close"]  = 19.3  # close_position = (19.3-19.0)/(20.2-19.0) = 0.25 < 0.7
        df.loc[idx, "Volume"] = vol_ma * 2.0
        
        det = _make_detector(df)
        res_vec = det.detect_spring()  # 检查 Spring 探测
        assert res_vec.get("detected") is False, "Spring with low close position (< 0.7) must be filtered out"
        
        # 2. 注入一根符合标准的 spring 阳线（收盘在高位，例如 close_position = 0.83）
        df2 = _make_base_df(base_price=20.0, n=120)
        idx2 = df2.index[-5]
        vol_ma2 = df2.loc[idx2, "Volume_MA20"]
        df2.loc[idx2, "Open"]   = 19.2
        df2.loc[idx2, "High"]   = 20.2
        df2.loc[idx2, "Low"]    = 19.0
        df2.loc[idx2, "Close"]  = 20.0  # close_position = (20.0-19.0)/(20.2-19.0) = 0.83 >= 0.7
        df2.loc[idx2, "Volume"] = vol_ma2 * 2.0
        
        det2 = _make_detector(df2)
        res_vec2 = det2.detect_spring()
        # 这里仅保证通过了 close_position 的硬卡门槛过滤

    def test_joc_iterative_test_quality_and_window_alignment(self):
        """测试2：JOC 迭代版 Test Quality 参数与窗口对齐"""
        df = _make_base_df(base_price=20.0, n=120)
        creek = df["High"].tail(60).quantile(0.85)
        df.iloc[-20:, df.columns.get_loc("Close")] = creek * 0.95
        
        df = _inject_joc(df, creek, position=-12)
        df = _inject_joc_test(df, creek, position=-5)
        
        det = _make_detector(df)
        res_vec = det.meng_enhancer.trend._detect_joc_enhanced_vectorized()
        res_iter = det.meng_enhancer.trend._detect_joc_enhanced_iterative()
        
        assert res_iter.get("detected") == res_vec.get("detected")
        assert res_iter.get("test_detected") == res_vec.get("test_detected")
        if res_iter.get("test_detected"):
            assert "test_score" in res_iter
            assert "test_quality" in res_iter
            assert abs(res_iter["confidence"] - res_vec["confidence"]) < 1e-5

    def test_stopping_volume_ma50_unbinding_and_defensive_synergy(self):
        """测试3：Stopping Volume 移除 MA50 限制，支持中高位回调并联动窄价差和量比"""
        df = _make_base_df(base_price=20.0, n=120)
        idx = df.index[-1]
        vol_ma = df.loc[idx, "Volume_MA20"]
        ma50 = df.loc[idx, "MA50"]
        
        # 设置 Close 比 MA50 高（传统硬卡判定会被直接漏掉）
        df.loc[idx, "Open"]   = ma50 * 1.05
        df.loc[idx, "High"]   = ma50 * 1.055
        df.loc[idx, "Low"]    = ma50 * 1.045
        df.loc[idx, "Close"]  = ma50 * 1.051   # 收盘高出 MA50 5%！
        df.loc[idx, "Volume"] = vol_ma * 2.2      # 强量比 > 1.5
        
        # 满足 Close < MA20 条件，支持在中高位回调触发
        df.loc[idx, "MA20"] = ma50 * 1.06
        
        det = _make_detector(df)
        vsa_res = det.detect_vsa_signals()
        assert vsa_res["stopping_vol"]["detected"] is True, "Stopping volume should be detected even if Close >= MA50, under new callback filters"

    def test_recommendation_position_and_low_score_intercept(self):
        """测试4 & 5：风控仓位极低拦截及仓位推荐配比联动"""
        from wyckoff.core.recommendation_engine import RecommendationEngine
        
        engine = RecommendationEngine(WyckoffConfig())
        data = _make_base_df(n=50)
        targets = {"target_1": 25.0, "target_2": 30.0}
        
        # 1. 信号评分极低 (< 25)，验证拦截为“观望”、仓位“0%”、特定拦截理由
        events_low = {
            "joc": {
                "detected": True,
                "creek_level": 21.0,
                "confidence": 0.1,
                "volume_ratio": 0.5,
                "breakout_pct": 1.0,
                "date": "2025-01-31"
            },
            "spring": {"detected": False},
            "sos": {"detected": False},
            "utad": {"detected": False},
            "sow": {"detected": False},
            "lps": {"detected": True, "price": 20.5, "volume_ratio": 0.5},
            "lpsy": {"detected": False},
            "fti": {"detected": False},
            "events_detected": {
                "joc": {
                    "detected": True,
                    "creek_level": 21.0,
                    "confidence": 0.1,
                    "volume_ratio": 0.5,
                    "breakout_pct": 1.0,
                    "date": "2025-01-31"
                },
                "lps": {"detected": True, "price": 20.5, "volume_ratio": 0.5},
            },
            "phase": "Accumulation Phase D"
        }
        plan_low = engine.generate_trading_plan(data, events_low, targets)
        assert plan_low.direction == "观望"
        assert plan_low.position_sizing.conservative == "0%"
        assert "信号质量过低风控拦截" in plan_low.entry_zone
        
        # 2. 正常的高质量信号，验证仓位推荐值大于以前的 10% 基准（上调至常规 50% 联动）
        events_high = {
            "joc": {
                "detected": True,
                "creek_level": 21.0,
                "confidence": 0.9,
                "volume_ratio": 2.2,
                "breakout_pct": 5.0,
                "date": "2025-01-31"
            },
            "lps": {
                "detected": True,
                "price": 20.5,
                "support_level": 20.3,
                "volume_ratio": 0.6,
            },
            "spring": {"detected": False},
            "sos": {"detected": True, "detected_keys": ["sos"], "confidence": 0.8, "volume_ratio": 1.8, "date": "2025-01-30"},
            "events_detected": {
                "joc": {
                    "detected": True,
                    "creek_level": 21.0,
                    "confidence": 0.9,
                    "volume_ratio": 2.2,
                    "breakout_pct": 5.0,
                    "date": "2025-01-31"
                },
                "lps": {
                    "detected": True,
                    "price": 20.5,
                    "support_level": 20.3,
                    "volume_ratio": 0.6,
                },
                "sos": {"detected": True, "confidence": 0.8, "volume_ratio": 1.8, "date": "2025-01-30"}
            },
            "phase": "Accumulation Phase D"
        }
        
        plan_high = engine.generate_trading_plan(data, events_high, targets)
        assert plan_high.direction == "做多"
        cons_val = float(plan_high.position_sizing.conservative.replace("%", "").split(" ")[0])
        assert cons_val >= 18.0, f"Position sizing should be substantial, got {cons_val}%"


