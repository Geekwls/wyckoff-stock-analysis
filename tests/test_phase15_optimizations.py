"""Phase 15：威科夫审查优化 — breakout bug / JOC门控 / 序列校验 / 旁路同源"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd

from wyckoff.core.breakout_analyzer import BreakoutAnalyzer
from wyckoff.core.detectors.meng_trend_detector import MengTrendDetector
from wyckoff.core.detectors.reversal_detector import ReversalDetector
from wyckoff.core.event_arbitrator import EventArbitrator, ArbitrationSignal
from wyckoff.core.sequence_validator import SequenceValidator
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.core.trading_plan_generator import TradingPlanGenerator


def _make_ohlcv(n: int = 40, base: float = 100.0) -> pd.DataFrame:
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    return pd.DataFrame({
        'Open': [base] * n,
        'High': [base + 1] * n,
        'Low': [base - 1] * n,
        'Close': [base] * n,
        'Volume': [1_000_000] * n,
        'Volume_MA20': [900_000] * n,
        'ATR': [1.0] * n,
    }, index=dates)


class TestBreakoutPullbackFix(unittest.TestCase):
    def test_pullback_detection_no_scalar_any_error(self):
        df = _make_ohlcv(30, 100.0)
        # 突破后回测到 TR 上沿附近
        df.iloc[-5, df.columns.get_loc('Low')] = 99.5
        df.iloc[-5, df.columns.get_loc('High')] = 101.0
        df.iloc[-5, df.columns.get_loc('Close')] = 100.5
        df.iloc[-5, df.columns.get_loc('Volume')] = 500_000

        analyzer = BreakoutAnalyzer(df)
        breakout_point = df.index[-10]
        result = analyzer._analyze_pullback(breakout_point, tr_high=100.0)
        self.assertIn('has_pullback', result)
        self.assertIsInstance(result['has_pullback'], bool)


class TestJocReaccumulationGate(unittest.TestCase):
    def test_distribution_phase_d_not_reaccumulation(self):
        det = MengTrendDetector.__new__(MengTrendDetector)
        det._current_phase = 'Distribution Phase D'
        self.assertFalse(det._is_reaccumulation_context())

    def test_accumulation_phase_d_is_reaccumulation(self):
        det = MengTrendDetector.__new__(MengTrendDetector)
        det._current_phase = 'Accumulation Phase D'
        self.assertTrue(det._is_reaccumulation_context())


class TestUtadNoPhaseDefault(unittest.TestCase):
    def test_utad_rejected_without_distribution_phase(self):
        det = ReversalDetector.__new__(ReversalDetector)
        det._current_phase = None
        det.data = _make_ohlcv(130, 50.0)
        det.thresholds = MagicMock()
        det._indicator_cache = None
        # 不应因 current_phase=None 而默认通过派发语境
        result = det.detect_utad(lookback=120)
        if result.get('detected'):
            self.fail('UTAD should not detect without distribution phase context')
        self.assertFalse(result.get('detected', False))


class TestSequenceValidatorJocLps(unittest.TestCase):
    def test_lps_without_joc_not_valid(self):
        events = MagicMock()
        events.lps = MagicMock(
            detected=True,
            latest=MagicMock(date=pd.Timestamp('2024-02-01'), price=98.0),
            signals=[MagicMock(signal_type='lps')],
        )
        events.spring = MagicMock(
            detected=True,
            latest_spring=MagicMock(
                breakdown_price=95.0,
                date=pd.Timestamp('2024-01-10'),
                breakdown_date=pd.Timestamp('2024-01-10'),
            ),
            signals=[],
        )
        events.sos = MagicMock(detected=True, date=pd.Timestamp('2024-01-20'))
        events.joc = None

        val = SequenceValidator(events, _make_ohlcv())._validate_lps_vs_spring()
        self.assertFalse(val['valid'])
        self.assertFalse(val['has_joc_precursor'])


class TestEventArbitratorPairDiff(unittest.TestCase):
    def test_spring_lpsy_uses_pair_time_diff(self):
        arb = EventArbitrator(_make_ohlcv())
        spring = ArbitrationSignal(
            signal_type='spring', date='2024-01-01', direction='bullish',
            confidence=0.8, strength=0.7,
        )
        lpsy = ArbitrationSignal(
            signal_type='lpsy', date='2024-01-05', direction='bearish',
            confidence=0.7, strength=0.6,
        )
        other = ArbitrationSignal(
            signal_type='sow', date='2024-03-01', direction='bearish',
            confidence=0.6, strength=0.5,
        )
        winner, rejected, reason, _ = arb._apply_arbitration_rules(
            [spring, lpsy, other], {}
        )
        self.assertIsNotNone(winner)
        self.assertIn('天', reason)


class TestTradingPlanSpringWaits(unittest.TestCase):
    def test_accumulation_phase_c_spring_waits(self):
        df = _make_ohlcv()
        pd_mock = MagicMock()
        pd_mock.identify_phase.return_value = {
            'phase': 'Accumulation Phase C',
            'events_detected': {
                'spring': {
                    'detected': True,
                    'latest_spring': {
                        'lifecycle_status': 'active',
                        'breakdown_price': 95,
                    },
                },
                'joc': {'detected': False},
            },
        }
        pd_mock.detect_trading_range.return_value = {'high': 110, 'low': 90}
        gen = TradingPlanGenerator(df, pd_mock)
        plan = gen.generate(phase_str='Accumulation Phase C')
        self.assertEqual(plan.get('direction'), '观望')


class TestSignalExtractorSpringWithoutJoc(unittest.TestCase):
    def test_resolve_primary_signal_skips_spring_without_joc(self):
        events = {
            'spring': {'detected': True, 'latest_spring': {'lifecycle_status': 'active'}},
            'joc': {'detected': False},
        }
        sig, direction = SignalExtractor.resolve_primary_signal({'events_detected': events})
        self.assertNotEqual((sig, direction), ('spring', 'long'))


if __name__ == '__main__':
    unittest.main()
