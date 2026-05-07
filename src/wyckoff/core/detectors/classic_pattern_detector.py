import pandas as pd
from typing import Dict, Optional, Tuple, List, Any
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig, WyckoffThresholds
from ..utils import TypeConverter

class ClassicPatternDetector(BaseDetector):
    """负责检测经典威科夫形态 (Climax, Spring, Upthrust, JOC, FTI, VSA, Divergence)"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, analysis_cache):
        super().__init__()
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
        # 确保指标列存在
        vol_ma = self.data['Volume_MA20'] if 'Volume_MA20' in self.data.columns else self.data['Volume'].rolling(20).mean()
        low_min = self.data['Low_Min_20'] if 'Low_Min_20' in self.data.columns else self.data['Low'].rolling(20).min()
        high_max = self.data['High_Max_20'] if 'High_Max_20' in self.data.columns else self.data['High'].rolling(20).max()
        
        # 抛售高潮 (Selling Climax)
        sc_mask = (
            (df['Close'] < df['Open']) & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['Low'] == low_min.reindex(df.index))
        )
        
        # 买入高潮 (Buying Climax)
        bc_mask = (
            (df['Close'] > df['Open']) & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['High'] == high_max.reindex(df.index))
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

        # 计算SC（Climax）的实体中位值作为基准点，避免用极值造成的人为夸大
        # 使用统一的类型转换工具（替换分散的类型检查）
        if TypeConverter.is_date_like(climax_date):
            climax_ts = TypeConverter.to_timestamp(climax_date)
            sc_row = self.data.loc[self.data.index == climax_ts]
            if len(sc_row) > 0:
                sc_open = sc_row['Open'].iloc[0]
                sc_close = sc_row['Close'].iloc[0]
                # 使用实体中位值（(Open+Close)/2）而非极值
                sc_benchmark = (sc_open + sc_close) / 2.0
            else:
                sc_benchmark = climax_res['price']
        else:
            sc_benchmark = climax_res['price']

        if climax_res['type'] == 'selling_climax':
            # 吸筹期的SC后找AR（向上反弹）
            ar_price = df_after['High'].max()
            ar_date = df_after['High'].idxmax()
            # 计算从SC实体中位值的真实反弹百分比
            rebound_pct = (ar_price - sc_benchmark) / sc_benchmark if sc_benchmark > 0 else 0
            return {
                'detected': True,
                'type': 'automatic_rally',
                'date': ar_date,
                'price': ar_price,
                'rebound_pct': round(rebound_pct, 4),
                'sc_benchmark': round(sc_benchmark, 2)
            }
        else:
            # 派发期的BC后找AR（向下回落）
            ar_price = df_after['Low'].min()
            ar_date = df_after['Low'].idxmin()
            # 计算从BC实体中位值的真实回落百分比
            decline_pct = (ar_price - sc_benchmark) / sc_benchmark if sc_benchmark > 0 else 0
            # 同时计算从BC高点的名义回落（仅用于对比参考）
            bc_high = climax_res.get('price', 0)
            nominal_decline = (ar_price - bc_high) / bc_high if bc_high > 0 else 0
            return {
                'detected': True,
                'type': 'automatic_reaction',
                'date': ar_date,
                'price': ar_price,
                'decline_pct': round(decline_pct, 4),
                'sc_benchmark': round(sc_benchmark, 2),
                'climax_high': round(bc_high, 2),
                'nominal_decline_pct': round(nominal_decline, 4),
            }

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
        climax_vol = climax_res.get('volume', 0)

        if climax_res['type'] == 'selling_climax':
            test_mask = (df_after['Low'] <= climax_price * (1 + self.thresholds.JOC_TEST_BAND)) & \
                        (df_after['Volume'] < climax_vol * self.thresholds.VOLUME_CONFIRMATION['weak'])
            if test_mask.any():
                idx = df_after[test_mask].index[-1]
                st_vol = df_after.loc[idx, 'Volume']
                vol_ratio = st_vol / climax_vol if climax_vol > 0 else 1.0
                confirmed = vol_ratio < 0.4
                return {
                    'detected': True, 'type': 'secondary_test', 'date': idx,
                    'price': df_after.loc[idx, 'Low'],
                    'volume': float(st_vol),
                    'climax_volume': float(climax_vol),
                    'st_vol_ratio': round(vol_ratio, 3),
                    'supply_exhausted': confirmed,
                    'confidence': 0.8 if confirmed else 0.4,
                    'description': (
                        f"二次测试确认{'✅' if confirmed else '⚠️'} — "
                        f"ST成交量/Climax成交量 = {vol_ratio:.1%}"
                        f"{' < 40% ✓ 供应耗尽' if confirmed else ' ≥ 40% 需求尚未完全耗尽'}"
                    ),
                }
        else:
            test_mask = (df_after['High'] >= climax_price * (1 - self.thresholds.JOC_TEST_BAND)) & \
                        (df_after['Volume'] < climax_vol * self.thresholds.VOLUME_CONFIRMATION['weak'])
            if test_mask.any():
                idx = df_after[test_mask].index[-1]
                st_vol = df_after.loc[idx, 'Volume']
                vol_ratio = st_vol / climax_vol if climax_vol > 0 else 1.0
                confirmed = vol_ratio < 0.4
                return {
                    'detected': True, 'type': 'secondary_test', 'date': idx,
                    'price': df_after.loc[idx, 'High'],
                    'volume': float(st_vol),
                    'climax_volume': float(climax_vol),
                    'st_vol_ratio': round(vol_ratio, 3),
                    'supply_exhausted': confirmed,
                    'confidence': 0.8 if confirmed else 0.4,
                    'description': (
                        f"二次测试确认{'✅' if confirmed else '⚠️'} — "
                        f"ST成交量/Climax成交量 = {vol_ratio:.1%}"
                        f"{' < 40% ✓ 需求耗尽' if confirmed else ' ≥ 40% 抛压尚未完全释放'}"
                    ),
                }

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

        # 阶段感知验证：派发阶段直接拒绝（当阶段已识别时）
        if self._current_phase and ('Distribution' in self._current_phase or '派发' in self._current_phase):
            return {'detected': False, 'reason': 'distribution_phase_no_spring'}

        df = self.data.tail(lookback).copy()

        support = self._calculate_support_level_spring(df)
        if support is None:
            return {'detected': False, 'reason': 'no_trading_range'}

        # 验证盘整区间幅度
        range_pct = (df['High'].max() - df['Low'].min()) / df['Low'].min()
        if range_pct >= self.config.spring_range_threshold:
            return {'detected': False, 'reason': 'range_too_wide'}

        # 在最近30根K线中搜索Spring
        search_window = min(30, len(df))
        recent = df.tail(search_window)
        if len(recent) < 4:
            return {'detected': False, 'reason': 'insufficient_search_data'}

        # 使用全数据计算的 Volume_MA20 作为成交量基线，避免窗口边缘数据不可用
        vol_ma20 = (recent['Volume_MA20'] if 'Volume_MA20' in recent.columns
                    else df['Volume'].rolling(20, min_periods=1).mean().tail(search_window))
        springs = []

        for i in range(0, len(recent) - 2):
            cur = recent.iloc[i]
            nxt = recent.iloc[i + 1]
            d2 = recent.iloc[i + 2]

            # 条件1：价格跌破支撑位（允许3%误差缓冲）
            if cur['Low'] >= support * 0.97:
                continue

            # 条件2：次日收盘回到支撑位之上
            if nxt['Close'] <= support:
                continue

            # 条件3：次日收盘高于跌破日收盘（阳线确认）
            if nxt['Close'] <= cur['Close']:
                continue

            # 条件4：Spring当日放量（> 1.2倍20日均量）
            cur_vol_r = cur['Volume'] / vol_ma20.iloc[i] if vol_ma20.iloc[i] > 0 else 1
            if cur_vol_r < 1.2:
                continue

            # 条件5：下影线分析（下影线 >= 实体1.5倍）
            body = abs(cur['Close'] - cur['Open'])
            lower_shadow = max(0, min(cur['Open'], cur['Close']) - cur['Low'])
            shadow_r = lower_shadow / (body + 0.001)
            if shadow_r < 1.5:
                continue

            # 条件6：跟随确认评分
            follow_score = self._calculate_spring_follow_score(nxt, d2)

            # 综合评分（100分制）
            recovery_pct = (nxt['Close'] - support) / support * 100 if support > 0 else 0
            total_score = (
                min(cur_vol_r * 10, 30) +      # 成交量: 0-30
                min(shadow_r * 5, 20) +         # 影线: 0-20
                min(follow_score * 3, 30) +     # 跟随: 0-30
                min(recovery_pct, 10) +          # 收回幅度: 0-10
                10                                # 基础分
            )
            total_score = min(total_score, 100)

            spring = {
                'date': nxt.name,
                'breakdown_date': cur.name,
                'breakdown_price': round(float(cur['Low']), 2),
                'support_level': round(support, 2),
                'recovery_price': round(float(nxt['Close']), 2),
                'recovery_days': 1,
                'volume_ratio': round(cur_vol_r, 2),
                'shadow_ratio': round(shadow_r, 2),
                'follow_up_score': follow_score,
                'total_score': total_score,
                'strength': 'strong' if total_score > 70 else 'normal' if total_score > 50 else 'weak',
            }
            springs.append(spring)

        if springs:
            return {
                'detected': True,
                'signals': springs,
                'latest_spring': springs[-1],
                'method': 'enhanced_spring_detection',
            }
        return {'detected': False, 'reason': 'no_spring_found'}

    def _calculate_support_level_spring(self, df: pd.DataFrame) -> Optional[float]:
        """
        计算盘整区间下沿支撑位（5%分位值 + 低点聚类均值）
        """
        if len(df) < 20:
            return None

        lows = df['Low'].values
        sorted_lows = sorted(lows)

        p5_idx = max(0, int(len(sorted_lows) * 0.05))
        support = sorted_lows[p5_idx]

        p20_idx = max(0, int(len(sorted_lows) * 0.20))
        low_cluster = [l for l in sorted_lows if l <= sorted_lows[p20_idx]]
        if len(low_cluster) > 1:
            cluster_avg = sum(low_cluster) / len(low_cluster)
            support = max(support, cluster_avg)

        return round(float(support), 2)

    def _calculate_spring_follow_score(
        self, nxt: pd.Series, d2: pd.Series
    ) -> int:
        """
        计算Spring跟随确认评分（满分10分）

        6a: 次日阳线 +3
        6b: 次日收盘在日内高位 +2
        6c: 第三天继续上涨 +2（可选）
        6d: 出现三高(HH/HL/HC) +3（可选）
        """
        score = 0

        if nxt['Close'] > nxt['Open']:
            score += 3

        if nxt['Close'] > (nxt['High'] + nxt['Low']) / 2:
            score += 2

        if d2 is not None and d2['Close'] > nxt['Close']:
            score += 2

        if d2 is not None and (
            d2['High'] > nxt['High']
            and d2['Low'] > nxt['Low']
            and d2['Close'] > nxt['Close']
        ):
            score += 3

        return score

    @staticmethod
    def validate_spring_with_phase(spring_result: Dict, phase_analysis: Dict) -> Dict:
        """
        用阶段背景验证Spring的有效性

        Args:
            spring_result: detect_spring() 的返回结果
            phase_analysis: 阶段分析结果，需包含 'phase' 键

        Returns:
            {'valid': bool, 'confidence': str, 'reason': str}
        """
        phase = phase_analysis.get('phase', '')

        if any(vp in phase for vp in ['Accumulation', 'Reaccumulation', '积累']):
            has_sc = phase_analysis.get('has_sc', False)
            has_st = phase_analysis.get('has_st', False)
            if has_sc and has_st:
                return {'valid': True, 'confidence': 'high', 'reason': '完整吸筹结构 + Spring'}
            return {'valid': True, 'confidence': 'medium', 'reason': '吸筹阶段，但缺少完整前置结构'}

        if 'Distribution' in phase or '派发' in phase:
            return {'valid': False, 'confidence': 'low', 'reason': '派发阶段的Spring往往是失败的陷阱'}

        if 'Markup' in phase or '上涨' in phase:
            return {'valid': True, 'confidence': 'medium', 'reason': '上涨趋势中的Spring可能是回调买点'}

        return {'valid': True, 'confidence': 'low', 'reason': '阶段不明，保守对待'}

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
                
                max_reject_days = self.config.spring_max_recovery_days
                if days_to_reject <= max_reject_days:
                    b_vol = df.loc[b_idx, 'Volume']
                    r_vol = df.loc[r_idx, 'Volume']
                    close_pos = (df.loc[r_idx, 'High'] - df.loc[r_idx, 'Close']) / (df.loc[r_idx, 'High'] - df.loc[r_idx, 'Low'] + 1e-6)
                    
                    # 跟随确认 (P1 #3.2)：Upthrust 之后 3 日内需出现更低点
                    follow_through = df[df.index > r_idx].head(3)
                    ft_quality = 0
                    if len(follow_through) > 0:
                        lower_lows = (follow_through['Low'] < df.loc[r_idx, 'Low']).sum()
                        ft_quality = (lower_lows / len(follow_through)) * 100

                    if r_vol > b_vol * 1.1 or close_pos > 0.7:
                        upthrusts.append({
                            'date': r_idx,
                            'breakout_date': b_idx,
                            'breakout_price': df.loc[b_idx, 'High'],
                            'resistance_level': resistance_level,
                            'rejection_price': df.loc[r_idx, 'Close'],
                            'rejection_days': int(days_to_reject),
                            'close_from_high': round(close_pos, 2),
                            'follow_through_quality': round(ft_quality, 2)
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
        spring_res = self.detect_spring()
        if spring_res.get('detected'):
            latest = spring_res['latest_spring']
            support = latest['support_level']
            breakdown_price = latest['breakdown_price']
            if support > 0:
                breakdown_pct = (support - breakdown_price) / support
                if breakdown_pct >= self.thresholds.VSA_SHAKEOUT_DEPTH:
                    return {
                        'detected': True,
                        'date': latest['date'],
                        'depth': round(breakdown_pct * 100, 2),
                        'description': 'Shakeout - 剧烈震仓，深度洗盘后快速回收'
                    }
        return {'detected': False}
