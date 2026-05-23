"""Phase 11：延迟门控 / Phase E / VSA 注入 / E2E identify_phase"""
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds
from wyckoff.core.detectors.phase_identifier import PhaseIdentifier
from wyckoff.core.enums import WyckoffPhase
from wyckoff.core.phase_coordinator import PhaseCoordinator
from wyckoff.core.utils import continuous_price_confirmation
from wyckoff.schemas import (
    ClimaxModel,
    EventsModel,
    FtiModel,
    JocModel,
    SpringModel,
    TradingRangeModel,
    WyckoffEventModel,
)


class FakeCache:
    def get_or_compute(self, key, fn, *args, **kwargs):
        return fn(*args, **kwargs)


def _make_base_df(n: int = 120, base_price: float = 20.0) -> pd.DataFrame:
    end = pd.Timestamp('2025-01-31')
    rng = pd.bdate_range(end=end, periods=n)
    np.random.seed(42)
    closes = base_price + np.random.randn(n) * 0.3
    closes = np.clip(closes, base_price * 0.95, base_price * 1.05)
    df = pd.DataFrame({
        'Open': closes * (1 - np.random.uniform(0, 0.005, n)),
        'High': closes * (1 + np.random.uniform(0, 0.01, n)),
        'Low': closes * (1 - np.random.uniform(0, 0.01, n)),
        'Close': closes,
        'Volume': np.random.randint(5_000_000, 10_000_000, n).astype(float),
    }, index=rng)
    df['Volume_MA20'] = df['Volume'].rolling(20, min_periods=1).mean()
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['MA50'] = df['Close'].rolling(50, min_periods=1).mean()
    df['MA200'] = df['Close'].rolling(200, min_periods=1).mean().fillna(df['Close'])
    df['ATR'] = (df['High'] - df['Low']).rolling(14, min_periods=1).mean()
    return df


class TestProvisionalGating(unittest.TestCase):
    def test_sc_pending_does_not_block_sos_without_upthrust(self):
        coord = PhaseCoordinator(MagicMock())
        sw = MagicMock()
        coord.detector = MagicMock(sw_detector=sw)

        coord._apply_strength_signal_gating(
            'Accumulation Phase A (SC待AR确认)',
            spring_res={'detected': False},
            upthrust_res={'detected': False},
            climax_res={'detected': True, 'type': 'selling_climax'},
        )
        sw.block_signal.assert_not_called()

    def test_upthrust_still_blocks_sos_when_provisional(self):
        coord = PhaseCoordinator(MagicMock())
        sw = MagicMock()
        coord.detector = MagicMock(sw_detector=sw)

        coord._apply_strength_signal_gating(
            'Accumulation Phase A (SC待AR确认)',
            spring_res={'detected': False},
            upthrust_res={'detected': True},
            climax_res={'detected': True, 'type': 'selling_climax'},
        )
        sw.block_signal.assert_called_once_with('sos')


class TestPhaseEUpgrade(unittest.TestCase):
    def test_joc_phase_d_upgrades_to_e_on_uptrend(self):
        idx = pd.date_range('2024-01-01', periods=5, freq='D')
        df = pd.DataFrame({'Close': [100, 101, 102, 103, 104]}, index=idx)
        ident = PhaseIdentifier(df, WyckoffConfig(), WyckoffThresholds())
        label, enum, conf = ident._maybe_upgrade_to_phase_e(
            'Accumulation Phase D (积累期突破)', WyckoffPhase.PHASE_D, 0.85
        )
        self.assertIn('Phase E', label)
        self.assertEqual(enum, WyckoffPhase.PHASE_E)
        self.assertGreaterEqual(conf, 0.90)

    def test_continuous_confirmation_helper(self):
        idx = pd.date_range('2024-01-01', periods=5, freq='D')
        df = pd.DataFrame({'Close': [100, 99, 98, 97, 96]}, index=idx)
        self.assertTrue(
            continuous_price_confirmation(df, 3, 'Distribution Phase D')
        )


class TestVsaInjection(unittest.TestCase):
    def test_normalize_vsa_signals(self):
        raw = {
            'no_supply': {'detected': True},
            'no_demand': {'detected': False},
            'stopping_vol': {'detected': False},
        }
        out = PhaseCoordinator._normalize_vsa_signals(raw)
        self.assertTrue(out['is_no_supply'])
        self.assertFalse(out['is_no_demand'])


class TestIdentifyPhaseE2E(unittest.TestCase):
    def test_identify_phase_pipeline_fields(self):
        from wyckoff.core.pattern_detector import WyckoffPatternDetector

        df = _make_base_df(120)
        # 压平波动，降低 Spring/Upthrust 误触发
        mid = df['Close'].mean()
        df['Open'] = mid
        df['High'] = mid * 1.002
        df['Low'] = mid * 0.998
        df['Close'] = mid
        df['Volume'] = 6_000_000

        det = WyckoffPatternDetector(df, WyckoffConfig(), FakeCache())
        result = det.identify_phase()

        self.assertIn('phase', result)
        self.assertIn('events_detected', result)
        events = result['events_detected']
        self.assertIsNotNone(getattr(events, 'vsa_signals', None))
        self.assertIsNotNone(getattr(events, 'coordinator_final_phase', None))
        self.assertIn('identifier_phase', result)


class TestRecollectOnSideFlip(unittest.TestCase):
    def test_recollect_appends_revision_log(self):
        coord = PhaseCoordinator(MagicMock())
        sw = MagicMock()
        coord.detector = MagicMock()
        coord.detector.sw_detector = sw
        coord.detector.detect_sos.return_value = {'detected': False}
        coord.detector.detect_sow.return_value = {'detected': True, 'price': 18.0}
        coord.detector.detect_lps.return_value = {'detected': False}
        coord.detector.detect_lpsy.return_value = {'detected': False}

        events = EventsModel(
            trading_range=TradingRangeModel(
                is_consolidation=True, high=22, low=18, range_pct=0.2,
                duration_days=60, position=0.5, current_price=20,
            ),
            phase_revision_log=[],
        )

        def _safe(model_cls, data):
            return model_cls(**{k: v for k, v in data.items() if k in model_cls.model_fields})

        from wyckoff.schemas import SowModel, SosModel, LpsModel, LpsyModel
        updated = coord._recollect_strength_events(
            events,
            'Distribution Phase C',
            {
                'tr_res': {'high': 22, 'low': 18},
                'spring_res': {'detected': False},
                'upthrust_res': {'detected': True},
                'climax_res': {'detected': True, 'type': 'buying_climax'},
                'joc_res': {},
                'fti_res': {},
            },
            _safe,
        )
        self.assertTrue(any('Phase11' in log for log in updated.phase_revision_log))


if __name__ == '__main__':
    unittest.main()
