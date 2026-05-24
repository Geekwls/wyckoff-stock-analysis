import unittest
import pandas as pd
import numpy as np
from wyckoff.config.settings import WyckoffThresholds
from wyckoff.core.point_and_figure import calculate_cause_effect_from_pnf, PointAndFigureCalculator
from wyckoff.core.weis_wave import WeisWaveGenerator


class TestWave5TacticalStrategy(unittest.TestCase):
    def _create_mock_data(self, length: int, price: float, atr_pct: float, vol: float = 1000.0) -> pd.DataFrame:
        """Helper to create mock OHLCV data with a controlled ATR%"""
        closes = [price] * length
        highs = []
        lows = []
        atr_val = price * (atr_pct / 100.0)
        
        # We simulate a steady high/low spread equal to the desired ATR
        for c in closes:
            highs.append(c + atr_val / 2.0)
            lows.append(c - atr_val / 2.0)
            
        return pd.DataFrame({
            'Open': closes,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': [vol] * length
        })

    def test_wave5_adaptive_pnf_box_size_limits_and_fallback(self):
        # 1. Test PNF_BOX_SIZE_MIN (0.5% limit) for low volatility stock
        # ATR% is set extremely low at 0.2%, so 0.5 * ATR% = 0.1%, which should clip at PNF_BOX_SIZE_MIN (0.5%)
        low_vol_data = self._create_mock_data(length=260, price=100.0, atr_pct=0.2)
        res = calculate_cause_effect_from_pnf(low_vol_data, adaptive_box_size=True)
        self.assertAlmostEqual(res['box_size_pct'], 0.5)
        self.assertEqual(res['derivation'], "adaptive_atr_250d")

        # 2. Test PNF_BOX_SIZE_MAX (3.0% limit) for high volatility stock
        # ATR% is set high at 8.0%, so 0.5 * ATR% = 4.0%, which should clip at PNF_BOX_SIZE_MAX (3.0%)
        high_vol_data = self._create_mock_data(length=260, price=100.0, atr_pct=8.0)
        res = calculate_cause_effect_from_pnf(high_vol_data, adaptive_box_size=True)
        self.assertAlmostEqual(res['box_size_pct'], 3.0)
        self.assertEqual(res['derivation'], "adaptive_atr_250d")

        # 3. Test Fallback logic for new listings (次新股)
        # 3.1 Length = 150 (falls back to 120d)
        new_listing_120 = self._create_mock_data(length=150, price=100.0, atr_pct=2.0)
        res = calculate_cause_effect_from_pnf(new_listing_120, adaptive_box_size=True)
        self.assertAlmostEqual(res['box_size_pct'], 1.0)  # 0.5 * 2% = 1%
        self.assertEqual(res['derivation'], "adaptive_atr_120d")

        # 3.2 Length = 80 (falls back to 60d)
        new_listing_60 = self._create_mock_data(length=80, price=100.0, atr_pct=4.0)
        res = calculate_cause_effect_from_pnf(new_listing_60, adaptive_box_size=True)
        self.assertAlmostEqual(res['box_size_pct'], 2.0)  # 0.5 * 4% = 2%
        self.assertEqual(res['derivation'], "adaptive_atr_60d")

        # 3.3 Length = 30 (falls back to 20d)
        new_listing_20 = self._create_mock_data(length=30, price=100.0, atr_pct=5.0)
        res = calculate_cause_effect_from_pnf(new_listing_20, adaptive_box_size=True)
        self.assertAlmostEqual(res['box_size_pct'], 2.5)  # 0.5 * 5% = 2.5%
        self.assertEqual(res['derivation'], "adaptive_atr_20d")

    def test_wave5_adaptive_pnf_custom_thresholds_override(self):
        # Test overriding PNF_BOX_SIZE_MIN/MAX via custom thresholds
        custom_th = WyckoffThresholds(
            PNF_BOX_SIZE_MIN=1.5,
            PNF_BOX_SIZE_MAX=2.0
        )
        
        # High volatility asset, normally caps at 3.0%, but custom_th caps it at 2.0%
        high_vol_data = self._create_mock_data(length=260, price=100.0, atr_pct=8.0)
        res = calculate_cause_effect_from_pnf(high_vol_data, adaptive_box_size=True, thresholds=custom_th)
        self.assertAlmostEqual(res['box_size_pct'], 2.0)

        # Low volatility asset, normally floors at 0.5%, but custom_th floors it at 1.5%
        low_vol_data = self._create_mock_data(length=260, price=100.0, atr_pct=0.2)
        res = calculate_cause_effect_from_pnf(low_vol_data, adaptive_box_size=True, thresholds=custom_th)
        self.assertAlmostEqual(res['box_size_pct'], 1.5)

    def test_wave5_weis_wave_volume_normalization(self):
        # Create zigzag price moves to trigger clear up/down waves
        # We need a 60-day background history to compute rolling ADV_60
        length = 100
        closes = [100.0] * length
        highs = [101.0] * length
        lows = [99.0] * length
        volumes = [1000.0] * length
        
        # Introduce a 5-day up wave from index 65 to 70
        for i in range(65, 71):
            closes[i] = 100.0 + (i - 64) * 2.0  # rising price
            highs[i] = closes[i] + 0.5
            lows[i] = closes[i] - 0.5
            volumes[i] = 2000.0                 # volume 2000 per day
            
        # Introduce a 1-day down wave (spike) at index 71
        closes[71] = 100.0                      # drop back
        highs[71] = 100.5
        lows[71] = 99.5
        volumes[71] = 6000.0                    # huge 1-day spike volume

        data = pd.DataFrame({
            'Open': closes,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': volumes
        })
        
        gen = WeisWaveGenerator(data, atr_multiplier=1.0)
        waves = gen.generate()
        
        # We look for our target waves (around the end of the data)
        self.assertTrue(len(waves) >= 2)
        
        up_wave = None
        spike_wave = None
        for w in waves:
            if w.direction == 'up' and w.duration == 6:
                up_wave = w
            if w.direction == 'down' and w.duration == 2:
                spike_wave = w

        self.assertIsNotNone(up_wave, "Failed to capture the simulated up wave")
        self.assertIsNotNone(spike_wave, "Failed to capture the 1-day spike down wave")

        # Check absolute volumes are intact
        self.assertAlmostEqual(up_wave.volume, 12000.0)
        self.assertAlmostEqual(spike_wave.volume, 7000.0)

        # ADV_60 around index 70/72 is roughly 1083 (mostly 1000s, some 2000s)
        # Let's verify that the normalized volume is calculated correctly
        self.assertTrue(up_wave.volume_normalized > 0)
        self.assertTrue(spike_wave.volume_normalized > 0)

        # Check that the 2-day spike wave uses duration_factor = 3 due to the floor protection
        # ADV_60 at index 72 is ~1083.33
        # Normalized volume of spike = 7000 / (1083.33 * 3) = ~2.15
        # Without protection, it would have been 7000 / (1083.33 * 2) = ~3.23
        expected_spike_norm = 7000.0 / (data['Volume'].rolling(60).mean().iloc[72] * 3)
        self.assertAlmostEqual(spike_wave.volume_normalized, expected_spike_norm, places=4)


if __name__ == '__main__':
    unittest.main()
