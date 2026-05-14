import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple, List, Any
from .base_detector import BaseDetector, USE_VECTORIZED
from ...config.settings import WyckoffConfig, WyckoffThresholds
from ..utils import TypeConverter, PhaseAdapter

logger = logging.getLogger(__name__)

class ReversalDetector(BaseDetector):
    """
    负责检测价格反转和趋势停止形态
    (Climax, AR, ST, Spring, Upthrust)
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, analysis_cache, bayesian_model=None, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds
        self._analysis_cache = analysis_cache
        self.bayesian_model = bayesian_model
        self._cache_warmed = False

    def _warm_up_indicator_cache(self):
        """预热常用指标"""
        if self._cache_warmed:
            return
        common_indicators = {
            'Volume_MA20': {'window': 20},
            'Low_Min_20': {'window': 20},
            'High_Max_20': {'window': 20},
            'ATR': {'period': 14}
        }
        if self._indicator_cache:
            self._indicator_cache.warm_up(common_indicators)
        self._cache_warmed = True

    def _detect_market_environment(self) -> str:
        """
        🔧 修复 P1-2: 检测市场环境（多头/空头/震荡）

        Returns:
            'bullish' - 多头市场（MA20 > MA50 > MA200）
            'bearish' - 空头市场（MA20 < MA50 < MA200）
            'neutral' - 震荡市场（均线纠缠）
        """
        try:
            if self.data is None or len(self.data) < 200:
                return 'neutral'

            current_price = self.data['Close'].iloc[-1]
            ma20 = self.data['Close'].rolling(20).mean().iloc[-1]
            ma50 = self.data['Close'].rolling(50).mean().iloc[-1]
            ma200 = self.data['Close'].rolling(200).mean().iloc[-1]

            # 多头排列
            if current_price > ma20 > ma50 > ma200:
                return 'bullish'
            # 空头排列
            elif current_price < ma20 < ma50 < ma200:
                return 'bearish'
            else:
                return 'neutral'
        except Exception:
            return 'neutral'

    def _classify_upthrust_with_context(
        self,
        breakout_vol_ratio: float,
        penetration_depth: float,
        market_env: str
    ) -> tuple:
        """
        🔧 修复 P1-2: 根据市场环境动态调整 UT 分类

        Args:
            breakout_vol_ratio: 突破量比
            penetration_depth: 穿透深度（百分比）
            market_env: 市场环境 ('bullish'/'bearish'/'neutral')

        Returns:
            (upthrust_type, is_valid, needs_secondary_test, description)
        """
        is_valid = True
        needs_secondary_test = False

        if market_env == 'bullish':
            # 多头市场：更宽容，倾向于认为是试探
            if breakout_vol_ratio < 1.0 and penetration_depth < 2.0:
                return 'type_3_safe', True, False, '缩量浅穿透，多头市场的正常试探'
            elif breakout_vol_ratio > 2.0 and penetration_depth > 3.0:
                return 'type_1_dangerous', False, True, '放量深穿透，多头市场需警惕转势'
            else:
                return 'type_2_neutral', True, True, '中性，等待二次测试'
        elif market_env == 'bearish':
            # 空头市场：更严格，倾向于警惕派发
            if breakout_vol_ratio > 1.8 and penetration_depth > 2.0:
                return 'type_1_dangerous', False, True, '弱势市场的放量突破，疑似派发'
            elif breakout_vol_ratio < 0.6 and penetration_depth < 1.0:
                return 'type_3_safe', True, False, '极度缩量，供应枯竭'
            else:
                return 'type_2_neutral', True, True, '中性，等待确认'
        else:
            # 震荡市场：使用原始标准
            if breakout_vol_ratio > 1.5 and penetration_depth > 3.0:
                return 'type_1_dangerous', False, True, '放量深穿透'
            elif breakout_vol_ratio < 0.8 and penetration_depth < 1.5:
                return 'type_3_safe', True, False, '缩量浅穿透'
            else:
                return 'type_2_neutral', True, True, '中性，需等待确认'

    # --- Climax, AR, ST ---
    def detect_climax(self) -> Dict:
        """检测高潮行为 (SC/BC)"""
        self._warm_up_indicator_cache()
        return self._analysis_cache.get_or_compute(
            "climax", self._detect_climax_impl
        )

    def _detect_climax_impl(self) -> Dict:
        if self.data is None or len(self.data) < 20:
            return {'detected': False}

        df = self.data.tail(40).copy()
        vol_ma, low_min, high_max = self._get_tech_indicators(20)
        
        # 获取 60 日最高/最低作为趋势背景参考
        high_60 = self.data['High'].rolling(60).max().reindex(df.index)
        low_60 = self.data['Low'].rolling(60).min().reindex(df.index)
        
        # 抛售高潮 (Selling Climax): 必须发生在下跌趋势背景下 (相对于60日高点跌幅 > 8%)
        sc_mask = (
            (df['Close'] < df['Open']) & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['Low'] == low_min.reindex(df.index)) &
            (df['Low'] < high_60 * 0.92)  # 趋势过滤
        )
        
        # 买入高潮 (Buying Climax): 必须发生上涨趋势背景下 (相对于60日低点涨幅 > 15%)
        bc_mask = (
            (df['Close'] > df['Open']) & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['High'] == high_max.reindex(df.index)) &
            (df['High'] > low_60 * 1.15)  # 趋势过滤
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

        if TypeConverter.is_date_like(climax_date):
            climax_ts = TypeConverter.to_timestamp(climax_date)
            sc_row = self.data.loc[self.data.index == climax_ts]
            if len(sc_row) > 0:
                sc_open = sc_row['Open'].iloc[0]
                sc_close = sc_row['Close'].iloc[0]
                sc_benchmark = (sc_open + sc_close) / 2.0
            else:
                sc_benchmark = climax_res['price']
        else:
            sc_benchmark = climax_res['price']

        if climax_res['type'] == 'selling_climax':
            ar_price = df_after['High'].max()
            ar_date = df_after['High'].idxmax()
            rebound_pct = (ar_price - sc_benchmark) / sc_benchmark if sc_benchmark > 0 else 0
            return {
                'detected': True, 'type': 'automatic_rally', 'date': ar_date, 'price': ar_price,
                'rebound_pct': round(rebound_pct, 4), 'sc_benchmark': round(sc_benchmark, 2)
            }
        else:
            ar_price = df_after['Low'].min()
            ar_date = df_after['Low'].idxmin()
            decline_pct = (ar_price - sc_benchmark) / sc_benchmark if sc_benchmark > 0 else 0
            bc_high = climax_res.get('price', 0)
            nominal_decline = (ar_price - bc_high) / bc_high if bc_high > 0 else 0
            return {
                'detected': True, 'type': 'automatic_reaction', 'date': ar_date, 'price': ar_price,
                'decline_pct': round(decline_pct, 4), 'sc_benchmark': round(sc_benchmark, 2),
                'climax_high': round(bc_high, 2), 'nominal_decline_pct': round(nominal_decline, 4),
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
        is_sc = climax_res['type'] == 'selling_climax'

        # 收集所有符合条件的ST (支持多次二次测试)
        all_tests = []

        for i in range(len(df_after)):
            row = df_after.iloc[i]
            if is_sc:
                price_test = row['Low'] <= climax_price * (1 + self.thresholds.JOC_TEST_BAND)
            else:
                price_test = row['High'] >= climax_price * (1 - self.thresholds.JOC_TEST_BAND)

            vol_test = row['Volume'] < climax_vol * self.thresholds.VOLUME_CONFIRMATION['weak']

            if price_test and vol_test:
                vol_ratio = row['Volume'] / climax_vol if climax_vol > 0 else 1.0
                all_tests.append({
                    'date': df_after.index[i],
                    'price': float(row['Low'] if is_sc else row['High']),
                    'volume': float(row['Volume']),
                    'vol_ratio': round(vol_ratio, 3),
                    'test_number': len(all_tests) + 1,
                })

        if not all_tests:
            return {
                'detected': False,
                'all_secondary_tests': [],
                'test_count': 0,
            }

        # 最后一笔ST
        last_test = all_tests[-1]
        vol_ratio = last_test['vol_ratio']
        confirmed = vol_ratio < 0.4

        # 检查ST序列是否递减量缩 (Wyckoff: 每次ST量应递减)
        st_sequence_trend = 'stable'
        if len(all_tests) >= 2:
            vol_trend = all_tests[-1]['vol_ratio'] / max(all_tests[0]['vol_ratio'], 1e-9)
            if vol_trend < 0.5:
                st_sequence_trend = 'declining'
            elif vol_trend > 1.2:
                st_sequence_trend = 'increasing'

        return {
            'detected': True,
            'type': 'secondary_test',
            'date': last_test['date'],
            'price': last_test['price'],
            'volume': last_test['volume'],
            'climax_volume': float(climax_vol),
            'st_vol_ratio': round(vol_ratio, 3),
            'supply_exhausted': confirmed,
            'confidence': 0.8 if confirmed else 0.4,
            'all_secondary_tests': all_tests,
            'test_count': len(all_tests),
            'st_sequence_trend': st_sequence_trend,
        }

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
        if PhaseAdapter.is_distribution(self._current_phase):
            return {'detected': False, 'reason': 'distribution_phase_no_spring'}

        df = self.data.tail(lookback).copy()
        support = self._calculate_support_level_spring(df)
        if support is None:
            return {'detected': False, 'reason': 'no_trading_range'}
        range_pct = (df['High'].max() - df['Low'].min()) / max(df['Low'].min(), 1e-9)
        if range_pct >= self.config.spring_range_threshold:
            return {'detected': False, 'reason': 'range_too_wide'}

        search_window = min(30, len(df))
        recent = df.tail(search_window).reset_index(drop=True)
        if len(recent) < 4:
            return {'detected': False, 'reason': 'insufficient_search_data'}

        springs = []
        if USE_VECTORIZED:
            try:
                springs = self._detect_spring_vectorized(recent, support)
            except Exception as e:
                logger.warning(f"Vectorized Spring detection failed: {e}. Falling back to iterative.")
                springs = self._detect_spring_iterative(recent, support)
        else:
            springs = self._detect_spring_iterative(recent, support)

        if springs:
            fresh_springs = [s for s in springs if not self._is_signal_stale(s['date'], 'spring')]
            if fresh_springs:
                return {
                    'detected': True, 'signals': springs, 'fresh_signals': fresh_springs,
                    'latest_spring': fresh_springs[-1], 'method': 'enhanced_spring_detection_with_decay',
                    'signal_age_days': self._get_signal_age_days(fresh_springs[-1]['date'])
                }
            return {'detected': False, 'reason': 'all_spring_signals_stale'}
        return {'detected': False, 'reason': 'no_spring_found'}

    def _calculate_support_level_spring(self, df: pd.DataFrame) -> Optional[float]:
        if len(df) < 20: return None
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

    def _calculate_spring_follow_score(self, nxt: pd.Series, d2: pd.Series) -> int:
        score = 0
        if nxt['Close'] > nxt['Open']: score += 3
        if nxt['Close'] > (nxt['High'] + nxt['Low']) / 2: score += 2
        if d2 is not None and d2['Close'] > nxt['Close']: score += 2
        if d2 is not None and (d2['High'] > nxt['High'] and d2['Low'] > nxt['Low'] and d2['Close'] > nxt['Close']):
            score += 3
        return score

    def _count_recovery_days(self, recent: pd.DataFrame, breakdown_idx: int, support: float) -> int:
        """
        计算从跌破到收回支持位实际所需天数
        Wyckoff理论: 1-3天内收回 = 有效Spring
        """
        recovery_days = 0
        for j in range(breakdown_idx + 1, min(breakdown_idx + 10, len(recent))):
            recovery_days += 1
            if recent.iloc[j]['Close'] > support:
                return recovery_days
        return recovery_days

    def _detect_spring_vectorized(self, recent: pd.DataFrame, support: float) -> List[Dict]:
        n = len(recent)
        lows, closes, highs, opens, volumes = recent['Low'].values, recent['Close'].values, recent['High'].values, recent['Open'].values, recent['Volume'].values
        breakdown_mask = lows[:-2] < support
        safe_support = np.where(support > 1e-9, support, 1.0)
        breakdown_pcts = (safe_support - lows[:-2]) / safe_support * 100
        valid_breakdown = breakdown_mask & (breakdown_pcts >= 1) & (breakdown_pcts <= 5)
        recovery_mask = closes[1:-1] > support
        bullish_recovery = closes[1:-1] > closes[:-2]
        safe_volumes = np.where(volumes[:-2] > 0, volumes[:-2], 1.0)
        vol_ratios = volumes[1:-1] / safe_volumes
        valid_volume = vol_ratios > 1.0
        daily_ranges = highs[1:-1] - lows[1:-1]
        safe_ranges = np.where(daily_ranges == 0, 1.0, daily_ranges)
        close_positions = (closes[1:-1] - lows[1:-1]) / safe_ranges
        high_close = close_positions >= 0.7
        spring_candidates = valid_breakdown & recovery_mask & bullish_recovery & valid_volume & high_close
        candidate_indices = np.where(spring_candidates)[0]
        springs = []
        for i in candidate_indices:
            cur_idx, nxt_idx, d2_idx = i, i + 1, i + 2
            if d2_idx >= n: continue
            follow_score = self._calculate_spring_follow_score(recent.iloc[nxt_idx], recent.iloc[d2_idx])
            breakdown_pct = breakdown_pcts[i]
            recovery_vol_r, nxt_close_pos = float(vol_ratios[i]), float(close_positions[i])
            recovery_pct = (closes[nxt_idx] - support) / support * 100 if support > 0 else 0
            actual_recovery_days = self._count_recovery_days(recent, i, support)
            total_score = min(recovery_vol_r * 15, 30) + min(nxt_close_pos * 25, 20) + min(follow_score * 3, 30) + min(recovery_pct, 10) + 10
            total_score = min(total_score, 100)
            
            # Spring 量能分类与 ST 强制绑定 (符合 David Weis 原著)
            mean_vol = recent['Volume'].mean()
            breakdown_vol_ratio = float(volumes[cur_idx] / mean_vol) if mean_vol > 0 else 1.0
            penetration_depth = breakdown_pcts[i]
            needs_secondary_test = False
            is_valid = True
            
            if breakdown_vol_ratio > 1.5 and penetration_depth > 3.0:
                spring_type = 'type_1_dangerous'      # 放量深跌，危险，不能买
                is_valid = False
                needs_secondary_test = True
            elif breakdown_vol_ratio < 0.8 and penetration_depth < 1.5:
                spring_type = 'type_3_safe'           # 缩量浅跌，安全，可立即买
                needs_secondary_test = False
            else:
                spring_type = 'type_2_neutral'        # 中性，需等待 ST 确认
                needs_secondary_test = True

            if is_valid:
                springs.append({
                    'breakdown_price': {
                        "value": round(float(lows[cur_idx]), 2),
                        "derivation": "lowest_in_breakdown_bar",
                        "note": "跌破支撑位的价格点"
                    },
                    'support_level': {
                        "value": round(support, 2),
                        "derivation": "p5_p20_cluster_low",
                        "note": "基于近期低点簇计算的支撑位"
                    },
                    'recovery_price': round(float(closes[nxt_idx]), 2), 'recovery_days': actual_recovery_days,
                    'volume_ratio': round(recovery_vol_r, 2), 'close_position': round(nxt_close_pos * 100, 1),
                    'follow_up_score': follow_score, 'total_score': min(total_score, 100),
                    'strength': 'strong' if total_score > 70 else 'normal' if total_score > 50 else 'weak',
                    'breakdown_volume_ratio': round(breakdown_vol_ratio, 2),
                    'spring_type': spring_type,
                    'needs_secondary_test': needs_secondary_test,
                    'penetration_depth': round(float(penetration_depth), 2)
                })
        return springs

    def _detect_spring_iterative(self, recent: pd.DataFrame, support: float) -> List[Dict]:
        springs = []
        breakdown_mask = recent['Low'] < support
        candidate_indices = recent.index[breakdown_mask]
        for idx in candidate_indices:
            i = recent.index.get_loc(idx)
            if i + 2 >= len(recent): continue
            cur, nxt, d2 = recent.iloc[i], recent.iloc[i + 1], recent.iloc[i + 2]
            breakdown_pct = (support - cur['Low']) / support * 100
            if breakdown_pct > 5 or nxt['Close'] <= support or nxt['Close'] <= cur['Close']: continue
            recovery_vol_r = nxt['Volume'] / cur['Volume'] if cur['Volume'] > 0 else 1
            if recovery_vol_r <= 1.0: continue
            nxt_range = nxt['High'] - nxt['Low']
            nxt_close_pos = (nxt['Close'] - nxt['Low']) / nxt_range if nxt_range > 0 else 0.5
            if nxt_close_pos < 0.7: continue
            follow_score = self._calculate_spring_follow_score(nxt, d2)
            recovery_pct = (nxt['Close'] - support) / support * 100 if support > 0 else 0
            actual_recovery_days = self._count_recovery_days(recent, i, support)
            total_score = min(recovery_vol_r * 15, 30) + min(nxt_close_pos * 25, 20) + min(follow_score * 3, 30) + min(recovery_pct, 10) + 10
            
            # Spring 量能分类与 ST 强制绑定 (符合 David Weis 原著)
            mean_vol = recent['Volume'].mean()
            breakdown_vol_ratio = float(cur['Volume'] / mean_vol) if mean_vol > 0 else 1.0
            penetration_depth = breakdown_pct
            needs_secondary_test = False
            is_valid = True
            
            if breakdown_vol_ratio > 1.5 and penetration_depth > 3.0:
                spring_type = 'type_1_dangerous'      # 放量深跌，危险，不能买
                is_valid = False
                needs_secondary_test = True
            elif breakdown_vol_ratio < 0.8 and penetration_depth < 1.5:
                spring_type = 'type_3_safe'           # 缩量浅跌，安全，可立即买
                needs_secondary_test = False
            else:
                spring_type = 'type_2_neutral'        # 中性，需等待 ST 确认
                needs_secondary_test = True

            if is_valid:
                springs.append({
                    'date': nxt.name, 'breakdown_date': cur.name, 
                    'breakdown_price': {
                        "value": round(float(cur['Low']), 2),
                        "derivation": "lowest_in_breakdown_bar",
                        "note": "跌破支撑位的价格点"
                    },
                    'support_level': {
                        "value": round(support, 2),
                        "derivation": "p5_p20_cluster_low",
                        "note": "基于近期低点簇计算的支撑位"
                    }, 
                    'recovery_price': round(float(nxt['Close']), 2),
                    'recovery_days': actual_recovery_days, 'volume_ratio': round(recovery_vol_r, 2),
                    'close_position': round(nxt_close_pos * 100, 1), 'follow_up_score': follow_score,
                    'total_score': min(total_score, 100), 'strength': 'strong' if total_score > 70 else 'normal' if total_score > 50 else 'weak',
                    'breakdown_volume_ratio': round(breakdown_vol_ratio, 2),
                    'spring_type': spring_type,
                    'needs_secondary_test': needs_secondary_test,
                    'penetration_depth': round(float(penetration_depth), 2)
                })
        return springs

    def detect_upthrust(self, lookback: int = None) -> Dict:
        lookback = lookback or self.config.spring_lookback
        cache_key = f"upthrust_{lookback}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_upthrust_impl, lookback
        )

    def _detect_upthrust_impl(self, lookback: int) -> Dict:
        if self.data is None or len(self.data) < 30: return {'detected': False}
        df = self.data.tail(lookback).copy()
        resistance_level = self._check_upthrust_preconditions(df)
        if resistance_level is None: return {'detected': False}
        upthrusts = self._find_and_verify_upthrusts(df, resistance_level)
        if upthrusts: return {'detected': True, 'upthrusts': upthrusts, 'latest_upthrust': upthrusts[-1]}
        return {'detected': False}

    def _check_upthrust_preconditions(self, df: pd.DataFrame) -> Optional[float]:
        M = self.config.breakout_search_window
        if len(df) <= M: return None
        range_df = df.iloc[:-M]
        high_max, low_min = range_df['High'].max(), range_df['Low'].min()
        if (high_max - low_min) / low_min < self.config.spring_range_threshold: return high_max
        return None

    def _find_and_verify_upthrusts(self, df: pd.DataFrame, resistance_level: float):
        M = self.config.breakout_search_window
        breakout_df = df.tail(M)
        upthrusts, breakout_indices = [], breakout_df.index[breakout_df['High'] > resistance_level]
        rejection_indices = df.index[df['Close'] < resistance_level]

        mean_vol = df['Volume'].mean()

        # 🔧 修复 P1-2: 检测市场环境，用于动态调整 UT 分类
        market_env = self._detect_market_environment()

        for b_idx in breakout_indices[-3:]:
            later_rejections = rejection_indices[rejection_indices > b_idx]
            if len(later_rejections) > 0:
                r_idx = later_rejections[0]
                days_to_reject = (df.index.get_indexer([r_idx])[0] - df.index.get_indexer([b_idx])[0])
                if days_to_reject <= self.config.spring_max_recovery_days:
                    b_vol, r_vol = df.loc[b_idx, 'Volume'], df.loc[r_idx, 'Volume']

                    b_high = df.loc[b_idx, 'High']
                    breakout_vol_ratio = b_vol / mean_vol if mean_vol > 0 else 1.0
                    penetration_depth = (b_high - resistance_level) / resistance_level * 100

                    close_pos = (df.loc[r_idx, 'High'] - df.loc[r_idx, 'Close']) / (df.loc[r_idx, 'High'] - df.loc[r_idx, 'Low'] + 1e-6)
                    follow_through = df[df.index > r_idx].head(3)
                    ft_quality = (follow_through['Low'] < df.loc[r_idx, 'Low']).sum() / len(follow_through) * 100 if len(follow_through) > 0 else 0

                    # 🔧 修复 P1-2: 使用市场环境加权的 UT 分类
                    upthrust_type, is_valid, needs_secondary_test, ut_note = self._classify_upthrust_with_context(
                        breakout_vol_ratio, penetration_depth, market_env
                    )

                    upthrusts.append({
                        'date': r_idx, 'breakout_date': b_idx, 'breakout_price': b_high,
                        'resistance_level': {
                            "value": round(float(resistance_level), 2),
                            "derivation": "max_high_before_breakout",
                            "note": "近期交易区间上沿阻力位"
                        },
                        'rejection_price': round(float(df.loc[r_idx, 'Close']), 2),
                        'rejection_days': int(days_to_reject), 'close_from_high': round(close_pos, 2),
                        'follow_through_quality': round(ft_quality, 2),
                        'breakout_volume_ratio': round(breakout_vol_ratio, 2),
                        'penetration_depth': round(penetration_depth, 2),
                        'upthrust_type': upthrust_type,
                        'needs_secondary_test': needs_secondary_test,
                        'is_valid': is_valid,
                        'market_environment': market_env,  # 🔧 新增：记录市场环境
                        'classification_note': ut_note  # 🔧 新增：分类说明
                    })
        return upthrusts
