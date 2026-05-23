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
        
        total_range = (df['High'] - df['Low']).replace(0, 1e-9)
        close_pct = (df['Close'] - df['Low']) / total_range

        # 抛售高潮 (Selling Climax): 必须发生在下跌趋势背景下 (相对于60日高点跌幅 > 8%)
        sc_bar_mask = (df['Close'] < df['Open']) | ((df['Close'] >= df['Open']) & (close_pct >= 0.40))
        sc_mask = (
            sc_bar_mask & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['Low'] == low_min.reindex(df.index)) &
            (df['Low'] < high_60 * 0.92)  # 趋势过滤
        )
        
        # 买入高潮 (Buying Climax): 必须发生上涨趋势背景下 (相对于60日低点涨幅 > 15%)
        bc_bar_mask = (df['Close'] > df['Open']) | ((df['Close'] <= df['Open']) & (close_pct <= 0.60))
        bc_mask = (
            bc_bar_mask & 
            (df['Volume'] > vol_ma.reindex(df.index) * self.thresholds.VOLUME_CONFIRMATION['strong']) & 
            (df['High'] == high_max.reindex(df.index)) &
            (df['High'] > low_60 * 1.15)  # 趋势过滤
        )
        
        if sc_mask.any():
            idx = df[sc_mask].index[-1]
            climax = {'detected': True, 'type': 'selling_climax', 'date': idx, 'price': df.loc[idx, 'Low'], 'volume': df.loc[idx, 'Volume']}
            self._verify_climax_confirmation(climax)
            return climax
        if bc_mask.any():
            idx = df[bc_mask].index[-1]
            climax = {'detected': True, 'type': 'buying_climax', 'date': idx, 'price': df.loc[idx, 'High'], 'volume': df.loc[idx, 'Volume']}
            self._verify_climax_confirmation(climax)
            return climax
            
        return {'detected': False}

    def _verify_climax_confirmation(self, climax_res: dict):
        """
        验证高潮信号是否已确认 (P1 #6)
        SC 确认：AR 反弹需收复 (Benchmark-Low) 的 50%。
        Benchmark = (Open+Close)/2
        """
        climax_date = climax_res['date']
        df = self.data
        try:
            climax_row = df.loc[climax_date]
            benchmark = (climax_row['Open'] + climax_row['Close']) / 2.0
            climax_res['sc_benchmark'] = float(benchmark)
            
            # 查找之后 5 日的 AR
            df_after = df[df.index > climax_date].head(5)
            if len(df_after) == 0:
                climax_res['is_confirmed'] = False
                return

            if climax_res['type'] == 'selling_climax':
                # SC 确认逻辑
                max_high = df_after['High'].max()
                climax_low = climax_res['price']
                total_drop = benchmark - climax_low
                recovery = max_high - climax_low
                
                if total_drop > 0 and recovery >= total_drop * 0.5:
                    climax_res['is_confirmed'] = True
                    climax_res['confirmation_date'] = df_after['High'].idxmax()
                else:
                    climax_res['is_confirmed'] = False
            else:
                # BC 确认逻辑：AR 不能有效跌破 BC 发生前的支撑位
                # 获取 BC 前的支撑 (取前20日最低)
                pre_bc_df = df[df.index < climax_date].tail(20)
                if len(pre_bc_df) > 0:
                    support = pre_bc_df['Low'].min()
                    min_low_after = df_after['Low'].min()
                    if min_low_after >= support:
                        climax_res['is_confirmed'] = True
                        climax_res['confirmation_date'] = df_after['Low'].idxmin()
                    else:
                        climax_res['is_confirmed'] = False
                else:
                    climax_res['is_confirmed'] = True # 数据不足默认通过，但在报告中标记
        except Exception:
            climax_res['is_confirmed'] = False

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
        df_after = self.data[self.data.index > climax_date].head(15)
        if len(df_after) == 0:
            return {'detected': False}

        if TypeConverter.is_date_like(climax_date):
            try:
                climax_ts = pd.to_datetime(climax_date)
                if self.data.index.tz is not None and climax_ts.tz is None:
                    climax_ts = climax_ts.tz_localize('UTC').tz_convert(self.data.index.tz)
                elif self.data.index.tz is None and climax_ts.tz is not None:
                    climax_ts = climax_ts.tz_localize(None)
                
                # 寻找最接近的 index（时间差在 1 秒内即为同一根K线）
                time_diffs = np.abs((self.data.index - climax_ts).total_seconds())
                min_diff_idx = np.argmin(time_diffs)
                if time_diffs[min_diff_idx] < 1.0:
                    sc_row = self.data.iloc[[min_diff_idx]]
                else:
                    sc_row = self.data.loc[self.data.index == climax_ts]
            except Exception:
                sc_row = self.data.loc[self.data.index == climax_date]
            
            if len(sc_row) > 0:
                sc_open = sc_row['Open'].iloc[0]
                sc_close = sc_row['Close'].iloc[0]
                sc_benchmark = (sc_open + sc_close) / 2.0
            else:
                sc_benchmark = climax_res['price']
        else:
            sc_benchmark = climax_res['price']

        ar_min_pct = self.thresholds.AR_MIN_REBOUND_PCT / 100.0

        if climax_res['type'] in ('selling_climax', 'stopping_volume', 'local_extreme_low'):
            ar_price = None
            ar_date = None
            detection_layer = None

            # 层级 1：Swing 摆动过滤（优先）
            if len(df_after) >= 7:
                for i in range(2, len(df_after) - 2):
                    h = df_after['High'].iloc[i]
                    if (h >= df_after['High'].iloc[i-1] and h >= df_after['High'].iloc[i-2] and
                        h >= df_after['High'].iloc[i+1] and h >= df_after['High'].iloc[i+2]):
                        ar_price = float(h)
                        ar_date = df_after.index[i]
                        detection_layer = 'swing_high'
                        break

            # 层级 2：立即反弹检测（1-3 天）
            if ar_price is None:
                df_3 = df_after.head(3)
                if len(df_3) > 0:
                    max_high_idx = df_3['High'].idxmax()
                    max_high_val = float(df_3['High'].max())
                    if (max_high_val - sc_benchmark) / sc_benchmark >= ar_min_pct:
                        ar_price = max_high_val
                        ar_date = max_high_idx
                        detection_layer = 'immediate_rebound'

            # 层级 3：5日扩展检测（1-5 天）
            if ar_price is None:
                df_5 = df_after.head(5)
                if len(df_5) > 0:
                    max_high_idx = df_5['High'].idxmax()
                    max_high_val = float(df_5['High'].max())
                    if (max_high_val - sc_benchmark) / sc_benchmark >= ar_min_pct:
                        ar_price = max_high_val
                        ar_date = max_high_idx
                        detection_layer = '5d_extended'

            # 层级 4：15 天极值兜底
            if ar_price is None:
                ar_price = float(df_after['High'].max())
                ar_date = df_after['High'].idxmax()
                detection_layer = '15d_extreme_fallback'

            rebound_pct = (ar_price - sc_benchmark) / sc_benchmark if sc_benchmark > 0 else 0
            return {
                'detected': True, 'type': 'automatic_rally', 'date': ar_date, 'price': ar_price,
                'rebound_pct': round(rebound_pct, 4), 'sc_benchmark': round(sc_benchmark, 2),
                'detection_layer': detection_layer
            }
        else:
            # buying_climax
            ar_price = None
            ar_date = None
            detection_layer = None

            # 层级 1：Swing 摆动过滤（优先）
            if len(df_after) >= 7:
                for i in range(2, len(df_after) - 2):
                    l = df_after['Low'].iloc[i]
                    if (l <= df_after['Low'].iloc[i-1] and l <= df_after['Low'].iloc[i-2] and
                        l <= df_after['Low'].iloc[i+1] and l <= df_after['Low'].iloc[i+2]):
                        ar_price = float(l)
                        ar_date = df_after.index[i]
                        detection_layer = 'swing_low'
                        break

            # 层级 2：立即回落检测（1-3 天）
            if ar_price is None:
                df_3 = df_after.head(3)
                if len(df_3) > 0:
                    min_low_idx = df_3['Low'].idxmin()
                    min_low_val = float(df_3['Low'].min())
                    if (sc_benchmark - min_low_val) / sc_benchmark >= ar_min_pct:
                        ar_price = min_low_val
                        ar_date = min_low_idx
                        detection_layer = 'immediate_reaction'

            # 层级 3：5日扩展检测（1-5 天）
            if ar_price is None:
                df_5 = df_after.head(5)
                if len(df_5) > 0:
                    min_low_idx = df_5['Low'].idxmin()
                    min_low_val = float(df_5['Low'].min())
                    if (sc_benchmark - min_low_val) / sc_benchmark >= ar_min_pct:
                        ar_price = min_low_val
                        ar_date = min_low_idx
                        detection_layer = '5d_extended'

            # 层级 4：15 天极值兜底
            if ar_price is None:
                ar_price = float(df_after['Low'].min())
                ar_date = df_after['Low'].idxmin()
                detection_layer = '15d_extreme_fallback'

            decline_pct = (ar_price - sc_benchmark) / sc_benchmark if sc_benchmark > 0 else 0
            bc_high = climax_res.get('price', 0)
            nominal_decline = (ar_price - bc_high) / bc_high if bc_high > 0 else 0
            return {
                'detected': True, 'type': 'automatic_reaction', 'date': ar_date, 'price': ar_price,
                'decline_pct': round(decline_pct, 4), 'sc_benchmark': round(sc_benchmark, 2),
                'climax_high': round(bc_high, 2), 'nominal_decline_pct': round(nominal_decline, 4),
                'detection_layer': detection_layer
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

        #  缺陷5修复：ST价格容差改为固定5%（不再复用JOC参数）并加入下影线支撑验证
        ST_PRICE_BAND = 0.05  # ST容差固定5%：Weis强调的是缩量而非绝对价格接近

        # 收集所有符合条件的ST (支持多次二次测试)
        all_tests = []

        for i in range(len(df_after)):
            row = df_after.iloc[i]
            if is_sc:
                price_test = row['Low'] <= climax_price * (1 + ST_PRICE_BAND)
            else:
                price_test = row['High'] >= climax_price * (1 - ST_PRICE_BAND)

            vol_test = row['Volume'] < climax_vol * self.thresholds.VOLUME_CONFIRMATION['weak']

            #  缺陷5修复：验证K线有下影线支撑（收盘位置 > 最低点1/3），或者量能极度萎缩
            candle_range = max(row['High'] - row['Low'], 1e-9)
            close_pct = (row['Close'] - row['Low']) / candle_range
            vol_ratio = row['Volume'] / climax_vol if climax_vol > 0 else 1.0
            
            has_lower_shadow_support = (close_pct > 0.33 or vol_ratio < 0.4) if is_sc else (close_pct < 0.67 or vol_ratio < 0.4)

            if price_test and vol_test:
                all_tests.append({
                    'date': df_after.index[i],
                    'price': float(row['Low'] if is_sc else row['High']),
                    'volume': float(row['Volume']),
                    'vol_ratio': round(vol_ratio, 3),
                    'test_number': len(all_tests) + 1,
                    'has_shadow_support': bool(has_lower_shadow_support),
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
    def detect_spring(self, lookback: int = None, trading_range: dict = None) -> Dict:
        lookback = lookback or self.config.spring_lookback
        #  缺陷3修复：传入TR时绕过缓存直接调用，防止旧缓存污染TR感知的支撑位计算
        if trading_range:
            return self._detect_spring_impl(lookback, trading_range=trading_range)
        cache_key = f"spring_{lookback}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_spring_impl, lookback
        )

    def _detect_spring_impl(self, lookback: int, trading_range: dict = None) -> Dict:
        if self.data is None or len(self.data) < 30:
            return {'detected': False, 'reason': 'insufficient_data'}
        if PhaseAdapter.is_distribution(self._current_phase):
            return {'detected': False, 'reason': 'distribution_phase_no_spring'}
        #  缺陷3修复：在明确下跌趋势中（Markdown）禁止误检Spring
        if 'Markdown' in str(self._current_phase):
            return {'detected': False, 'reason': 'markdown_phase_no_spring_without_confirmed_tr'}

        df = self.data.tail(lookback).copy()
        #  缺陷3修复：支撑位优先使用TR下沿
        support = self._calculate_support_level_spring(df, trading_range_low=trading_range.get('low') if trading_range else None)
        if support is None:
            return {'detected': False, 'reason': 'no_trading_range'}
        range_pct = (df['High'].max() - df['Low'].min()) / max(df['Low'].min(), 1e-9)
        if range_pct >= self.config.spring_range_threshold:
            return {'detected': False, 'reason': 'range_too_wide'}

        search_window = min(30, len(df))
        recent = df.tail(search_window).reset_index(drop=True)
        if len(recent) < 4:
            return {'detected': False, 'reason': 'insufficient_search_data'}

        original_index = df.tail(search_window).index
        springs = []
        if USE_VECTORIZED:
            try:
                springs = self._detect_spring_vectorized(recent, support, original_index)
            except Exception as e:
                logger.warning(f"Vectorized Spring detection failed: {e}. Falling back to iterative.")
                springs = self._detect_spring_iterative(recent, support, original_index)
        else:
            springs = self._detect_spring_iterative(recent, support, original_index)

        if springs:
            for s in springs:
                s['st_confirmed'] = self._verify_spring_st(s)
            fresh_springs = [s for s in springs if not self._is_signal_stale(s['date'], 'spring')]
            if fresh_springs:
                return {
                    'detected': True, 'signals': springs, 'fresh_signals': fresh_springs,
                    'latest_spring': fresh_springs[-1], 'method': 'enhanced_spring_detection_with_decay',
                    'signal_age_days': self._get_signal_age_days(fresh_springs[-1]['date'])
                }
            return {'detected': False, 'reason': 'all_spring_signals_stale'}
        return {'detected': False, 'reason': 'no_spring_found'}

    def _calculate_support_level_spring(self, df: pd.DataFrame, trading_range_low: float = None) -> Optional[float]:
        #  缺陷3修复：优先使用确认的TR下沿作为Spring支撑位
        if trading_range_low is not None and trading_range_low > 0:
            return round(float(trading_range_low), 2)
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

    def _calculate_spring_follow_score(self, nxt: pd.Series, d2: pd.Series) -> int:
        score = 0
        if nxt['Close'] > nxt['Open']:
            score += 3
        if nxt['Close'] > (nxt['High'] + nxt['Low']) / 2:
            score += 2
        if d2 is not None and d2['Close'] > nxt['Close']:
            score += 2
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

    def _detect_spring_vectorized(self, recent: pd.DataFrame, support: float, original_index: Optional[pd.Index] = None) -> List[Dict]:
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
        #  孟洪涛阈值：使用 MENG_SPRING_RECOVERY_CLOSE_POS 替代硬编码 0.7
        recovery_close_threshold = self.thresholds.MENG_SPRING_RECOVERY_CLOSE_POS
        high_close = close_positions >= recovery_close_threshold
        spring_candidates = valid_breakdown & recovery_mask & bullish_recovery & valid_volume & high_close
        candidate_indices = np.where(spring_candidates)[0]
        springs = []
        for i in candidate_indices:
            cur_idx, nxt_idx, d2_idx = i, i + 1, i + 2
            if d2_idx >= n:
                continue
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
            
            # 解决极端缩量的“量比失真”
            if 'turn' in recent.columns:
                if recent['turn'].mean() < 0.5:
                    breakdown_vol_ratio = min(breakdown_vol_ratio, 1.5)  # 惩罚性阻尼限制
                    
            penetration_depth = breakdown_pcts[i]
            needs_secondary_test = False
            is_valid = True
            
            if breakdown_vol_ratio > 1.5 and penetration_depth > 3.0:
                spring_type = 'type_1_dangerous'      # 放量深跌，危险，不能买
                is_valid = True
                needs_secondary_test = True
            elif breakdown_vol_ratio < 0.8 and penetration_depth < 1.5:
                spring_type = 'type_3_safe'           # 缩量浅跌，安全，可立即买
                needs_secondary_test = False
            else:
                spring_type = 'type_2_neutral'        # 中性，需等待 ST 确认
                needs_secondary_test = True

            if is_valid:
                springs.append({
                    'date': original_index[nxt_idx] if original_index is not None else recent.index[nxt_idx],
                    'breakdown_date': original_index[cur_idx] if original_index is not None else recent.index[cur_idx],
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
                    'breakdown_volume': float(volumes[cur_idx]),
                    'spring_type': spring_type,
                    'needs_secondary_test': needs_secondary_test,
                    'penetration_depth': round(float(penetration_depth), 2),
                    'confidence': 0.8 if spring_type == 'type_3_safe' else 0.5
                })
        return springs

    def _detect_spring_iterative(self, recent: pd.DataFrame, support: float, original_index: Optional[pd.Index] = None) -> List[Dict]:
        springs = []
        breakdown_mask = recent['Low'] < support
        candidate_indices = recent.index[breakdown_mask]
        for idx in candidate_indices:
            i = recent.index.get_loc(idx)
            if i + 2 >= len(recent):
                continue
            cur, nxt, d2 = recent.iloc[i], recent.iloc[i + 1], recent.iloc[i + 2]
            breakdown_pct = (support - cur['Low']) / support * 100
            if breakdown_pct > 5 or nxt['Close'] <= support or nxt['Close'] <= cur['Close']:
                continue
            recovery_vol_r = nxt['Volume'] / cur['Volume'] if cur['Volume'] > 0 else 1
            if recovery_vol_r <= 1.0:
                continue
            nxt_range = nxt['High'] - nxt['Low']
            nxt_close_pos = (nxt['Close'] - nxt['Low']) / nxt_range if nxt_range > 0 else 0.5
            #  孟洪涛阈值：使用 MENG_SPRING_RECOVERY_CLOSE_POS 替代硬编码 0.7
            if nxt_close_pos < self.thresholds.MENG_SPRING_RECOVERY_CLOSE_POS:
                continue
            follow_score = self._calculate_spring_follow_score(nxt, d2)
            recovery_pct = (nxt['Close'] - support) / support * 100 if support > 0 else 0
            actual_recovery_days = self._count_recovery_days(recent, i, support)
            total_score = min(recovery_vol_r * 15, 30) + min(nxt_close_pos * 25, 20) + min(follow_score * 3, 30) + min(recovery_pct, 10) + 10
            
            # Spring 量能分类与 ST 强制绑定 (符合 David Weis 原著)
            mean_vol = recent['Volume'].mean()
            breakdown_vol_ratio = float(cur['Volume'] / mean_vol) if mean_vol > 0 else 1.0
            
            # 解决极端缩量的“量比失真”
            if 'turn' in recent.columns:
                if recent['turn'].mean() < 0.5:
                    breakdown_vol_ratio = min(breakdown_vol_ratio, 1.5)  # 惩罚性阻尼限制
                    
            penetration_depth = breakdown_pct
            needs_secondary_test = False
            is_valid = True
            
            if breakdown_vol_ratio > 1.5 and penetration_depth > 3.0:
                spring_type = 'type_1_dangerous'      # 放量深跌，危险，不能买
                is_valid = True
                needs_secondary_test = True
            elif breakdown_vol_ratio < 0.8 and penetration_depth < 1.5:
                spring_type = 'type_3_safe'           # 缩量浅跌，安全，可立即买
                needs_secondary_test = False
            else:
                spring_type = 'type_2_neutral'        # 中性，需等待 ST 确认
                needs_secondary_test = True

            if is_valid:
                springs.append({
                    'date': original_index[nxt_idx] if original_index is not None else nxt.name,
                    'breakdown_date': original_index[cur_idx] if original_index is not None else cur.name,
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
                    'breakdown_volume': float(cur['Volume']),
                    'spring_type': spring_type,
                    'needs_secondary_test': needs_secondary_test,
                    'penetration_depth': round(float(penetration_depth), 2),
                    'confidence': 0.8 if spring_type == 'type_3_safe' else 0.5
                })
        return springs

    def _verify_spring_st(self, spring_dict: Dict) -> bool:
        """
        校验 Spring 的二次测试 (ST)
        """
        if spring_dict.get('spring_type') == 'type_3_safe':
            return True
            
        recovery_date = spring_dict['date']
        spring_low = spring_dict['breakdown_price']['value']
        breakdown_vol = spring_dict.get('breakdown_volume')
        
        if not breakdown_vol:
            return False
            
        # 获取收回日后的最多 20 个交易日
        try:
            post_df = self.data[pd.to_datetime(self.data.index) > pd.to_datetime(recovery_date)].head(20)
        except Exception:
            post_df = self.data[self.data.index > recovery_date].head(20)
            
        if post_df.empty:
            return False
            
        st_confirmed = False
        for idx, row in post_df.iterrows():
            # 若跌破 Spring 低点，则标记失败并终止
            if row['Low'] <= spring_low:
                return False
            
            # 校验测试日成交量是否显著萎缩 (st_vol < breakdown_vol * 0.7)
            if row['Volume'] < breakdown_vol * 0.7:
                current_min_low = post_df.loc[:idx, 'Low'].min()
                if row['Low'] <= spring_low * 1.08 or row['Low'] == current_min_low:
                    st_confirmed = True
                    
        return st_confirmed

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
        M = self.config.breakout_search_window
        if len(df) <= M:
            return None
        range_df = df.iloc[:-M]
        high_max, low_min = range_df['High'].max(), range_df['Low'].min()
        if (high_max - low_min) / low_min < self.config.spring_range_threshold:
            return high_max
        return None

    def _find_and_verify_upthrusts(self, df: pd.DataFrame, resistance_level: float):
        M = self.config.breakout_search_window
        breakout_df = df.tail(M)
        upthrusts, breakout_indices = [], breakout_df.index[breakout_df['High'] > resistance_level]
        rejection_indices = df.index[df['Close'] < resistance_level]

        mean_vol = df['Volume'].mean()

        #  修复 P1-2: 检测市场环境，用于动态调整 UT 分类
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

                    #  修复 P1-2: 使用市场环境加权的 UT 分类
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
                        'market_environment': market_env,  #  新增：记录市场环境
                        'classification_note': ut_note  #  新增：分类说明
                    })
        return upthrusts

    # ── UTAD 检测 (Upthrust After Distribution) ──────────────
    def detect_utad(self, lookback: int = 120) -> Dict:
        """
        检测 UTAD（Upthrust After Distribution — 派发后的上冲回落）

        孟洪涛《新威科夫操盘法》定义：
        UTAD 是派发 Phase E 的标志性事件，与吸筹区的 Spring 相对应。
        特征：
        1. 价格在长期上涨后创出新高
        2. 突破量巨大（量比 > 2.0），但收盘疲软（长上影线）
        3. 突破后 1-5 天内价格迅速回落到派发区间内
        4. 后续无法再创新高（需求枯竭）
        """
        if self.data is None or len(self.data) < 60:
            return {'detected': False, 'reason': 'insufficient_data'}

        is_dist = PhaseAdapter.is_distribution(self._current_phase) if self._current_phase else False
        is_markdown = 'Markdown' in str(self._current_phase) if self._current_phase else False

        df = self.data.tail(lookback).copy()
        if len(df) < 60:
            return {'detected': False, 'reason': 'insufficient_data_for_utad'}

        recent = df.tail(30)
        current_price = recent['Close'].iloc[-1]
        lookback_high = df['High'].max()
        lookback_high_idx = df['High'].idxmax()

        recent_high = recent['High'].max()
        recent_high_idx = recent['High'].idxmax()
        
        # 高波动资产特化的 UTAD 容差机制
        market_type = getattr(self.thresholds, 'market_type', 'EQUITY')
        
        atr_pct = 0.05
        try:
            atr_pct = ((df['High'] - df['Low']).tail(14).mean()) / current_price
        except Exception:
            pass

        upper_limit = 1.03 + atr_pct  # 引入 ATR 联动
        if market_type == 'CRYPTO':
            upper_limit = max(1.10, 1.0 + atr_pct) # CRYPTO 允许放宽至刺穿 1.10

        is_near_high = (lookback_high * 0.98 <= recent_high <= lookback_high * upper_limit)

        if not is_near_high:
            return {'detected': False, 'reason': 'price_not_near_high_or_breakout_too_deep'}

        breakout_row = df.loc[recent_high_idx]
        vol_ma = df['Volume'].tail(60).mean()
        breakout_vol_ratio = breakout_row['Volume'] / vol_ma if vol_ma > 0 else 1.0

        # UTAD 核心量价特征：突破时成交量为近期(20日)最高 (P1 #3)
        vol_20_max = df['Volume'].tail(20).max()
        is_highest_vol = breakout_row['Volume'] >= vol_20_max
        
        range_val = max(breakout_row['High'] - breakout_row['Low'], 1e-9)
        upper_shadow = breakout_row['High'] - max(breakout_row['Open'], breakout_row['Close'])
        upper_shadow_ratio = upper_shadow / range_val

        has_climax_volume = breakout_vol_ratio > 2.0 or is_highest_vol
        has_long_upper_shadow = upper_shadow_ratio > 0.4

        if not (has_climax_volume and has_long_upper_shadow):
            return {'detected': False, 'reason': 'no_climax_volume_or_upper_shadow'}

        # UTAD 必须发生在 Phase C/D (P1 #3)
        current_phase = self._current_phase
        is_dist_context = PhaseAdapter.is_distribution(current_phase) if current_phase else True
            
        if not is_dist_context:
            return {'detected': False, 'reason': 'not_in_distribution_phase'}

        after_breakout = df[df.index > recent_high_idx].head(3) # 缩短到 3 天确认 (P1 #3)
        if len(after_breakout) == 0:
            return {'detected': False, 'reason': 'insufficient_data_after_breakout'}

        resistance_level = lookback_high
        fallback_detected = False
        confirmation_days = 0
        for i in range(len(after_breakout)):
            if after_breakout.iloc[i]['Close'] < resistance_level * 0.98:
                fallback_detected = True
                confirmation_days = i + 1
                break

        if not fallback_detected:
            return {'detected': False, 'reason': 'no_fallback_after_breakout'}

        distribution_detected = is_dist or is_markdown

        confidence = 0.5
        if has_climax_volume:
            confidence += 0.2
        if has_long_upper_shadow:
            confidence += 0.15
        if confirmation_days <= 3:
            confidence += 0.15
        if distribution_detected:
            confidence += 0.15
        if current_price < resistance_level * 0.95:
            confidence += 0.1
        confidence = min(confidence, 1.0)

        if confirmation_days <= 2 and breakout_vol_ratio > 2.5:
            utad_type = 'classic_utad'
        elif confirmation_days <= 5:
            utad_type = 'failed_breakout'
        else:
            utad_type = 'double_top'

        utad_res = {
            'detected': True,
            'utad_type': utad_type,
            'date': after_breakout.index[min(confirmation_days, len(after_breakout) - 1)],
            'breakout_date': recent_high_idx,
            'breakout_price': float(breakout_row['High']),
            'breakout_volume': float(breakout_row['Volume']),
            'resistance_level': float(resistance_level),
            'volume_ratio': round(float(breakout_vol_ratio), 2),
            'upper_shadow_ratio': round(float(upper_shadow_ratio), 2),
            'penetration_depth': round(float((breakout_row['High'] - resistance_level) / max(resistance_level, 1e-9) * 100), 2),
            'confirmation_days': confirmation_days,
            'distribution_detected': distribution_detected,
            'confidence': round(confidence, 2),
        }

        # 校验 UTAD ST 二次测试并存入 st_confirmed
        st_confirmed = self._verify_utad_st(utad_res)
        utad_res['st_confirmed'] = st_confirmed

        utad_res['description'] = (
            f"UTAD（派发后的上冲回落）：价格突破派发区间上沿{resistance_level:.2f}元后，"
            f"在{confirmation_days}天内回落至区间内。量比{breakout_vol_ratio:.1f}倍，"
            f"上影线占比{upper_shadow_ratio:.0%}。"
            f"{'有前置派发结构 ✓' if distribution_detected else '无前置派发结构 ⚠️'}。"
            f"{'二次测试缩量确认成功 ✓' if st_confirmed else '二次测试放量或价格未跌回证伪 ⚠️'}"
        )

        return utad_res

    def _verify_utad_st(self, utad_dict: Dict) -> bool:
        """
        校验 UTAD 的二次测试 (ST)
        """
        utad_date = utad_dict['date']
        utad_high = utad_dict['breakout_price']
        breakout_vol = utad_dict.get('breakout_volume', 0)
        
        # 获取 BC climax 体积
        bc_volume = 0
        try:
            climax_res = self.detect_climax()
            if climax_res.get('detected') and climax_res.get('type') == 'buying_climax':
                bc_volume = climax_res.get('volume', 0)
        except Exception:
            pass

        # 1. 从 UTAD 返回交易区间（TR）后的下一个交易日开始，扫描随后的 10 个交易日
        try:
            post_df = self.data[pd.to_datetime(self.data.index) > pd.to_datetime(utad_date)].head(10)
        except Exception:
            post_df = self.data[self.data.index > utad_date].head(10)

        if post_df.empty:
            return False

        # 若 UTAD 价格在 10 个交易日内始终高高挂起未能跌回 TR 下方（Close 始终处于 UTAD 高点的 95% 以上），同样判定为失败（st_confirmed = False）。
        if (post_df['Close'] >= utad_high * 0.95).all():
            return False

        # 2. 校验测试日高点和成交量
        # "若 10 天内反抽高点突破了 UTAD 高点，或在 10 天内反抽成交量比值（st_vol / breakout_volume >= 0.7 或相对于 BC climax 体积比值 >= 0.5），则判定 ST 确认失败（st_confirmed = False）"
        # Otherwise, st_confirmed = True.
        st_confirmed = True
        for idx, row in post_df.iterrows():
            if row['High'] > utad_high:
                st_confirmed = False
                break
            
            # 反抽成交量比值判定
            try:
                prev_idx = self.data.index.get_loc(idx) - 1
                prev_close = self.data['Close'].iloc[prev_idx] if prev_idx >= 0 else row['Open']
            except Exception:
                prev_close = row['Open']
            
            is_rally = (row['Close'] >= row['Open']) or (row['Close'] >= prev_close) or (row['High'] >= utad_high * 0.9)
            if is_rally:
                st_vol = row['Volume']
                vol_ratio_breakout = st_vol / breakout_vol if breakout_vol > 0 else 0
                vol_ratio_bc = st_vol / bc_volume if bc_volume > 0 else 0
                if vol_ratio_breakout >= 0.7 or (bc_volume > 0 and vol_ratio_bc >= 0.5):
                    st_confirmed = False
                    break
                    
        return st_confirmed

    def detect_stopping_volume(self) -> Dict:
        """
        检测停止成交量 (Stopping Volume)

        孟洪涛理论：在吸筹末期，出现异常放量的长下影线K线
        - 量能显著放大（>平均量的1.5倍）
        - 实体较小（<波段的30%）
        - 下影线较长（>波段的30%）
        - 收盘位置较高（>波段中点）

        Returns:
            {
                'detected': bool,
                'date': timestamp,
                'volume_ratio': float,
                'body_ratio': float,
                'shadow_ratio': float,
                'close_position': float
            }
        """
        if self.data is None or len(self.data) < 20:
            return {'detected': False, 'reason': 'insufficient_data'}

        df = self.data.tail(40).copy()
        vol_ma = df['Volume'].rolling(20).mean()
        fallback_vol_ma = df['Volume'].mean()

        stopping_signals = []

        for idx in df.index:
            row = df.loc[idx]
            current_vol_ma = vol_ma.loc[idx] if pd.notna(vol_ma.loc[idx]) else fallback_vol_ma
            vol_ratio = row['Volume'] / current_vol_ma if current_vol_ma > 0 else 1.0

            # 波段计算
            rng = row['High'] - row['Low']
            if rng <= 0:
                continue

            body = abs(row['Close'] - row['Open'])
            lower_shadow = min(row['Close'], row['Open']) - row['Low']
            upper_shadow = row['High'] - max(row['Close'], row['Open'])

            body_ratio = body / rng
            lower_shadow_ratio = lower_shadow / rng
            close_position = (row['Close'] - row['Low']) / rng

            # 孟洪涛阈值判断
            has_stopping_volume = vol_ratio >= self.thresholds.MENG_STOPPING_VOL_RATIO
            has_small_body = body_ratio <= self.thresholds.MENG_STOPPING_BODY_RATIO
            has_lower_shadow = lower_shadow_ratio >= self.thresholds.MENG_STOPPING_SHADOW_RATIO
            high_close = close_position >= self.thresholds.MENG_VSA_CLOSE_POS

            if has_stopping_volume and has_small_body and (has_lower_shadow or high_close):
                stopping_signals.append({
                    'date': idx,
                    'volume_ratio': round(vol_ratio, 2),
                    'body_ratio': round(body_ratio, 3),
                    'shadow_ratio': round(lower_shadow_ratio, 3),
                    'close_position': round(close_position, 3)
                })

        if not stopping_signals:
            return {'detected': False, 'signals': []}

        # 返回最新的信号
        latest = stopping_signals[-1]
        return {
            'detected': True,
            **latest,
            'all_signals': stopping_signals,
            'signal_count': len(stopping_signals)
        }


def _unify_quality_score(spring_or_ut_result: dict) -> int:
    """
    统一 Spring/UT 质量评分为 1-100 分
    
   威科夫理论质量标准：
    - type_3_safe: 85-100分 (可立即行动)
    - type_2_neutral: 50-84分 (需等待确认)
    - type_1_dangerous: 1-49分 (避免行动)
    """
    if not spring_or_ut_result.get('detected'):
        return 0
    
    signal_type = spring_or_ut_result.get('spring_type') or spring_or_ut_result.get('upthrust_type', '')
    
    if signal_type == 'type_3_safe':
        base_score = 85
    elif signal_type == 'type_2_neutral':
        base_score = 50
    elif signal_type == 'type_1_dangerous':
        base_score = 20
    else:
        base_score = 50
    
    # 根据置信度微调
    confidence = spring_or_ut_result.get('confidence', 0.5)
    return min(int(base_score + confidence * 15), 100)
