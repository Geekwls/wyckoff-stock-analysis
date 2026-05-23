"""Phase 29: WIE3 calibration, 60min VSA, golden regression helpers."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from wyckoff.core.intraday_vsa import IntradayVSAService
from wyckoff.core.market_state import RegimeState
from wyckoff.core.state_engine import EventDrivenStateEngine
from wyckoff.core.wie3_calibration import (
    estimate_transition_matrix,
    load_transition_matrix,
    resolve_transition_matrix_path,
    weak_label_state,
)


ROOT = Path(__file__).resolve().parents[1]


class TestWIE3Calibration(unittest.TestCase):
    def test_weak_label_panic_on_breakdown(self):
        label = weak_label_state(
            close=100.0,
            aps=3.0,
            cds=5,
            lcs=1.0,
            vpoc=105.0,
            exp_eff=0.3,
            clv=-0.8,
            retention=0.7,
            hidden_weakness=True,
        )
        self.assertEqual(label, RegimeState.S0_PANIC_LIQUIDATION.value)

    def test_estimate_transition_matrix_rows_sum_to_one(self):
        labels = [
            RegimeState.S2_NEUTRAL_COMPRESSION.value,
            RegimeState.S2_NEUTRAL_COMPRESSION.value,
            RegimeState.S3_DEMAND_EMERGENCE.value,
            RegimeState.S4_MARKUP.value,
            RegimeState.S4_MARKUP.value,
            RegimeState.S5_DISTRIBUTION.value,
        ]
        matrix = estimate_transition_matrix(labels, smoothing=0.5, blend_default=0.0)
        for from_label, row in matrix.items():
            self.assertAlmostEqual(sum(row.values()), 1.0, places=3, msg=from_label)

    def test_state_engine_loads_calibrated_matrix(self):
        path = ROOT / 'fixtures' / 'wie3' / 'transition_matrix_default.json'
        matrix = load_transition_matrix(path)
        self.assertIsNotNone(matrix)
        engine = EventDrivenStateEngine(transition_matrix=matrix)
        row = engine.transition_matrix[RegimeState.S0_PANIC_LIQUIDATION.value]
        self.assertAlmostEqual(sum(row.values()), 1.0, places=4)

    def test_resolve_default_matrix_path(self):
        path = resolve_transition_matrix_path(None)
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())


class TestIntradayVSA(unittest.TestCase):
    def _hourly_no_supply_bars(self):
        rows = 30
        close = np.linspace(99.5, 100.2, rows)
        return pd.DataFrame({
            'Open': close - 0.1,
            'High': close + 0.15,
            'Low': close - 0.2,
            'Close': close,
            'Volume': np.where(np.arange(rows) >= rows - 3, 400, 1200),
        })

    def test_detects_no_supply_entry_quality(self):
        service = IntradayVSAService()
        result = service.analyze_entry_quality(
            self._hourly_no_supply_bars(),
            direction='long',
            anchor_level=100.0,
        )
        self.assertTrue(result['available'])
        self.assertIn(result['entry_quality'], ('good', 'excellent', 'fair'))
        self.assertTrue(result['no_supply'] or result['narrow_spread'])


class TestGoldenRegressionHelper(unittest.TestCase):
    def test_expectations_file_valid(self):
        path = ROOT / 'fixtures' / 'golden' / 'expectations.json'
        spec = json.loads(path.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(spec.get('samples') or []), 2)

    def test_validate_golden_logic(self):
        from scripts.validate_real_stocks import _validate_golden

        results = [
            {
                'symbol': 'sh.600519',
                'ok': True,
                'phase': 'Distribution Phase C/D',
                'direction': '观望',
                'spring': '-',
                'lps': '-',
                'signal_score': 49,
            },
            {
                'symbol': 'sz.000001',
                'ok': True,
                'phase': 'Accumulation Phase B (1号Spring待二次测试)',
                'direction': '观望',
                'spring': 'Y',
                'lps': '-',
                'signal_score': 47,
            },
        ]
        rc = _validate_golden(results, ROOT / 'fixtures' / 'golden' / 'expectations.json')
        self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main()
