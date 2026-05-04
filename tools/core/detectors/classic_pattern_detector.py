import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from ...config.settings import WyckoffConfig, WyckoffThresholds

class ClassicPatternDetector:
    """负责检测经典威科夫形态 (Climax, Spring, Upthrust, JOC, FTI, VSA, Divergence)"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, analysis_cache):
        self.data = data
        self.config = config
        self.thresholds = thresholds
        self._analysis_cache = analysis_cache

    # --- Climax, AR, ST ---
    def detect_climax(self) -> Dict:
        """检测高潮行为 (SC/BC)"""
        return self._analysis_cache.get_or_compute(
            "climax", self._detect_climax_impl
        )

    def _detect_climax_impl(self) -> Dict:
        if self.data is None or len(self.data) < 20:
            return {'detected': False}

        df = self.data.tail(40).copy()
        # 使用预计算的量比指标
        vol_ma = self.data['Volume_MA20']
        
        # 抛售高潮 (Selling Climax)
        sc_mask = (
            (df['Close'] < df['Open']) & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['Low'] == self.data['Low_Min_20'].reindex(df.index))
        )
        
        # 买入高潮 (Buying Climax)
        bc_mask = (
            (df['Close'] > df['Open']) & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['High'] == self.data['High_Max_20'].reindex(df.index))
        )
        
        if sc_mask.any():
            idx = df[sc_mask].index[-1]
            return {'detected': True, 'type': 'selling_climax', 'date': idx, 'price': df.loc[idx, 'Low'], 'volume': df.loc[idx, 'Volume']}
        if bc_mask.any():
            idx = df[bc_mask].index[-1]
            return {'detected': True, 'type': 'buying_climax', 'date': idx, 'price': df.loc[idx, 'High'], 'volume': df.loc[idx, 'Volume']}
            
        return {'detected': False}

    def detect_automatic_reaction(self, climax_res: Dict) -> Dict:
        """检测自动反弹/回落 (AR)"""
        cache_key = f"ar_{climax_res.get('date')}_{climax_res.get('type')}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_automatic_reaction_impl, climax_res
        )

    def _detect_automatic_reaction_impl(self, climax_res: Dict) -> Dict:
        if not climax_res.get('detected'):
            return {'detected': False}
            
        climax_date = climax_res['date']
        df_after = self.data[self.data.index > climax_date].head(20)
        
        if len(df_after) == 0:
            return {'detected': False}
            
        if climax_res['type'] == 'selling_climax':
            ar_price = df_after['High'].max()
            ar_date = df_after['High'].idxmax()
            return {'detected': True, 'type': 'automatic_rally', 'date': ar_date, 'price': ar_price}
        else:
            ar_price = df_after['Low'].min()
            ar_date = df_after['Low'].idxmin()
            return {'detected': True, 'type': 'automatic_reaction', 'date': ar_date, 'price': ar_price}

    def detect_secondary_test(self, climax_res: Dict, ar_res: Dict) -> Dict:
        """检测二次测试 (ST)"""
        cache_key = f"st_{climax_res.get('date')}_{ar_res.get('date')}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_secondary_test_impl, climax_res, ar_res
        )

    def _detect_secondary_test_impl(self, climax_res: Dict, ar_res: Dict) -> Dict:
        if not climax_res.get('detected') or not ar_res.get('detected'):
            return {'detected': False}
            
        ar_date = ar_res['date']
        df_after = self.data[self.data.index > ar_date].head(30)
        
        if len(df_after) == 0:
            return {'detected': False}
            
        climax_price = climax_res['price']
        
        if climax_res['type'] == 'selling_climax':
            # 寻找接近 SC 低点的测试 (使用 JOC_TEST_BAND 比例)
            test_mask = (df_after['Low'] <= climax_price * (1 + self.thresholds.JOC_TEST_BAND)) & \
                        (df_after['Volume'] < climax_res['volume'] * self.thresholds.VOLUME_CONFIRMATION['weak'])
            if test_mask.any():
                idx = df_after[test_mask].index[-1]
                return {'detected': True, 'type': 'secondary_test', 'date': idx, 'price': df_after.loc[idx, 'Low']}
        else:
            test_mask = (df_after['High'] >= climax_price * (1 - self.thresholds.JOC_TEST_BAND)) & \
                        (df_after['Volume'] < climax_res['volume'] * self.thresholds.VOLUME_CONFIRMATION['weak'])
            if test_mask.any():
                idx = df_after[test_mask].index[-1]
                return {'detected': True, 'type': 'secondary_test', 'date': idx, 'price': df_after.loc[idx, 'High']}
                
        return {'detected': False}

    # --- Spring & Upthrust ---
    def detect_spring(self, lookback: int = None) -> Dict:
        lookback = lookback or self.config.spring_lookback
        cache_key = f"spring_{lookback}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_spring_impl, lookback
        )

    def _detect_spring_impl(self, lookback: int) -> Dict:
        if self.data is None or len(self.data) < 30:
            return {'detected': False, 'reason': 'insufficient_data'}
            
        df = self.data.tail(lookback).copy()
        support_level = self._check_spring_preconditions(df)
        if support_level is None:
            return {'detected': False, 'reason': 'no_trading_range'}
            
        search_df, breakdown_indices, recovery_info = self._find_spring_breakdowns(df, support_level)
        if breakdown_indices is None or len(breakdown_indices) == 0:
            return {'detected': False, 'reason': 'no_breakdown_found'}
            
        springs = self._verify_spring_recoveries(search_df, breakdown_indices, support_level, recovery_info)
        
        if springs:
            return {'detected': True, 'signals': springs, 'latest_spring': springs[-1]}
        return {'detected': False, 'reason': 'no_spring_found'}

    def _check_spring_preconditions(self, df: pd.DataFrame) -> Optional[float]:
        """
        检查前置条件：前 N-M 根定义区间，计算支撑位。
        """
        M = self.config.breakout_search_window
        if len(df) <= M:
            return None
            
        range_df = df.iloc[:-M] # 前 N-M 根定义区间
        high_max = range_df['High'].max()
        low_min = range_df['Low'].min()
        
        range_pct = (high_max - low_min) / low_min
        if range_pct < self.config.spring_range_threshold:
            return low_min
        return None

    def _find_spring_breakdowns(self, df: pd.DataFrame, support_level: float):
        """
        在最后 M 根中找突破/回归。
        """
        M = self.config.breakout_search_window
        breakout_df = df.tail(M)
        
        breakdown_mask = breakout_df['Low'] < support_level
        breakdown_indices = breakout_df.index[breakdown_mask]
        
        # 寻找回归（可以在整个 df 中寻找，但触发点必须在 breakout_df 之后或之内）
        recovery_mask = df['Close'] > support_level
        recovery_info = {
            'mask': recovery_mask,
            'indices': df.index[recovery_mask]
        }
        return df, breakdown_indices, recovery_info

    def _verify_spring_recoveries(self, df: pd.DataFrame, breakdown_indices, support_level, recovery_info):
        springs = []
        recovery_mask = recovery_info['mask']
        recovery_indices = recovery_info['indices']
        
        for b_idx in breakdown_indices[-3:]:
            later_recoveries = recovery_indices[recovery_indices > b_idx]
            if len(later_recoveries) > 0:
                r_idx = later_recoveries[0]
                days_to_recover = (df.index.get_indexer([r_idx])[0] - df.index.get_indexer([b_idx])[0])
                
                if days_to_recover <= self.config.spring_max_recovery_days:
                    b_vol = df.loc[b_idx, 'Volume']
                    r_vol = df.loc[r_idx, 'Volume']
                    
                    if r_vol > b_vol * 1.1:
                        springs.append({
                            'date': r_idx,
                            'breakdown_date': b_idx,
                            'breakdown_price': df.loc[b_idx, 'Low'],
                            'support_level': support_level,
                            'recovery_price': df.loc[r_idx, 'Close'],
                            'recovery_days': int(days_to_recover),
                            'volume_ratio': round(r_vol / b_vol, 2)
                        })
        return springs

    def detect_upthrust(self, lookback: int = None) -> Dict:
        lookback = lookback or self.config.spring_lookback
        cache_key = f"upthrust_{lookback}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_upthrust_impl, lookback
        )

    def _detect_upthrust_impl(self, lookback: int) -> Dict:
        if self.data is None or len(self.data) < 30:
            return {'detected': False}
            
        df = self.data.tail(lookback).copy()
        resistance_level = self._check_upthrust_preconditions(df)
        if resistance_level is None:
            return {'detected': False}
            
        upthrusts = self._find_and_verify_upthrusts(df, resistance_level)
        if upthrusts:
            return {'detected': True, 'upthrusts': upthrusts, 'latest_upthrust': upthrusts[-1]}
        return {'detected': False}

    def _check_upthrust_preconditions(self, df: pd.DataFrame) -> Optional[float]:
        """
        检查前置条件：前 N-M 根定义区间，计算阻力位。
        """
        M = self.config.breakout_search_window
        if len(df) <= M:
            return None
            
        range_df = df.iloc[:-M]
        high_max = range_df['High'].max()
        low_min = range_df['Low'].min()
        
        range_pct = (high_max - low_min) / low_min
        if range_pct < self.config.spring_range_threshold:
            return high_max
        return None

    def _find_and_verify_upthrusts(self, df: pd.DataFrame, resistance_level: float):
        M = self.config.breakout_search_window
        breakout_df = df.tail(M)
        
        upthrusts = []
        breakout_mask = breakout_df['High'] > resistance_level
        breakout_indices = breakout_df.index[breakout_mask]
        
        rejection_mask = df['Close'] < resistance_level
        rejection_indices = df.index[rejection_mask]
        
        for b_idx in breakout_indices[-3:]:
            later_rejections = rejection_indices[rejection_indices > b_idx]
            if len(later_rejections) > 0:
                r_idx = later_rejections[0]
                days_to_reject = (df.index.get_indexer([r_idx])[0] - df.index.get_indexer([b_idx])[0])
                
                if days_to_reject <= 3:
                    b_vol = df.loc[b_idx, 'Volume']
                    r_vol = df.loc[r_idx, 'Volume']
                    close_pos = (df.loc[r_idx, 'High'] - df.loc[r_idx, 'Close']) / (df.loc[r_idx, 'High'] - df.loc[r_idx, 'Low'] + 1e-6)
                    
                    if r_vol > b_vol * 1.1 or close_pos > 0.7:
                        upthrusts.append({
                            'date': r_idx,
                            'breakout_date': b_idx,
                            'breakout_price': df.loc[b_idx, 'High'],
                            'resistance_level': resistance_level,
                            'rejection_price': df.loc[r_idx, 'Close'],
                            'rejection_days': int(days_to_reject),
                            'close_from_high': round(close_pos, 2)
                        })
        return upthrusts

    # --- JOC & FTI ---
    def detect_joc(self, lookback: int = 90) -> Dict:
        if self.data is None or len(self.data) < 60:
            return {'detected': False, 'reason': 'insufficient_data'}

        df = self.data.tail(lookback).copy()
        vol_ma = df['Volume'].rolling(20, min_periods=1).mean()
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
            (df['Volume'] >= vol_ma * self.thresholds.JOC_VOLUME_RATIO)
        )

        if not breakout_mask.any():
            return {'detected': False, 'reason': 'no_joc_breakout_found'}

        joc_idx = df[breakout_mask].index[-1]
        joc_row = df.loc[joc_idx]
        v_ma_val = vol_ma.loc[joc_idx]
        volume_ratio = joc_row['Volume'] / v_ma_val if v_ma_val > 0 else 0
        breakout_pct = (joc_row['Close'] - creek_level) / creek_level

        test_detected = False
        test_date = None
        test_vol_ratio = None
        df_after_joc = df[df.index > joc_idx].head(10)
        if len(df_after_joc) >= 1:
            for idx_test in df_after_joc.index:
                row_test = df_after_joc.loc[idx_test]
                near_creek = creek_level * (1 - self.thresholds.JOC_TEST_BAND) <= row_test['Low'] <= creek_level * (1 + self.thresholds.JOC_TEST_BAND * 2)
                vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * self.thresholds.JOC_TEST_VOL_RATIO
                if near_creek and vol_shrinking:
                    test_detected = True
                    test_date = idx_test
                    test_vol_ratio = round(row_test['Volume'] / vol_ma.loc[idx_test], 2)
                    break

        confidence = 0.50 + (0.2 if volume_ratio >= 2.0 else 0.1 if volume_ratio >= 1.5 else 0) + (0.1 if breakout_pct >= 0.03 else 0) + (0.2 if test_detected else 0)
        return {
            'detected': True, 'date': joc_idx, 'creek_level': round(creek_level, 3), 'close_price': round(joc_row['Close'], 3),
            'breakout_pct': round(breakout_pct * 100, 2), 'volume_ratio': round(volume_ratio, 2),
            'test_detected': test_detected, 'test_date': test_date, 'test_vol_ratio': test_vol_ratio, 'confidence': round(min(confidence, 1.0), 2)
        }

    def detect_fti(self, lookback: int = 90) -> Dict:
        if self.data is None or len(self.data) < 60:
            return {'detected': False, 'reason': 'insufficient_data'}

        df = self.data.tail(lookback).copy()
        vol_ma = df['Volume'].rolling(20, min_periods=1).mean()
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
            (df['Volume'] >= vol_ma * self.thresholds.FTI_VOLUME_RATIO)
        )

        if not breakdown_mask.any():
            return {'detected': False, 'reason': 'no_fti_breakdown_found'}

        fti_idx = df[breakdown_mask].index[-1]
        fti_row = df.loc[fti_idx]
        v_ma_val = vol_ma.loc[fti_idx]
        volume_ratio = fti_row['Volume'] / v_ma_val if v_ma_val > 0 else 0
        breakdown_pct = (fti_row['Close'] - ice_level) / ice_level

        test_detected = False
        test_date = None
        test_vol_ratio = None
        df_after_fti = df[df.index > fti_idx].head(10)
        if len(df_after_fti) >= 1:
            for idx_test in df_after_fti.index:
                row_test = df_after_fti.loc[idx_test]
                near_ice = ice_level * (1 - self.thresholds.FTI_TEST_BAND * 1.5) <= row_test['High'] <= ice_level * (1 + self.thresholds.FTI_TEST_BAND)
                vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * self.thresholds.FTI_TEST_VOL_RATIO
                failed_recovery = row_test['Close'] < ice_level * (1 + self.thresholds.FTI_TEST_BAND/2)
                if near_ice and vol_shrinking and failed_recovery:
                    test_detected = True
                    test_date = idx_test
                    test_vol_ratio = round(row_test['Volume'] / vol_ma.loc[idx_test], 2)
                    break

        confidence = 0.50 + (0.2 if volume_ratio >= 2.0 else 0.1 if volume_ratio >= 1.5 else 0) + (0.1 if abs(breakdown_pct) >= 0.03 else 0) + (0.2 if test_detected else 0)
        return {
            'detected': True, 'date': fti_idx, 'ice_level': round(ice_level, 3), 'close_price': round(fti_row['Close'], 3),
            'breakdown_pct': round(breakdown_pct * 100, 2), 'volume_ratio': round(volume_ratio, 2),
            'test_detected': test_detected, 'test_date': test_date, 'test_vol_ratio': test_vol_ratio, 'confidence': round(min(confidence, 1.0), 2)
        }

    # --- VSA ---
    def detect_vsa_signals(self, lookback: int = 20) -> Dict:
        if self.data is None or len(self.data) < 20:
            return {'no_supply': {'detected': False}, 'no_demand': {'detected': False}, 'stopping_vol': {'detected': False}}

        df = self.data.tail(lookback).copy()
        vol_ma = df['Volume'].rolling(20, min_periods=1).mean()
        total_range = (df['High'] - df['Low']).replace(0, float('nan'))
        body_ratio = ((df['Close'] - df['Open']).abs() / total_range).fillna(0)
        close_position = ((df['Close'] - df['Low']) / total_range).fillna(0.5)

        no_supply_mask = (df['Close'] < df['Open']) & (body_ratio < self.thresholds.VSA_NO_SUPPLY_BODY_RATIO) & (df['Volume'] < vol_ma * self.thresholds.VSA_NO_SUPPLY_VOL_RATIO) & (close_position >= self.thresholds.VSA_NO_SUPPLY_CLOSE_POS)
        no_demand_mask = (df['Close'] > df['Open']) & (body_ratio < self.thresholds.VSA_NO_DEMAND_BODY_RATIO) & (df['Volume'] < vol_ma * self.thresholds.VSA_NO_DEMAND_VOL_RATIO) & (close_position <= self.thresholds.VSA_NO_DEMAND_CLOSE_POS)
        stopping_mask = (df['Volume'] > vol_ma * self.thresholds.VSA_STOPPING_VOL_RATIO) & (body_ratio < self.thresholds.VSA_STOPPING_BODY_RATIO) & (close_position >= self.thresholds.VSA_STOPPING_CLOSE_POS)

        res = {'no_supply': {'detected': False}, 'no_demand': {'detected': False}, 'stopping_vol': {'detected': False}}
        if no_supply_mask.any():
            idx = df[no_supply_mask].index[-1]
            res['no_supply'] = {
                'detected': True, 
                'date': idx, 
                'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2),
                'description': '无供应 - 缩量下跌，卖盘枯竭'
            }
        if no_demand_mask.any():
            idx = df[no_demand_mask].index[-1]
            res['no_demand'] = {
                'detected': True, 
                'date': idx, 
                'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2),
                'description': '无需求 - 缩量上涨，买盘不足'
            }
        if stopping_mask.any():
            idx = df[stopping_mask].index[-1]
            res['stopping_vol'] = {
                'detected': True, 
                'date': idx, 
                'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2),
                'description': '停止量 - 放量窄幅，主力吸筹'
            }
        return res

    # --- Divergence & Confirmation ---
    def detect_divergence(self, window: int = 30) -> Dict:
        if self.data is None or len(self.data) < window:
            return {'detected': False}
        df = self.data.tail(window).copy()
        if 'RSI' not in df.columns or df['RSI'].isna().all():
            return {'detected': False}
        mid = len(df) // 2
        df_e, df_l = df.iloc[:mid], df.iloc[mid:]
        if len(df_e) < 5 or len(df_l) < 5: return {'detected': False}

        if df_l['High'].max() > df_e['High'].max() and df_l['RSI'].max() < df_e['RSI'].max():
            return {'detected': True, 'type': 'top_divergence', 'confidence': 0.8}
        if df_l['Low'].min() < df_e['Low'].min() and df_l['RSI'].min() > df_e['RSI'].min():
            return {'detected': True, 'type': 'bottom_divergence', 'confidence': 0.8}
        return {'detected': False}
    # --- Advanced Meng Hongtao Patterns ---
    def detect_bag_holding(self) -> Dict:
        """检测 Bag Holding (极端抛售高潮)"""
        if self.data is None or len(self.data) < 20:
            return {'detected': False}
        df = self.data.tail(20)
        vol_ma = df['Volume'].rolling(20, min_periods=1).mean()
        
        # 逻辑：成交量极大（>3x MA），K线实体极小，收盘在下半部
        total_range = (df['High'] - df['Low']).replace(0, float('nan'))
        body_size = (df['Close'] - df['Open']).abs()
        body_ratio = body_size / total_range
        
        mask = (df['Volume'] > vol_ma * self.thresholds.VSA_BAG_HOLDING_VOL_RATIO) & \
               (body_ratio < self.thresholds.VSA_STOPPING_BODY_RATIO) & \
               (df['Low'] == df['Low'].rolling(10).min())
               
        if mask.any():
            idx = df[mask].index[-1]
            return {
                'detected': True, 
                'date': idx, 
                'vol_ratio': round(df.loc[idx, 'Volume'] / vol_ma.loc[idx], 2),
                'description': 'Bag Holding - 极端放量且窄幅，庄家大量接盘'
            }
        return {'detected': False}

    def detect_shakeout(self) -> Dict:
        """检测 Shakeout (终极震仓)"""
        # 逻辑：快速且深幅的下跌后迅速收回
        spring_res = self.detect_spring()
        if spring_res.get('detected'):
            latest = spring_res['latest_spring']
            if latest['breakdown_pct'] <= -self.thresholds.VSA_SHAKEOUT_DEPTH:
                return {
                    'detected': True, 
                    'date': latest['date'],
                    'depth': latest['breakdown_pct'],
                    'description': 'Shakeout - 剧烈震仓，深度洗盘后快速回收'
                }
        return {'detected': False}
