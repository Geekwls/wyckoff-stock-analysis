"""Phase 12：Spring normalize 金样本 + SC→Spring→JOC 全链路"""
import unittest

import numpy as np
import pandas as pd

from wyckoff.config.settings import WyckoffConfig
from wyckoff.core.pattern_detector import WyckoffPatternDetector
from wyckoff.core.phase_coordinator import (
    _normalize_spring_event,
    _normalize_upthrust_event,
)
from wyckoff.schemas import SpringModel, UpthrustModel


class FakeCache:
    def get_or_compute(self, key, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def _make_base_df(n: int = 150, base: float = 20.0) -> pd.DataFrame:
    end = pd.Timestamp('2025-06-30')
    idx = pd.bdate_range(end=end, periods=n)
    np.random.seed(7)
    close = np.full(n, base)
    df = pd.DataFrame({
        'Open': close * 0.998,
        'High': close * 1.008,
        'Low': close * 0.992,
        'Close': close,
        'Volume': np.full(n, 6_000_000.0),
    }, index=idx)
    df['Volume_MA20'] = df['Volume'].rolling(20, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['MA50'] = df['Close'].rolling(50, min_periods=1).mean()
    df['MA200'] = df['Close'].rolling(200, min_periods=1).mean().fillna(df['Close'])
    df['ATR'] = (df['High'] - df['Low']).rolling(14, min_periods=1).mean().clip(lower=0.05)
    return df


def _inject_tr_box(df: pd.DataFrame, low: float, high: float, start: int, end: int) -> pd.DataFrame:
    """在 [start:end] 注入横盘 TR。"""
    out = df.copy()
    span = out.iloc[start:end]
    mid = (low + high) / 2
    out.loc[span.index, 'Open'] = mid
    out.loc[span.index, 'High'] = high
    out.loc[span.index, 'Low'] = low
    out.loc[span.index, 'Close'] = mid
    out.loc[span.index, 'Volume'] = 5_000_000
    return out


def _inject_sc(df: pd.DataFrame, pos: int, sc_low: float) -> pd.DataFrame:
    out = df.copy()
    idx = out.index[pos]
    vol_ma = out.loc[idx, 'Volume_MA20']
    out.loc[idx, 'Open'] = sc_low * 1.08
    out.loc[idx, 'High'] = sc_low * 1.10
    out.loc[idx, 'Low'] = sc_low
    out.loc[idx, 'Close'] = sc_low * 1.02
    out.loc[idx, 'Volume'] = vol_ma * 3.5
    return out


def _inject_spring(df: pd.DataFrame, pos: int, support: float) -> pd.DataFrame:
    """Spring：跌破支撑后 2 日内收回（孟氏 5  filter 友好）。"""
    out = df.copy()
    b_idx = out.index[pos]
    r_idx = out.index[pos + 2]
    b_vol = out.loc[b_idx, 'Volume_MA20'] * 0.7
    r_vol = out.loc[b_idx, 'Volume_MA20'] * 1.4

    spring_low = support * 0.975
    out.loc[b_idx, 'Open'] = support * 1.01
    out.loc[b_idx, 'High'] = support * 1.02
    out.loc[b_idx, 'Low'] = spring_low
    out.loc[b_idx, 'Close'] = support * 0.995
    out.loc[b_idx, 'Volume'] = b_vol

    out.loc[r_idx, 'Open'] = support * 0.99
    out.loc[r_idx, 'High'] = support * 1.04
    out.loc[r_idx, 'Low'] = support * 0.985
    out.loc[r_idx, 'Close'] = support * 1.03
    out.loc[r_idx, 'Volume'] = r_vol
    return out


def _inject_joc(df: pd.DataFrame, pos: int, creek: float) -> pd.DataFrame:
    out = df.copy()
    idx = out.index[pos]
    vol_ma = out.loc[idx, 'Volume_MA20']
    out.loc[idx, 'Open'] = creek * 0.985
    out.loc[idx, 'High'] = creek * 1.07
    out.loc[idx, 'Low'] = creek * 0.980
    out.loc[idx, 'Close'] = creek * 1.055
    out.loc[idx, 'Volume'] = vol_ma * 2.0
    return out


class TestSpringNormalize(unittest.TestCase):
    def test_meng_spring_dict_validates_as_spring_model(self):
        raw = {
            'detected': True,
            'latest_spring': {
                'date': '2024-06-01',
                'breakdown_price': 18.2,
                'support_level': 18.5,
                'recovery_price': 19.1,
                'recovery_days': 2,
                'vol_ratio': 1.6,
                'spring_type': 3,
                'lifecycle_status': 'confirmed',
            },
        }
        normalized = _normalize_spring_event(raw)
        model = SpringModel(**normalized)
        self.assertTrue(model.detected)
        self.assertIsNotNone(model.latest_spring)
        self.assertEqual(model.latest_spring.volume_ratio, 1.6)
        self.assertEqual(model.latest_spring.breakdown_date, '2024-06-01')

    def test_signals_list_also_normalized(self):
        raw = {
            'detected': True,
            'signals': [{
                'date': pd.Timestamp('2024-06-01'),
                'breakdown_price': 18.0,
                'support_level': 18.5,
                'recovery_price': 19.0,
                'recovery_days': 1,
                'vol_ratio': 1.2,
            }],
        }
        model = SpringModel(**_normalize_spring_event(raw))
        self.assertEqual(len(model.signals), 1)
        self.assertEqual(model.signals[0].volume_ratio, 1.2)


class TestUpthrustNormalize(unittest.TestCase):
    def test_meng_upthrust_dict_validates(self):
        raw = {
            'detected': True,
            'latest_upthrust': {
                'date': '2024-06-02',
                'breakout_price': 22.5,
                'resistance_level': 22.0,
                'rejection_price': 21.4,
                'rejection_days': 2,
                'close_position': 80,
                'vol_ratio': 1.3,
            },
        }
        model = UpthrustModel(**_normalize_upthrust_event(raw))
        self.assertTrue(model.detected)
        self.assertAlmostEqual(model.latest_upthrust.close_from_high, 0.8, places=2)


class TestGoldenAccumulationPipeline(unittest.TestCase):
    def _build_golden_df(self) -> pd.DataFrame:
        tr_low, tr_high = 18.5, 21.5
        df = _make_base_df(150, base=20.0)
        df = _inject_tr_box(df, tr_low, tr_high, 30, 120)
        df = _inject_sc(df, 35, sc_low=17.8)
        df = _inject_spring(df, 100, support=tr_low)
        df = _inject_joc(df, 145, creek=tr_high)
        return df

    def test_collect_all_events_no_pydantic_error(self):
        df = self._build_golden_df()
        det = WyckoffPatternDetector(df, WyckoffConfig(), FakeCache())
        events = det.phase_coordinator.collect_all_events()
        self.assertIsNotNone(events.trading_range)
        self.assertIsNotNone(events.vsa_signals)

    def test_identify_phase_accumulation_structure(self):
        df = self._build_golden_df()
        det = WyckoffPatternDetector(df, WyckoffConfig(), FakeCache())
        result = det.identify_phase()
        self.assertIn('phase', result)
        phase = result['phase']
        events = result['events_detected']
        # 金样本：至少检测到 Spring 或 JOC 之一，且阶段为吸筹相关
        has_spring = events.spring and events.spring.detected
        has_joc = events.joc and events.joc.detected
        self.assertTrue(has_spring or has_joc, 'golden sample should detect Spring or JOC')
        self.assertTrue(
            'Accumulation' in phase or 'Markup' in phase or 'Phase C' in phase or 'Phase D' in phase,
            f'unexpected phase: {phase}',
        )
