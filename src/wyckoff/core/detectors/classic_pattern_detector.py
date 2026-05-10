import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple, List, Any
from .base_detector import BaseDetector, USE_VECTORIZED
from ...config.settings import WyckoffConfig, WyckoffThresholds
from ..utils import TypeConverter, PhaseAdapter
from ..indicator_cache import IndicatorCache

logger = logging.getLogger(__name__)

class ClassicPatternDetector(BaseDetector):
    """负责检测经典威科夫形态 (Climax, Spring, Upthrust, JOC, FTI, VSA, Divergence)"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, analysis_cache, bayesian_model=None, indicator_cache=None):
        super().__init__()
        self.data = data
        self.config = config
        self.thresholds = thresholds
        self._analysis_cache = analysis_cache
        self.bayesian_model = bayesian_model

        # 使用注入的缓存或初始化新缓存
        self._indicator_cache = indicator_cache or IndicatorCache(data)
        self._cache_warmed = False

    def _warm_up_indicator_cache(self):
        """
        预热指标缓存（预计算常用指标）

        根据 profiling 数据，这些指标在检测中最常用：
        - Volume_MA20：所有成交量检测都需要
        - Low_Min_20：Spring 检测需要
        - High_Max_20：Upthrust 检测需要
        - ATR：Spring 动态调整需要

        预热可减少 30-40% 的重复计算开销
        """
        if self._cache_warmed:
            return

        common_indicators = {
            'Volume_MA20': {'window': 20},
            'Low_Min_20': {'window': 20},
            'High_Max_20': {'window': 20},
            'ATR': {'period': 14}
        }

        self._indicator_cache.warm_up(common_indicators)
        self._cache_warmed = True

    def _get_volume_threshold(self, signal_type: str, default: float) -> float:
        """获取自适应或静态成交量阈值"""
        if self.bayesian_model:
            return self.bayesian_model.get_volume_threshold(signal_type, default=default)
        return default

    def _get_tech_indicators(self, window: int = 20) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        统一获取技术指标（Volume MA, Low Min, High Max）

        使用 IndicatorCache 避免重复计算，性能提升约 30-40%
        """
        vol_ma = self._indicator_cache.get(f'Volume_MA{window}')
        low_min = self._indicator_cache.get(f'Low_Min{window}')
        high_max = self._indicator_cache.get(f'High_Max{window}')

        return vol_ma, low_min, high_max

    # --- Climax, AR, ST ---
    def detect_climax(self) -> Dict:
        """检测高潮行为 (SC/BC)"""
        # 预热指标缓存（首次调用时）
        self._warm_up_indicator_cache()

        return self._analysis_cache.get_or_compute(
            "climax", self._detect_climax_impl
        )

    def _detect_climax_impl(self) -> Dict:
        if self.data is None or len(self.data) < 20:
            return {'detected': False}

        df = self.data.tail(40).copy()
        # 使用统一的技术指标获取方法
        vol_ma, low_min, high_max = self._get_tech_indicators(20)
        
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
                        f"二次测试 确认{'✅' if confirmed else '⚠️'} — "
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
        if PhaseAdapter.is_distribution(self._current_phase):
            return {'detected': False, 'reason': 'distribution_phase_no_spring'}

        df = self.data.tail(lookback).copy()

        support = self._calculate_support_level_spring(df)
        if support is None:
            return {'detected': False, 'reason': 'no_trading_range'}

        # 验证盘整区间幅度
        range_pct = (df['High'].max() - df['Low'].min()) / max(df['Low'].min(), 1e-9)
        if range_pct >= self.config.spring_range_threshold:
            return {'detected': False, 'reason': 'range_too_wide'}

        # 在最近30根K线中搜索Spring
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
            # 🔧 v1.2新增：应用时间衰减，过滤过期的Spring信号
            fresh_springs = [
                s for s in springs
                if not self._is_signal_stale(s['date'], 'spring')
            ]

            if fresh_springs:
                return {
                    'detected': True,
                    'signals': springs,  # 保留所有信号供参考
                    'fresh_signals': fresh_springs,  # 新增：仅包含有效信号
                    'latest_spring': fresh_springs[-1],  # 修改：使用最新的有效信号
                    'method': 'enhanced_spring_detection_with_decay',
                    'signal_age_days': self._get_signal_age_days(fresh_springs[-1]['date'])  # 新增：信号年龄
                }
            else:
                return {'detected': False, 'reason': 'all_spring_signals_stale'}
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
            cluster_avg = sum(low_cluster) / len(low_cluster) if len(low_cluster) > 0 else df['Low'].min()
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

    def _detect_spring_vectorized(self, recent: pd.DataFrame, support: float) -> List[Dict]:
        """
        向量化版本的Spring检测

        Args:
            recent: 搜索窗口内的数据
            support: 支撑位

        Returns:
            Spring信号列表
        """
        n = len(recent)

        # 转换为NumPy数组
        lows = recent['Low'].values
        closes = recent['Close'].values
        highs = recent['High'].values
        opens = recent['Open'].values
        volumes = recent['Volume'].values

        # 构建时间平移数组
        # T日: 跌破日
        # T+1日: 收回日
        # T+2日: 跟随确认日

        # 预筛选：跌破支撑的bar (修正逻辑：移除误导性的 0.97 限制，允许 1-3% 的标准 Spring)
        breakdown_mask = lows[:-2] < support

        # 条件1：跌破幅度检查（1-5%）- 使用 np.where 安全除法
        safe_support = np.where(support > 1e-9, support, 1.0)
        breakdown_pcts = (safe_support - lows[:-2]) / safe_support * 100
        valid_breakdown = breakdown_mask & (breakdown_pcts >= 1) & (breakdown_pcts <= 5)

        # 条件2：次日收盘回到支撑位之上
        recovery_mask = closes[1:-1] > support

        # 条件3：次日收盘高于跌破日收盘（阳线确认）
        bullish_recovery = closes[1:-1] > closes[:-2]

        # 条件4：收回日成交量 > 跌破日成交量 - 使用 np.where 安全除法
        safe_volumes = np.where(volumes[:-2] > 0, volumes[:-2], 1.0)
        vol_ratios = volumes[1:-1] / safe_volumes
        valid_volume = vol_ratios > 1.0

        # 条件5：收回日收盘在日内高位70%以上
        daily_ranges = highs[1:-1] - lows[1:-1]
        safe_ranges = np.where(daily_ranges == 0, 1.0, daily_ranges)
        close_positions = (closes[1:-1] - lows[1:-1]) / safe_ranges
        high_close = close_positions >= 0.7

        # 组合所有条件（除了跟随确认，需要单独处理）
        spring_candidates = valid_breakdown & recovery_mask & bullish_recovery & valid_volume & high_close

        # 获取候选索引
        candidate_indices = np.where(spring_candidates)[0]

        springs = []
        for i in candidate_indices:
            # T日: i, T+1日: i+1, T+2日: i+2
            cur_idx = i
            nxt_idx = i + 1
            d2_idx = i + 2

            if d2_idx >= n:
                continue

            # 条件6：跟随确认评分
            nxt = {
                'Close': closes[nxt_idx],
                'Open': opens[nxt_idx],
                'High': highs[nxt_idx],
                'Low': lows[nxt_idx]
            }
            d2 = {
                'Close': closes[d2_idx],
                'High': highs[d2_idx],
                'Low': lows[d2_idx]
            }
            follow_score = self._calculate_spring_follow_score(
                pd.Series(nxt),
                pd.Series(d2)
            )

            # 计算评分
            breakdown_pct = breakdown_pcts[i]
            recovery_vol_r = float(vol_ratios[i])
            nxt_close_pos = float(close_positions[i])
            recovery_pct = (closes[nxt_idx] - support) / support * 100 if support > 0 else 0

            total_score = (
                min(recovery_vol_r * 15, 30) +
                min(nxt_close_pos * 25, 20) +
                min(follow_score * 3, 30) +
                min(recovery_pct, 10) +
                10
            )
            total_score = min(total_score, 100)

            spring = {
                'date': recent.index[nxt_idx],
                'breakdown_date': recent.index[cur_idx],
                'breakdown_price': round(float(lows[cur_idx]), 2),
                'support_level': round(support, 2),
                'recovery_price': round(float(closes[nxt_idx]), 2),
                'recovery_days': 1,
                'volume_ratio': round(recovery_vol_r, 2),
                'close_position': round(nxt_close_pos * 100, 1),
                'follow_up_score': follow_score,
                'total_score': total_score,
                'strength': 'strong' if total_score > 70 else 'normal' if total_score > 50 else 'weak',
            }
            springs.append(spring)

        return springs

    def _detect_spring_iterative(self, recent: pd.DataFrame, support: float) -> List[Dict]:
        """
        迭代版本的Spring检测

        Args:
            recent: 搜索窗口内的数据
            support: 支撑位

        Returns:
            Spring信号列表
        """
        springs = []

        # 预筛选：只检查跌破支撑的 bar（修正逻辑：移除误导性的 0.97 限制，允许 1-3% 的标准 Spring）
        breakdown_mask = recent['Low'] < support
        candidate_indices = recent.index[breakdown_mask]

        for idx in candidate_indices:
            i = recent.index.get_loc(idx)
            if i + 2 >= len(recent):
                continue
            cur = recent.iloc[i]
            nxt = recent.iloc[i + 1]
            d2 = recent.iloc[i + 2]

            # 条件1：跌破幅度上限（书中1-3%，放宽到5%防漏检）
            breakdown_pct = (support - cur['Low']) / support * 100
            if breakdown_pct > 5:
                continue

            # 条件2：次日收盘回到支撑位之上
            if nxt['Close'] <= support:
                continue

            # 条件3：次日收盘高于跌破日收盘（阳线确认）
            if nxt['Close'] <= cur['Close']:
                continue

            # 条件4（书）：收回日成交量 > 跌破日成交量（需求吃掉供应）
            b_vol = cur['Volume']
            r_vol = nxt['Volume']
            recovery_vol_r = r_vol / b_vol if b_vol > 0 else 1
            if recovery_vol_r <= 1.0:
                continue

            # 条件5（书）：收回日收盘在日内高位 70% 以上
            nxt_range = nxt['High'] - nxt['Low']
            nxt_close_pos = (nxt['Close'] - nxt['Low']) / nxt_range if nxt_range > 0 else 0.5
            if nxt_close_pos < 0.7:
                continue

            # 条件6：跟随确认评分
            follow_score = self._calculate_spring_follow_score(nxt, d2)

            # 综合评分（100分制）— 按书中逻辑重新分配
            recovery_pct = (nxt['Close'] - support) / support * 100 if support > 0 else 0
            total_score = (
                min(recovery_vol_r * 15, 30) +   # 成交量(收回/跌破比): 0-30
                min(nxt_close_pos * 25, 20) +     # 收盘位置分: 0-20
                min(follow_score * 3, 30) +        # 跟随: 0-30
                min(recovery_pct, 10) +             # 收回幅度: 0-10
                10                                   # 基础分
            )
            total_score = min(total_score, 100)

            spring = {
                'date': nxt.name,
                'breakdown_date': cur.name,
                'breakdown_price': round(float(cur['Low']), 2),
                'support_level': round(support, 2),
                'recovery_price': round(float(nxt['Close']), 2),
                'recovery_days': 1,
                'volume_ratio': round(recovery_vol_r, 2),
                'close_position': round(nxt_close_pos * 100, 1),
                'follow_up_score': follow_score,
                'total_score': total_score,
                'strength': 'strong' if total_score > 70 else 'normal' if total_score > 50 else 'weak',
            }
            springs.append(spring)

        return springs

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

        if PhaseAdapter.is_distribution(phase):
            return {'valid': False, 'confidence': 'low', 'reason': '派发阶段的Spring往往是失败的陷阱'}

        if PhaseAdapter.is_markup(phase):
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
            (df['Volume'] >= vol_ma * self._get_volume_threshold('breakout', self.thresholds.JOC_VOLUME_RATIO))
        )

        if not breakout_mask.any():
            return {'detected': False, 'reason': 'no_joc_breakout_found'}

        # 🔧 v1.2新增：时间衰减应用，从最新的JOC信号开始检查
        joc_candidates = df[breakout_mask].sort_index(ascending=False)
        fresh_joc_found = False

        for joc_idx_temp in joc_candidates.index:
            # 检查信号是否过期
            if self._is_signal_stale(joc_idx_temp, 'joc'):
                continue  # 跳过过期信号

            joc_idx = joc_idx_temp
            joc_row = df.loc[joc_idx]
            fresh_joc_found = True
            break

        if not fresh_joc_found:
            return {'detected': False, 'reason': 'no_fresh_joc_signal_all_stale'}

        v_ma_val = vol_ma.loc[joc_idx]
        volume_ratio = joc_row['Volume'] / v_ma_val if v_ma_val > 0 else 0
        breakout_pct = (joc_row['Close'] - creek_level) / creek_level

        test_detected = False
        test_date = None
        test_vol_ratio = None
        test_depth_pct = 0.0
        test_count = 0
        df_after_joc = df[df.index > joc_idx].head(10)
        if len(df_after_joc) >= 1:
            if USE_VECTORIZED:
                try:
                    # 提前转换为 NumPy 数组，避免重复索引
                    lows = df_after_joc['Low'].values
                    closes = df_after_joc['Close'].values
                    vols = df_after_joc['Volume'].values
                    vol_mas = vol_ma.loc[df_after_joc.index].values

                    # 向量化计算回测条件
                    creek_lower = creek_level * (1 - self.thresholds.JOC_TEST_BAND)
                    creek_upper = creek_level * (1 + self.thresholds.JOC_TEST_BAND * 2)

                    near_creek = (lows >= creek_lower) & (lows <= creek_upper)
                    test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.JOC_TEST_VOL_RATIO)
                    vol_shrinking = vols < vol_mas * test_vol_threshold
                    above_creek = closes > creek_level

                    # 组合条件：接近小溪 + 缩量 + 收盘在小溪上方
                    test_hits = near_creek & vol_shrinking & above_creek
                    hit_indices = np.where(test_hits)[0]

                    if len(hit_indices) > 0:
                        test_detected = True
                        first_hit = hit_indices[0]
                        test_date = df_after_joc.index[first_hit]
                        test_vol_ratio = round(float(vols[first_hit] / vol_mas[first_hit]), 2)

                    test_count = int(np.sum(test_hits))

                    # 计算最大回测深度
                    depths = (joc_row['Close'] - lows) / joc_row['Close']
                    if len(depths) > 0:
                        test_depth_pct = max(0.0, float(np.max(depths)))

                except Exception as e:
                    logger.warning(f"Vectorized JOC test failed: {e}. Falling back to iterative.")
                    # 迭代版本
                    for idx_test in df_after_joc.index:
                        row_test = df_after_joc.loc[idx_test]
                        near_creek = creek_level * (1 - self.thresholds.JOC_TEST_BAND) <= row_test['Low'] <= creek_level * (1 + self.thresholds.JOC_TEST_BAND * 2)
                        test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.JOC_TEST_VOL_RATIO)
                        vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * test_vol_threshold
                        above_creek = row_test['Close'] > creek_level
                        if near_creek and vol_shrinking and above_creek:
                            if not test_detected:
                                test_detected = True
                                test_date = idx_test
                                test_vol_ratio = round(row_test['Volume'] / vol_ma.loc[idx_test], 2)
                            test_count += 1
                        # 计算回测深度
                        depth = (joc_row['Close'] - row_test['Low']) / joc_row['Close']
                        test_depth_pct = max(test_depth_pct, depth)
            else:
                for idx_test in df_after_joc.index:
                    row_test = df_after_joc.loc[idx_test]
                    near_creek = creek_level * (1 - self.thresholds.JOC_TEST_BAND) <= row_test['Low'] <= creek_level * (1 + self.thresholds.JOC_TEST_BAND * 2)
                    test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.JOC_TEST_VOL_RATIO)
                    vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * test_vol_threshold
                    above_creek = row_test['Close'] > creek_level
                    if near_creek and vol_shrinking and above_creek:
                        if not test_detected:
                            test_detected = True
                            test_date = idx_test
                            test_vol_ratio = round(row_test['Volume'] / vol_ma.loc[idx_test], 2)
                        test_count += 1
                    # 计算回测深度（最低点相对突破位的跌幅）
                    depth = (joc_row['Close'] - row_test['Low']) / joc_row['Close']
                    test_depth_pct = max(test_depth_pct, depth)

        # 使用强度分类系统
        strength_info = self._classify_joc_strength({
            'test_detected': test_detected,
            'test_depth_pct': test_depth_pct,
            'test_count': test_count,
            'volume_ratio': volume_ratio,
            'breakout_pct': breakout_pct
        })

        confidence = 0.50 + (0.2 if volume_ratio >= 2.0 else 0.1 if volume_ratio >= 1.5 else 0) + (0.1 if breakout_pct >= 0.03 else 0) + (0.2 if test_detected else 0) + strength_info['confidence_boost']
        return {
            'detected': True, 'date': joc_idx, 'creek_level': round(creek_level, 3), 'close_price': round(joc_row['Close'], 3),
            'breakout_pct': round(breakout_pct * 100, 2), 'volume_ratio': round(volume_ratio, 2),
            'test_detected': test_detected, 'test_date': test_date, 'test_vol_ratio': test_vol_ratio,
            'test_depth_pct': round(test_depth_pct * 100, 2), 'test_count': test_count,
            'strength': strength_info['strength'], 'strength_description': strength_info['description'],
            'trading_implication': strength_info['trading_implication'], 'confidence': round(min(confidence, 1.0), 2)
        }

    def _classify_joc_strength(self, joc_signal: dict) -> dict:
        """JOC强度分类系统

        理论依据：孟洪涛《新威科夫操盘法》
        - 强势JOC：直接拉升，不回测或回测很浅（<3%）
        - 弱势JOC：需要多次回测确认或深回测（≥3%）

        Args:
            joc_signal: JOC信号字典，包含test_detected, test_depth_pct, test_count等

        Returns:
            强度分类信息，包括strength级别、描述、交易建议、置信度加成
        """
        has_test = joc_signal.get('test_detected', False)
        test_depth = joc_signal.get('test_depth_pct', 0)
        test_count = joc_signal.get('test_count', 0)
        volume_ratio = joc_signal.get('volume_ratio', 0)

        # 判断JOC强度
        if not has_test:
            return {
                'strength': 'STRONG_JOC',
                'description': '强势JOC（直接拉升，无需回测）',
                'trading_implication': '激进追涨，止损设在JOC起点',
                'confidence_boost': 0.3
            }
        elif test_depth < 0.03 and test_count <= 2:
            return {
                'strength': 'STRONG_JOC_CONFIRMED',
                'description': f'强势JOC（浅回测{test_depth*100:.1f}%，{test_count}次确认）',
                'trading_implication': '稳健做多，回测介入',
                'confidence_boost': 0.2
            }
        else:
            return {
                'strength': 'WEAK_JOC',
                'description': f'弱势JOC（深回测{test_depth*100:.1f}%，{test_count}次试探）',
                'trading_implication': '谨慎观望，等待明确方向',
                'confidence_boost': -0.2
            }

    def detect_fti(self, lookback: int = 90) -> Dict:
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
            (df['Volume'] >= vol_ma * self._get_volume_threshold('breakout', self.thresholds.FTI_VOLUME_RATIO))
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
            if USE_VECTORIZED:
                try:
                    # 提前转换为 NumPy 数组
                    highs = df_after_fti['High'].values
                    closes = df_after_fti['Close'].values
                    vols = df_after_fti['Volume'].values
                    vol_mas = vol_ma.loc[df_after_fti.index].values

                    # 向量化计算回测条件
                    ice_lower = ice_level * (1 - self.thresholds.FTI_TEST_BAND * 1.5)
                    ice_upper = ice_level * (1 + self.thresholds.FTI_TEST_BAND)
                    ice_fail_threshold = ice_level * (1 + self.thresholds.FTI_TEST_BAND / 2)

                    near_ice = (highs >= ice_lower) & (highs <= ice_upper)
                    test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.FTI_TEST_VOL_RATIO)
                    vol_shrinking = vols < vol_mas * test_vol_threshold
                    failed_recovery = closes < ice_fail_threshold

                    # 组合条件：接近冰面 + 缩量 + 收盘在冰面下方
                    test_hits = near_ice & vol_shrinking & failed_recovery
                    hit_indices = np.where(test_hits)[0]

                    if len(hit_indices) > 0:
                        test_detected = True
                        first_hit = hit_indices[0]
                        test_date = df_after_fti.index[first_hit]
                        test_vol_ratio = round(float(vols[first_hit] / vol_mas[first_hit]), 2)

                except Exception as e:
                    logger.warning(f"Vectorized FTI test failed: {e}. Falling back to iterative.")
                    # 迭代版本
                    for idx_test in df_after_fti.index:
                        row_test = df_after_fti.loc[idx_test]
                        near_ice = ice_level * (1 - self.thresholds.FTI_TEST_BAND * 1.5) <= row_test['High'] <= ice_level * (1 + self.thresholds.FTI_TEST_BAND)
                        test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.FTI_TEST_VOL_RATIO)
                        vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * test_vol_threshold
                        failed_recovery = row_test['Close'] < ice_level * (1 + self.thresholds.FTI_TEST_BAND/2)
                        if near_ice and vol_shrinking and failed_recovery:
                            test_detected = True
                            test_date = idx_test
                            test_vol_ratio = round(row_test['Volume'] / vol_ma.loc[idx_test], 2)
                            break
            else:
                for idx_test in df_after_fti.index:
                    row_test = df_after_fti.loc[idx_test]
                    near_ice = ice_level * (1 - self.thresholds.FTI_TEST_BAND * 1.5) <= row_test['High'] <= ice_level * (1 + self.thresholds.FTI_TEST_BAND)
                    test_vol_threshold = self._get_volume_threshold('shrink', self.thresholds.FTI_TEST_VOL_RATIO)
                    vol_shrinking = row_test['Volume'] < vol_ma.loc[idx_test] * test_vol_threshold
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
        vol_ma, _, _ = self._get_tech_indicators(20)
        vol_ma = vol_ma.reindex(df.index)
        total_range = (df['High'] - df['Low']).replace(0, float('nan'))
        body_ratio = ((df['Close'] - df['Open']).abs() / total_range).fillna(0)
        close_position = ((df['Close'] - df['Low']) / total_range).fillna(0.5)

        # 修复：移除K线颜色限制（No Supply可以是任何颜色的小实体，书：十字星/纺锤线）
        no_supply_mask = (body_ratio < self.thresholds.VSA_NO_SUPPLY_BODY_RATIO) & (df['Volume'] < vol_ma * self._get_volume_threshold('shrink', self.thresholds.VSA_NO_SUPPLY_VOL_RATIO)) & (close_position >= self.thresholds.VSA_NO_SUPPLY_CLOSE_POS)
        no_demand_mask = (body_ratio < self.thresholds.VSA_NO_DEMAND_BODY_RATIO) & (df['Volume'] < vol_ma * self._get_volume_threshold('shrink', self.thresholds.VSA_NO_DEMAND_VOL_RATIO)) & (close_position <= self.thresholds.VSA_NO_DEMAND_CLOSE_POS)
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
        vol_ma, _, _ = self._get_tech_indicators(20)
        vol_ma = vol_ma.reindex(df.index)
        
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
