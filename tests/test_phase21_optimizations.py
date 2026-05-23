"""Phase 21：CHoCH 统一 + effective_phase 权威"""
import unittest
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from wyckoff.core.utils import detect_choch_weis, is_bullish_choch, normalize_choch_result
from wyckoff.core.pattern_detector import WyckoffPatternDetector
from wyckoff.core.signal_extractor import SignalExtractor
from wyckoff.core.detectors.meng_reversal_detector import MengReversalDetector
from wyckoff.core.detectors.strength_weakness_detector import StrengthWeaknessDetector
from wyckoff.config.settings import WyckoffConfig, WyckoffThresholds


def _wave_df(n: int = 80) -> pd.DataFrame:
    """构造可触发 Weis CHoCH 的合成数据。"""
    idx = pd.date_range('2024-01-01', periods=n, freq='D')
    close = np.concatenate([
        np.linspace(100, 90, 30),
        np.linspace(90, 95, 20),
        np.linspace(95, 110, 30),
    ])
    high = close + 1.5
    low = close - 1.5
    vol = np.concatenate([
        np.full(50, 1000.0),
        np.full(30, 3500.0),
    ])
    return pd.DataFrame({
        'Open': close,
        'High': high,
        'Low': low,
        'Close': close,
        'Volume': vol,
    }, index=idx)


class TestChochUnified(unittest.TestCase):
    def test_weis_choch_normalizes_direction(self):
        raw = detect_choch_weis(_wave_df())
        if raw.get('detected'):
            self.assertIn(raw['direction'], ('bullish', 'bearish'))
            self.assertEqual(raw.get('type'), 'CHoCH')
            self.assertIn('interpretation', raw)

    def test_meng_and_sw_same_source(self):
        df = _wave_df()
        cfg, th = WyckoffConfig(), WyckoffThresholds()
        meng = MengReversalDetector(df, cfg, th)
        sw = StrengthWeaknessDetector(df, cfg, th)
        self.assertEqual(meng.detect_choch(), sw.detect_choch())

    def test_normalize_up_down_aliases(self):
        out = normalize_choch_result({'detected': True, 'direction': 'up', 'description': 'test'})
        self.assertTrue(is_bullish_choch(out['direction']))


class TestEffectivePhase(unittest.TestCase):
    def test_get_effective_phase_prefers_merged_field(self):
        phase = {
            'phase': 'Distribution Phase C',
            'effective_phase': 'Distribution Phase C',
            'identifier_phase': 'Accumulation Phase C',
            'coordinator_phase': 'Distribution Phase C',
        }
        self.assertEqual(SignalExtractor.get_effective_phase(phase), 'Distribution Phase C')

    def test_coordinator_without_marker_does_not_override(self):
        detector = WyckoffPatternDetector.__new__(WyckoffPatternDetector)
        events = MagicMock()
        events.coordinator_final_phase = 'Distribution Phase C'
        events.phase_revision_log = []

        merged = detector._merge_coordinator_phase(
            {'phase': 'Accumulation Phase C', 'phase_enum': None},
            events,
        )
        self.assertEqual(merged['phase'], 'Accumulation Phase C')
        self.assertEqual(merged['effective_phase'], 'Accumulation Phase C')
        self.assertEqual(merged.get('coordinator_phase'), 'Distribution Phase C')

    def test_arbitration_marker_overrides(self):
        detector = WyckoffPatternDetector.__new__(WyckoffPatternDetector)
        events = MagicMock()
        events.coordinator_final_phase = 'Distribution Phase C/D'
        events.phase_revision_log = ['[事件仲裁] SOW 优先于 JOC']

        merged = detector._merge_coordinator_phase(
            {'phase': 'Accumulation Phase C', 'phase_enum': None},
            events,
        )
        self.assertEqual(merged['phase'], 'Distribution Phase C/D')
        self.assertEqual(merged['effective_phase'], 'Distribution Phase C/D')
        self.assertEqual(merged['identifier_phase'], 'Accumulation Phase C')

    def test_build_scoring_payload_uses_effective_phase(self):
        phase_result = {
            'phase': 'Accumulation Phase C',
            'effective_phase': 'Accumulation Phase C',
            'events_detected': {'spring': {'detected': True}},
        }
        payload = SignalExtractor.build_scoring_payload(phase_result)
        self.assertEqual(payload['phase'], 'Accumulation Phase C')
        self.assertEqual(payload['effective_phase'], 'Accumulation Phase C')
