import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple, List, Any
from .base_detector import BaseDetector, USE_VECTORIZED
from ...config.settings import WyckoffConfig, WyckoffThresholds

logger = logging.getLogger(__name__)

class TrendDetector(BaseDetector):
    """
    负责检测趋势确认和突破形态
    (JOC, FTI)
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, analysis_cache, bayesian_model=None, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds
        self._analysis_cache = analysis_cache
        self.bayesian_model = bayesian_model

    def detect_joc(self, lookback: int = 90) -> Dict:
        """检测 JOC (Jump Over Creek)"""
        if self.data is None or len(self.data) < 60:
            return {'detected': False, 'reason': 'insufficient_data'}

        df = self.data.tail(lookback).copy()
        vol_ma, _, _ = self._get_tech_indicators(20)
        vol_ma = vol_ma.reindex(df.index)
        tr_window = min(60, len(df))
        tr_data = df.tail(tr_window)
        creek_level = tr_data['High'].quantile(self.thresholds.JOC_CREEK_QUANTILE)

        body_size = (df['Close'] - df['Open']).abs()
        total_range = (df['High'] - df['Low']).replace(0, float('nan'))
        body_ratio = body_size / total_range
        upper_shadow = df['High'] - df[['Open', 'Close']].max(axis=1)
        upper_shadow_ratio = upper_shadow / total_range.fillna(1)

        breakout_mask = (
            (df['Close'] > creek_level) &
            (df['Open'] < creek_level * (1 + self.thresholds.JOC_TEST_BAND/2)) &
            (df['Close'] > df['Open']) &
            (body_ratio >= self.thresholds.JOC_BODY_RATIO) &
            (upper_shadow_ratio < self.thresholds.JOC_UPPER_SHADOW_RATIO) &
            (df['Volume'] >= vol_ma * self._get_volume_threshold('breakout', self.thresholds.JOC_VOLUME_RATIO, self.bayesian_model))
        )

        if not breakout_mask.any():
            return {'detected': False, 'reason': 'no_joc_breakout_found'}

        joc_candidates = df[breakout_mask].sort_index(ascending=False)
        fresh_joc_found = False
        current_price = self.data['Close'].iloc[-1]
        
        for joc_idx_temp in joc_candidates.index:
            # 增加：时间衰减检查
            if self._is_signal_stale(joc_idx_temp, 'joc'): continue
            
            # 增加：价格证伪检查
            if self._is_signal_falsified('joc', creek_level, current_price):
                logger.info(f"JOC signal at {joc_idx_temp} falsified by current price {current_price}")
                continue
                
            joc_idx = joc_idx_temp
            joc_row = df.loc[joc_idx]
            fresh_joc_found = True
            break

        if not fresh_joc_found:
            return {'detected': False, 'reason': 'no_fresh_valid_joc_signal'}

        v_ma_val = vol_ma.loc[joc_idx]
        volume_ratio = joc_row['Volume'] / v_ma_val if v_ma_val > 0 else 0
        breakout_pct = (joc_row['Close'] - creek_level) / creek_level

        test_detected, test_date, test_vol_ratio, test_depth_pct, test_count = False, None, None, 0.0, 0
        df_after_joc = df[df.index > joc_idx].head(10)
        if len(df_after_joc) >= 1:
            if USE_VECTORIZED:
                try:
                    lows, closes, vols = df_after_joc['Low'].values, df_after_joc['Close'].values, df_after_joc['Volume'].values
                    vol_mas = vol_ma.loc[df_after_joc.index].values
                    creek_lower, creek_upper = creek_level * (1 - self.thresholds.JOC_TEST_BAND), creek_level * (1 + self.thresholds.JOC_TEST_BAND * 2)
                    test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.JOC_TEST_VOL_RATIO, self.bayesian_model)
                    test_hits = (lows >= creek_lower) & (lows <= creek_upper) & (vols < vol_mas * test_vol_threshold) & (closes > creek_level)
                    hit_indices = np.where(test_hits)[0]
                    if len(hit_indices) > 0:
                        test_detected, first_hit = True, hit_indices[0]
                        test_date = df_after_joc.index[first_hit]
                        test_vol_ratio = round(float(vols[first_hit] / vol_mas[first_hit]), 2)
                    test_count = int(np.sum(test_hits))
                    depths = (joc_row['Close'] - lows) / joc_row['Close']
                    if len(depths) > 0: test_depth_pct = max(0.0, float(np.max(depths)))
                except Exception:
                    test_detected, test_date, test_vol_ratio, test_depth_pct, test_count = self._detect_joc_test_iterative(df_after_joc, creek_level, vol_ma, joc_row)
            else:
                test_detected, test_date, test_vol_ratio, test_depth_pct, test_count = self._detect_joc_test_iterative(df_after_joc, creek_level, vol_ma, joc_row)

        strength_info = self._classify_joc_strength({'test_detected': test_detected, 'test_depth_pct': test_depth_pct, 'test_count': test_count, 'volume_ratio': volume_ratio, 'breakout_pct': breakout_pct})
        confidence = 0.50 + (0.2 if volume_ratio >= 2.0 else 0.1 if volume_ratio >= 1.5 else 0) + (0.1 if breakout_pct >= 0.03 else 0) + (0.2 if test_detected else 0) + strength_info['confidence_boost']
        return {
            'detected': True, 'date': joc_idx, 'creek_level': round(creek_level, 3), 'close_price': round(joc_row['Close'], 3),
            'breakout_pct': round(breakout_pct * 100, 2), 'volume_ratio': round(volume_ratio, 2),
            'test_detected': test_detected, 'test_date': test_date, 'test_vol_ratio': test_vol_ratio,
            'test_depth_pct': round(test_depth_pct * 100, 2), 'test_count': test_count,
            'strength': strength_info['strength'], 'strength_description': strength_info['description'],
            'trading_implication': strength_info['trading_implication'], 'confidence': round(min(confidence, 1.0), 2)
        }

    def _detect_joc_test_iterative(self, df_after, creek_level, vol_ma, joc_row):
        test_detected, test_date, test_vol_ratio, test_depth_pct, test_count = False, None, None, 0.0, 0
        for idx_test, row_test in df_after.iterrows():
            near_creek = creek_level * (1 - self.thresholds.JOC_TEST_BAND) <= row_test['Low'] <= creek_level * (1 + self.thresholds.JOC_TEST_BAND * 2)
            test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.JOC_TEST_VOL_RATIO, self.bayesian_model)
            vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * test_vol_threshold
            above_creek = row_test['Close'] > creek_level
            if near_creek and vol_shrinking and above_creek:
                if not test_detected:
                    test_detected, test_date, test_vol_ratio = True, idx_test, round(row_test['Volume'] / vol_ma.loc[idx_test], 2)
                test_count += 1
            test_depth_pct = max(test_depth_pct, (joc_row['Close'] - row_test['Low']) / joc_row['Close'])
        return test_detected, test_date, test_vol_ratio, test_depth_pct, test_count

    def _classify_joc_strength(self, joc_signal: dict) -> dict:
        has_test, test_depth, test_count = joc_signal.get('test_detected', False), joc_signal.get('test_depth_pct', 0), joc_signal.get('test_count', 0)
        if not has_test:
            return {'strength': 'STRONG_JOC', 'description': '强势JOC（直接拉升，无需回测）', 'trading_implication': '激进追涨，止损设在JOC起点', 'confidence_boost': 0.3}
        elif test_depth < 0.03 and test_count <= 2:
            return {'strength': 'STRONG_JOC_CONFIRMED', 'description': f'强势JOC（浅回测{test_depth*100:.1f}%，{test_count}次确认）', 'trading_implication': '稳健做多，回测介入', 'confidence_boost': 0.2}
        else:
            return {'strength': 'WEAK_JOC', 'description': f'弱势JOC（深回测{test_depth*100:.1f}%，{test_count}次试探）', 'trading_implication': '谨慎观望，等待明确方向', 'confidence_boost': -0.2}

    def detect_fti(self, lookback: int = 90) -> Dict:
        """检测 FTI (Fall Through Ice)"""
        if self.data is None or len(self.data) < 60:
            return {'detected': False, 'reason': 'insufficient_data'}

        df = self.data.tail(lookback).copy()
        vol_ma, _, _ = self._get_tech_indicators(20)
        vol_ma = vol_ma.reindex(df.index)
        tr_window = min(60, len(df))
        tr_data = df.tail(tr_window)
        ice_level = tr_data['Low'].quantile(self.thresholds.FTI_ICE_QUANTILE)

        body_size = (df['Close'] - df['Open']).abs()
        total_range = (df['High'] - df['Low']).replace(0, float('nan'))
        body_ratio = body_size / total_range
        lower_shadow = df[['Open', 'Close']].min(axis=1) - df['Low']
        lower_shadow_ratio = lower_shadow / total_range.fillna(1)

        breakdown_mask = (
            (df['Close'] < ice_level) &
            (df['Open'] > ice_level * (1 - self.thresholds.FTI_TEST_BAND/2)) &
            (df['Close'] < df['Open']) &
            (body_ratio >= self.thresholds.FTI_BODY_RATIO) &
            (lower_shadow_ratio < self.thresholds.FTI_LOWER_SHADOW_RATIO) &
            (df['Volume'] >= vol_ma * self._get_volume_threshold('breakout', self.thresholds.FTI_VOLUME_RATIO, self.bayesian_model))
        )

        if not breakdown_mask.any():
            return {'detected': False, 'reason': 'no_fti_breakdown_found'}

        fti_candidates = df[breakdown_mask].sort_index(ascending=False)
        fresh_fti_found = False
        current_price = self.data['Close'].iloc[-1]

        for fti_idx_temp in fti_candidates.index:
            # 增加：时间衰减检查
            if self._is_signal_stale(fti_idx_temp, 'fti'): continue
            
            # 增加：价格证伪检查 (解决用户提到的 26元 FTI 在 59元 时依然生效的问题)
            if self._is_signal_falsified('fti', ice_level, current_price):
                logger.info(f"FTI signal at {fti_idx_temp} (level {ice_level}) falsified by current price {current_price}")
                continue
                
            fti_idx = fti_idx_temp
            fti_row = df.loc[fti_idx]
            fresh_fti_found = True
            break

        if not fresh_fti_found:
            return {'detected': False, 'reason': 'no_fresh_valid_fti_signal'}

        v_ma_val = vol_ma.loc[fti_idx]
        volume_ratio, breakdown_pct = fti_row['Volume'] / v_ma_val if v_ma_val > 0 else 0, (fti_row['Close'] - ice_level) / ice_level

        test_detected, test_date, test_vol_ratio = False, None, None
        df_after_fti = df[df.index > fti_idx].head(10)
        if len(df_after_fti) >= 1:
            if USE_VECTORIZED:
                try:
                    highs, closes, vols = df_after_fti['High'].values, df_after_fti['Close'].values, df_after_fti['Volume'].values
                    vol_mas = vol_ma.loc[df_after_fti.index].values
                    ice_lower, ice_upper, ice_fail_threshold = ice_level * (1 - self.thresholds.FTI_TEST_BAND * 1.5), ice_level * (1 + self.thresholds.FTI_TEST_BAND), ice_level * (1 + self.thresholds.FTI_TEST_BAND / 2)
                    test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.FTI_TEST_VOL_RATIO, self.bayesian_model)
                    test_hits = (highs >= ice_lower) & (highs <= ice_upper) & (vols < vol_mas * test_vol_threshold) & (closes < ice_fail_threshold)
                    hit_indices = np.where(test_hits)[0]
                    if len(hit_indices) > 0:
                        test_detected, first_hit = True, hit_indices[0]
                        test_date, test_vol_ratio = df_after_fti.index[first_hit], round(float(vols[first_hit] / vol_mas[first_hit]), 2)
                except Exception:
                    test_detected, test_date, test_vol_ratio = self._detect_fti_test_iterative(df_after_fti, ice_level, vol_ma)
            else:
                test_detected, test_date, test_vol_ratio = self._detect_fti_test_iterative(df_after_fti, ice_level, vol_ma)

        confidence = 0.50 + (0.2 if volume_ratio >= 2.0 else 0.1 if volume_ratio >= 1.5 else 0) + (0.1 if abs(breakdown_pct) >= 0.03 else 0) + (0.2 if test_detected else 0)
        return {
            'detected': True, 'date': fti_idx, 'ice_level': round(ice_level, 3), 'close_price': round(fti_row['Close'], 3),
            'breakdown_pct': round(breakdown_pct * 100, 2), 'volume_ratio': round(volume_ratio, 2),
            'test_detected': test_detected, 'test_date': test_date, 'test_vol_ratio': test_vol_ratio, 'confidence': round(min(confidence, 1.0), 2)
        }

    def _detect_fti_test_iterative(self, df_after, ice_level, vol_ma):
        test_detected, test_date, test_vol_ratio = False, None, None
        for idx_test, row_test in df_after.iterrows():
            near_ice = ice_level * (1 - self.thresholds.FTI_TEST_BAND * 1.5) <= row_test['High'] <= ice_level * (1 + self.thresholds.FTI_TEST_BAND)
            test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.FTI_TEST_VOL_RATIO, self.bayesian_model)
            vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * test_vol_threshold
            failed_recovery = row_test['Close'] < ice_level * (1 + self.thresholds.FTI_TEST_BAND/2)
            if near_ice and vol_shrinking and failed_recovery:
                test_detected, test_date, test_vol_ratio = True, idx_test, round(row_test['Volume'] / vol_ma.loc[idx_test], 2)
                break
        return test_detected, test_date, test_vol_ratio
