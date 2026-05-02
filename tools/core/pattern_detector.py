import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from ..config.settings import WyckoffConfig, WyckoffThresholds
import logging
logger = logging.getLogger(__name__)

class WyckoffPatternDetector:
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, analysis_cache):
        self.data = data
        self.config = config
        self._analysis_cache = analysis_cache

    def detect_trading_range(self, window: int = 60) -> Dict:

        """检测交易区间（积累/分布），新增动态积累期持续时间计算"""
        if self.data is None or len(self.data) < window:
            return {}

        df = self.data.tail(window).copy()

        high_max = df['High'].max()
        low_min = df['Low'].min()
        range_pct = (high_max - low_min) / low_min

        is_consolidation = range_pct < 0.3

        # 防止短数据导致的切片错误
        recent_mean = df['Volume'].iloc[-20:].mean()
        early_mean = df['Volume'].iloc[:-20].mean() if len(df) > 20 else recent_mean
        vol_trend = 'decreasing' if recent_mean < early_mean else 'increasing'

        current_price = df['Close'].iloc[-1]
        position = (current_price - low_min) / (high_max - low_min) if high_max > low_min else 0.5

        # 动态估算积累期持续时间（向前扫描同幅度区间）
        consolidation_duration_days = window
        if is_consolidation and len(self.data) > window:
            extra_df = self.data.copy()
            for extra_window in [90, 120, 180, 252]:
                if len(extra_df) < extra_window:
                    break
                ext = extra_df.tail(extra_window)
                ext_range = (ext['High'].max() - ext['Low'].min()) / ext['Low'].min()
                if ext_range < 0.35:  # 稍微放宽阈值以覆盖更长时间
                    consolidation_duration_days = extra_window
                else:
                    break

        return {
            'is_consolidation': is_consolidation,
            'high': high_max,
            'low': low_min,
            'range_pct': range_pct,
            'duration_days': window,
            'consolidation_duration_days': consolidation_duration_days,  # 动态估算积累持续时间
            'volume_trend': vol_trend,
            'position': position,
            'current_price': current_price
        }

    def detect_spring(self, lookback: int = None) -> Dict:
        """
        增强版Spring检测 (V2) - 带缓存
        """
        lookback = lookback or self.config.spring_lookback
        cache_key = f"spring_{lookback}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_spring_impl, lookback
        )

    def _detect_spring_impl(self, lookback: int = None) -> Dict:
        """
        Spring检测核心实现
        """
        lookback = lookback or self.config.spring_lookback
        """
        威科夫Spring完整定义：
        1. 存在明确的交易区间（至少30天的横盘整理）
        2. 价格短暂跌破交易区间下边界（1-3天）
        3. 快速收回区间内（收盘价回到支撑位上方）
        4. 成交量模式：下跌时缩量或正常，反弹时放量
        """
        if self.data is None or len(self.data) < 30:
            return {'detected': False, 'reason': 'insufficient_data'}
            
        df = self.data.tail(lookback).copy()
        
        # 步骤1：检测交易区间
        tr_window = 60
        if len(df) < tr_window:
            return {'detected': False, 'reason': 'insufficient_data'}
        
        tr_data = df.tail(tr_window)
        tr_high = tr_data['High'].max()
        tr_low = tr_data['Low'].min()
        tr_range_pct = (tr_high - tr_low) / tr_low
        
        # 交易区间幅度应该小于阈值
        if tr_range_pct > self.config.spring_range_threshold:
            return {'detected': False, 'reason': 'no_trading_range'}
        
        # 步骤2：确认支撑位（交易区间下边界）
        support_level = tr_low
        
        # 获取股性波动率分类
        volatility_class = self._classify_volatility()
        threshold_map = {'low': 0.03, 'medium': 0.04, 'high': 0.05}
        max_breakdown_pct = threshold_map.get(volatility_class, 0.04)
        
        # 步骤3：向量化寻找跌破支撑的情况（优化性能）
        search_df = df.iloc[max(0, len(df) - 45):].copy()

        # 向量化计算：识别跌破支撑位的K线
        breakdown_mask = (
            (search_df['Low'] < support_level) &
            (search_df['Low'] >= support_level * (1 - max_breakdown_pct))
        )

        if not breakdown_mask.any():
            return {'detected': False, 'reason': 'no_breakdown_found'}

        # 向量化计算：收盘价位置和成交量比率
        search_df = search_df.copy()
        search_df['close_above_support'] = search_df['Close'] >= support_level
        search_df['vol_ma'] = search_df['Volume_MA20'].fillna(search_df['Volume'].mean())
        search_df['breakdown_vol_ratio'] = search_df['Volume'] / search_df['vol_ma']
        search_df['daily_range'] = search_df['High'] - search_df['Low']
        search_df['close_position'] = (
            (search_df['Close'] - search_df['Low']) / search_df['daily_range']
        ).fillna(1.0)

        # 向量化检查未来恢复情况（使用rolling和shift）
        recovery_days = self.config.spring_max_recovery_days
        recovery_info = []

        for day_offset in range(recovery_days + 1):
            if day_offset == 0:
                # 当天恢复
                future_mask = search_df['close_above_support']
            else:
                # 未来day_offset天内恢复
                future_close = search_df['Close'].shift(-day_offset)
                future_mask = future_close > support_level

            recovery_info.append({
                'day_offset': day_offset,
                'recovery_mask': future_mask,
                'recovery_close': search_df['Close'].shift(-day_offset),
                'recovery_high': search_df['High'].shift(-day_offset),
                'recovery_low': search_df['Low'].shift(-day_offset),
                'recovery_vol': search_df['Volume'].shift(-day_offset)
            })

        # 找到每个跌破点的最早恢复日
        springs = []
        seen_dates = set()

        breakdown_indices = search_df[breakdown_mask].index

        for idx in breakdown_indices:
            date_key = idx.strftime('%Y-%m-%d')
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)

            row_idx = search_df.index.get_loc(idx)
            current_low = search_df.loc[idx, 'Low']
            current_close = search_df.loc[idx, 'Close']
            current_vol = search_df.loc[idx, 'Volume']
            vol_ma = search_df.loc[idx, 'vol_ma']

            # 检查恢复情况
            recovery_found = False
            recovery_day = 0
            recovery_close = current_close
            recovery_high = search_df.loc[idx, 'High']
            recovery_low = current_low
            recovery_vol = current_vol

            close_above_support = search_df.loc[idx, 'close_above_support']

            if close_above_support:
                recovery_found = True
            else:
                for recovery in recovery_info[1:]:  # 跳过第0个（当天）
                    if row_idx < len(search_df) and recovery['recovery_mask'].iloc[row_idx]:
                        recovery_found = True
                        recovery_day = recovery['day_offset']
                        recovery_close = recovery['recovery_close'].iloc[row_idx]
                        recovery_high = recovery['recovery_high'].iloc[row_idx]
                        recovery_low = recovery['recovery_low'].iloc[row_idx]
                        recovery_vol = recovery['recovery_vol'].iloc[row_idx]
                        break

            if not recovery_found:
                continue

            # 收盘位置验证
            daily_range = recovery_high - recovery_low
            if daily_range > 0:
                close_position = (recovery_close - recovery_low) / daily_range
            else:
                close_position = 1.0 if recovery_close >= support_level else 0.0

            if not (recovery_close >= support_level or close_position >= 0.5):
                continue

            # 成交量模式验证
            breakdown_vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1
            recovery_vol_ratio = recovery_vol / vol_ma if vol_ma > 0 else 1

            vol_pattern = 'neutral'
            if breakdown_vol_ratio < 0.8 and recovery_vol_ratio > 1.2:
                vol_pattern = 'bullish'
            elif breakdown_vol_ratio < 1.0 and recovery_vol_ratio > 1.0:
                vol_pattern = 'mildly_bullish'
            elif breakdown_vol_ratio > 1.5:
                vol_pattern = 'bearish'

            # 综合判断
            is_spring = False
            confidence = 0

            if close_above_support and close_position >= 0.7:
                is_spring = True
                confidence = 0.85
            elif close_above_support:
                is_spring = True
                confidence = 0.75
            elif recovery_found and vol_pattern in ['bullish', 'mildly_bullish']:
                is_spring = True
                confidence = 0.65
            elif recovery_found and recovery_day <= 2:
                is_spring = True
                confidence = 0.5

            if is_spring:
                springs.append({
                    'date': idx,
                    'breakdown_price': current_low,
                    'support_level': support_level,
                    'recovery_day': recovery_day,
                    'recovery_price': recovery_close,
                    'close_above_support': close_above_support,
                    'vol_pattern': vol_pattern,
                    'breakdown_volume': current_vol,
                    'recovery_volume': recovery_vol,
                    'volume_ma': vol_ma,
                    'confidence': confidence,
                    'price': current_low
                })

        if springs:
            return {'detected': True, 'signals': springs, 'latest_spring': springs[-1]}
        return {'detected': False, 'reason': 'no_spring_found'}

    def detect_climax(self) -> Dict:
        """
        检测高潮（CL）- 向量化版本
        """
        return self._analysis_cache.get_or_compute("climax", self._detect_climax_impl)

    def _detect_climax_impl(self) -> Dict:
        """向量化高潮检测实现"""
        if self.data is None or len(self.data) < 20:
            return {'detected': False}
        
        df = self.data.copy()
        
        # 向量化计算
        avg_range = (df['High'] - df['Low']).rolling(20).mean()
        vol_spike = df['Volume'] / df['Volume_MA20']
        range_spike = (df['High'] - df['Low']) / avg_range
        
        # 布尔掩码 - 一次性筛选所有高潮日
        climax_mask = (vol_spike >= self.config.climax_vol_multiplier) & (range_spike >= self.config.climax_range_multiplier)
        
        if not climax_mask.any():
            return {'detected': False}
        
        # 获取所有高潮日期
        climax_dates = df.index[climax_mask]
        latest_date = climax_dates[-1]
        latest_idx = df.index.get_loc(latest_date)
        
        # 价格变化（与前一日对比）
        price_change = df['Close'].iloc[latest_idx] - df['Close'].iloc[latest_idx - 1]
        
        return {
            'detected': True,
            'type': 'buying_climax' if price_change > 0 else 'selling_climax',
            'date': latest_date,
            'price': df['Close'].iloc[latest_idx],
            'volume': df['Volume'].iloc[latest_idx],
            'volume_ratio': vol_spike.iloc[latest_idx],
            'range_ratio': range_spike.iloc[latest_idx]
        }

    def detect_automatic_reaction(self, climax_event: Dict) -> Dict:
        """检测自动反弹/回落（AR）"""
        if not climax_event.get('detected'):
            return {'detected': False}
        
        df = self.data.copy()
        try:
            climax_idx = df.index.get_loc(climax_event['date'])
        except KeyError:
            return {'detected': False}
        
        # 在高潮后5天内寻找AR
        for i in range(climax_idx + 1, min(climax_idx + 6, len(df))):
            current_vol = df['Volume'].iloc[i]
            climax_vol = df['Volume'].iloc[climax_idx]
            
            # 成交量应该低于高潮
            if current_vol < climax_vol * 0.7:
                if climax_event['type'] == 'buying_climax':
                    # 买入高潮后应该是下跌
                    if df['Close'].iloc[i] < df['Close'].iloc[climax_idx]:
                        return {
                            'detected': True,
                            'type': 'automatic_reaction',
                            'date': df.index[i],
                            'price': df['Close'].iloc[i],
                            'direction': 'down'
                        }
                else:
                    # 卖出高潮后应该是上涨
                    if df['Close'].iloc[i] > df['Close'].iloc[climax_idx]:
                        return {
                            'detected': True,
                            'type': 'automatic_rally',
                            'date': df.index[i],
                            'price': df['Close'].iloc[i],
                            'direction': 'up'
                        }
        
        return {'detected': False}

    def detect_secondary_test(self, climax_event: Dict, ar_event: Dict) -> Dict:
        """检测二次测试（ST） - 向量化修复版
        修复：添加核心条件 - 成交量必须明显小于高潮（< 50%），避免误判
        """
        if not climax_event.get('detected') or not ar_event.get('detected'):
            return {'detected': False}

        df = self.data.copy()
        try:
            climax_idx = df.index.get_loc(climax_event['date'])
        except KeyError:
            return {'detected': False}

        # 使用原始高潮量
        climax_raw_volume = climax_event.get('volume', df['Volume'].iloc[climax_idx])

        # 向量化搜索：在高潮后25天内寻找ST
        search_end = min(climax_idx + 25, len(df))
        if search_end <= climax_idx + 2:
            return {'detected': False}

        search_df = df.iloc[climax_idx + 2:search_end].copy()

        # 核心条件：成交量必须明显缩量 (< 高潮量的 50%)
        vol_filter = search_df['Volume'] < climax_raw_volume * 0.5

        if not vol_filter.any():
            return {'detected': False}

        st_events = []
        seen_dates = set()

        # 根据高潮类型向量化识别测试水平
        if climax_event['type'] == 'buying_climax':
            climax_high = df['High'].iloc[climax_idx]
            test_mask = vol_filter & (search_df['High'] > climax_high * 0.95)

            for idx in search_df[test_mask].index:
                date_key = idx.strftime('%Y-%m-%d')
                if date_key not in seen_dates:
                    seen_dates.add(date_key)
                    st_events.append({
                        'detected': True,
                        'type': 'secondary_test',
                        'date': idx,
                        'price': search_df.loc[idx, 'Close'],
                        'test_level': 'high',
                        'volume_ratio_vs_climax': round(search_df.loc[idx, 'Volume'] / climax_raw_volume, 2)
                    })
        else:
            climax_low = df['Low'].iloc[climax_idx]
            test_mask = vol_filter & (search_df['Low'] < climax_low * 1.05)

            for idx in search_df[test_mask].index:
                date_key = idx.strftime('%Y-%m-%d')
                if date_key not in seen_dates:
                    seen_dates.add(date_key)
                    st_events.append({
                        'detected': True,
                        'type': 'secondary_test',
                        'date': idx,
                        'price': search_df.loc[idx, 'Close'],
                        'test_level': 'low',
                        'volume_ratio_vs_climax': round(search_df.loc[idx, 'Volume'] / climax_raw_volume, 2)
                    })

        if st_events:
            return st_events[-1]  # 返回最近的二次测试
        return {'detected': False}

    def detect_upthrust(self, lookback: int = 20) -> Dict:
        """检测Upthrust（假突破）- 带缓存"""
        cache_key = f"upthrust_{lookback}"
        return self._analysis_cache.get_or_compute(
            cache_key, self._detect_upthrust_impl, lookback
        )

    def _detect_upthrust_impl(self, lookback: int = 20) -> Dict:
        """Upthrust检测核心实现 - 向量化版本"""
        if self.data is None or len(self.data) < lookback + 10:
            return {}

        df = self.data.tail(lookback + 10).copy()

        # 向量化计算20日滚动最高点作为阻力位
        df['resistance_level'] = df['High'].rolling(window=20, min_periods=10).max().shift(1)

        # 获取波动率分类
        volatility_class = self._classify_volatility()
        threshold_map = {'low': 0.03, 'medium': 0.04, 'high': 0.05}
        max_breakout_pct = threshold_map.get(volatility_class, 0.04)

        # 向量化识别假突破条件
        breakout_mask = (
            (df['resistance_level'] < df['High']) &
            (df['High'] <= df['resistance_level'] * (1 + max_breakout_pct))
        )

        if not breakout_mask.any():
            return {'detected': False}

        # 计算日内位置
        df['daily_range'] = df['High'] - df['Low']
        df['close_from_high'] = (
            (df['High'] - df['Close']) / df['daily_range']
        ).fillna(0.0)

        # 向量化检查未来5天的最低点
        future_lows = pd.DataFrame({
            f'low_{i}': df['Low'].shift(-i) for i in range(1, 6)
        })
        df['future_low'] = future_lows.min(axis=1)
        df['future_low_idx'] = future_lows.idxmin(axis=1).replace({
            f'low_{i}': i for i in range(1, 6)
        }).astype(float)

        # 计算未来平均成交量
        future_vols = pd.DataFrame({
            f'vol_{i}': df['Volume'].shift(-i) for i in range(1, 6)
        })
        df['future_avg_vol'] = future_vols.mean(axis=1)

        # 过滤有效的Upthrust候选
        valid_upthrust_mask = (
            breakout_mask &
            (df['future_low'] < df['resistance_level']) &
            (df['future_low_idx'] <= 3) &
            (df['close_from_high'] > 0.7) &
            (df['Volume'] > df['future_avg_vol'] * 1.2)
        )

        if not valid_upthrust_mask.any():
            return {'detected': False}

        # 收集有效的Upthrust事件
        upthrusts = []
        seen_dates = set()

        for idx in df[valid_upthrust_mask].index:
            date_key = idx.strftime('%Y-%m-%d')
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)

            upthrusts.append({
                'date': idx,
                'breakout_price': df.loc[idx, 'High'],
                'resistance_level': df.loc[idx, 'resistance_level'],
                'rejection_price': df.loc[idx, 'future_low'],
                'rejection_days': int(df.loc[idx, 'future_low_idx']),
                'close_from_high': round(df.loc[idx, 'close_from_high'], 3),
                'breakout_volume': df.loc[idx, 'Volume'],
                'rejection_volume': df.loc[idx, 'future_avg_vol'],
                'volume_ma': df.loc[idx, 'Volume_MA20']
            })

        if upthrusts:
            return {'detected': True, 'upthrusts': upthrusts, 'latest_upthrust': upthrusts[-1]}
        return {'detected': False}

    def detect_sos(self) -> Dict:
        """检测SOS（Sign of Strength - 强势信号）- 向量化版本"""
        return self._analysis_cache.get_or_compute("sos", self._detect_sos_impl)

    def _detect_sos_impl(self) -> Dict:
        """向量化SOS检测实现"""
        if self.data is None or len(self.data) < 60:
            return {}

        df = self.data.copy()
        volatility_class = self._classify_volatility()
        threshold_map = {'low': 0.02, 'medium': 0.035, 'high': 0.05}
        min_price_change = threshold_map.get(volatility_class, 0.035)

        # 向量化计算
        past_high = df['High'].rolling(20).max().shift(1)
        price_change = df['Close'].pct_change()
        vol_ratio = df['Volume'] / df['Volume_MA20'].replace(0, np.nan)
        daily_range = df['High'] - df['Low']
        
        # 收盘位置计算 (确保是 Series 类型)
        close_position = pd.Series(
            np.where(
                daily_range > 0,
                (df['Close'] - df['Low']) / daily_range,
                np.where(price_change > 0, 1.0, 0.0)
            ),
            index=df.index
        )
        
        # 涨停板判断
        is_limit_up = price_change >= 0.095
        
        # SOS 掩码
        sos_mask = (
            (df['Close'] > past_high) &
            (price_change > min_price_change) &
            (close_position > 0.7) &
            ((vol_ratio > 1.5) | is_limit_up)
        )
        
        # 排除前20天（无有效过去高点）
        sos_mask.iloc[:20] = False
        
        if not sos_mask.any():
            return {'detected': False}
            
        # 收集信号
        sos_indices = np.where(sos_mask)[0]
        sos_signals = []
        for idx in sos_indices:
            sos_signals.append({
                'date': df.index[idx],
                'price': df['Close'].iloc[idx],
                'volume': df['Volume'].iloc[idx],
                'volume_ratio': vol_ratio.iloc[idx],
                'price_change': price_change.iloc[idx],
                'breakthrough_level': past_high.iloc[idx]
            })

        return {'detected': True, 'signals': sos_signals, 'latest': sos_signals[-1]}

    def detect_sow(self) -> Dict:
        """检测SOW（Sign of Weakness - 弱势信号）- 带缓存"""
        return self._analysis_cache.get_or_compute("sow", self._detect_sow_impl)

    def _detect_sow_impl(self) -> Dict:
        """SOW检测核心实现 (向量化版本)"""
        if self.data is None or len(self.data) < 60:
            return {}

        df = self.data.copy()
        volatility_class = self._classify_volatility()
        threshold_map = {'low': -0.02, 'medium': -0.035, 'high': -0.05}
        max_price_drop = threshold_map.get(volatility_class, -0.035)

        # 向量化计算
        past_low = df['Low'].rolling(20).min().shift(1)
        price_change = df['Close'].pct_change()
        vol_ratio = df['Volume'] / df['Volume_MA20'].replace(0, np.nan)
        daily_range = df['High'] - df['Low']
        
        # 收盘位置计算 (SOW 是从高点算起的跌幅位置，确保是 Series 类型)
        close_position = pd.Series(
            np.where(
                daily_range > 0,
                (df['High'] - df['Close']) / daily_range,
                np.where(price_change < 0, 1.0, 0.0)
            ),
            index=df.index
        )
        
        # 跌停板判断
        is_limit_down = price_change <= -0.095

        # SOW 掩码
        sow_mask = (
            (df['Close'] < past_low) &
            (price_change < max_price_drop) &
            (close_position > 0.7) &
            ((vol_ratio > 1.5) | is_limit_down)
        )
        
        # 排除前20天
        sow_mask.iloc[:20] = False

        if not sow_mask.any():
            return {'detected': False}
            
        # 收集信号
        sow_indices = np.where(sow_mask)[0]
        sow_signals = []
        for idx in sow_indices:
            sow_signals.append({
                'date': df.index[idx],
                'price': df['Close'].iloc[idx],
                'volume': df['Volume'].iloc[idx],
                'volume_ratio': vol_ratio.iloc[idx],
                'price_change': price_change.iloc[idx],
                'breakdown_level': past_low.iloc[idx]
            })

        return {'detected': True, 'signals': sow_signals, 'latest': sow_signals[-1]}

    def detect_lps(self, days_since_sos: int = 20, sos_result: Dict = None) -> Dict:
        """检测 LPS（Last Point of Support - 最后支撑点） - 修复版
        修复: sos_raw_vol == 0 的短路逻辑会绕过所有量能校验
               改为: 有 SOS 量就与之对比，没有就 fallback 到 Volume_MA20 均量
        sos_result: 可传入预先计算的 detect_sos() 结果，避免重复计算
        """
        if sos_result is None:
            sos_result = self.detect_sos()
        if not sos_result.get('detected'):
            return {'detected': False}

        latest_sos = sos_result['latest']
        sos_date = latest_sos['date']
        sos_raw_vol = latest_sos.get('volume', 0)

        mask = self.data.index >= sos_date
        df_after_sos = self.data[mask].tail(days_since_sos)

        if len(df_after_sos) < 3:
            return {'detected': False}

        lps_idx = df_after_sos['Low'].idxmin()
        lps_price = df_after_sos['Low'].min()
        lps_vol = df_after_sos.loc[lps_idx, 'Volume']
        vol_ma = df_after_sos.loc[lps_idx, 'Volume_MA20'] if 'Volume_MA20' in df_after_sos.columns else 0

        # 量能校验（修复：消除 sos_raw_vol==0 短路）：
        #   主条件：有 SOS 原始量时，LPS量 < SOS量 * 0.7（回踩缩量 = 多头吸笹完毕）
        #   兜底条件：无 SOS 原始量时，改为 LPS量 < 均量 * 0.8（避免无条件通过）
        if sos_raw_vol > 0:
            vol_ok = lps_vol < sos_raw_vol * 0.7
        else:
            vol_ok = (vol_ma > 0 and lps_vol < vol_ma * 0.8)

        is_lps = (
            vol_ok and
            lps_price > latest_sos['breakthrough_level'] * 0.95
        )

        if is_lps:
            return {
                'detected': True,
                'date': lps_idx,
                'price': lps_price,
                'volume': lps_vol,
                'sos_volume': sos_raw_vol,
                'vol_ma': vol_ma,
                'pullback_pct': (latest_sos['price'] - lps_price) / latest_sos['price']
            }
        return {'detected': False}

    def detect_lpsy(self, days_since_sow: int = 20, sow_result: Dict = None) -> Dict:
        """检测 LPSY（Last Point of Supply - 最后供应点） - 修复版
        修复: sow_raw_vol == 0 的短路逻辑会绕过所有量能校验
               改为: 有 SOW 量就与之对比，没有就 fallback 到 Volume_MA20 均量
        sow_result: 可传入预先计算的 detect_sow() 结果，避免重复计算
        """
        if sow_result is None:
            sow_result = self.detect_sow()
        if not sow_result.get('detected'):
            return {'detected': False}

        latest_sow = sow_result['latest']
        sow_date = latest_sow['date']
        sow_raw_vol = latest_sow.get('volume', 0)

        mask = self.data.index >= sow_date
        df_after_sow = self.data[mask].tail(days_since_sow)

        if len(df_after_sow) < 3:
            return {'detected': False}

        lpsy_idx = df_after_sow['High'].idxmax()
        lpsy_price = df_after_sow['High'].max()
        lpsy_vol = df_after_sow.loc[lpsy_idx, 'Volume']
        vol_ma = df_after_sow.loc[lpsy_idx, 'Volume_MA20'] if 'Volume_MA20' in df_after_sow.columns else 0

        # 量能校验（修复：消除 sow_raw_vol==0 短路）：
        #   主条件：有 SOW 原始量时，LPSY量 < SOW量 * 0.7（反弹缩量 = 空头尉来未散）
        #   兜底条件：无 SOW 原始量时，改为 LPSY量 < 均量 * 0.8（避免无条件通过）
        if sow_raw_vol > 0:
            vol_ok = lpsy_vol < sow_raw_vol * 0.7
        else:
            vol_ok = (vol_ma > 0 and lpsy_vol < vol_ma * 0.8)

        is_lpsy = (
            vol_ok and
            lpsy_price < latest_sow['breakdown_level'] * 1.05
        )

        if is_lpsy:
            return {
                'detected': True,
                'date': lpsy_idx,
                'price': lpsy_price,
                'volume': lpsy_vol,
                'sow_volume': sow_raw_vol,
                'vol_ma': vol_ma,
                'rally_pct': (lpsy_price - latest_sow['price']) / latest_sow['price']
            }
        return {'detected': False}

    def detect_sos_variants(self) -> Dict:
        """
        检测SOS变体形态 - 增强版
        包括：跳空缺口SOS、巨量SOS、突破SOS等多种变体
        """
        if self.data is None or len(self.data) < 60:
            return {'detected': False, 'reason': 'insufficient_data'}

        sos_variants = []
        df = self.data.copy()
        volatility_class = self._classify_volatility()
        threshold_map = {'low': 0.02, 'medium': 0.035, 'high': 0.05}
        min_price_change = threshold_map.get(volatility_class, 0.035)

        # 计算技术指标
        df['Volume_MA20'] = df['Volume'].rolling(20).mean()
        df['Price_Change'] = df['Close'].pct_change()
        df['Gap'] = (df['Open'] - df['High'].shift(1)) / df['High'].shift(1)

        # 1. 跳空缺口SOS (Gap SOS)
        gap_threshold = 0.015  # 1.5%以上的向上跳空
        gap_sos_mask = (
            (df['Gap'] > gap_threshold) &
            (df['Volume'] > df['Volume_MA20'] * 1.5) &
            (df['Close'] > df['Open'])  # 跳空后收阳线
        )

        for idx in df[gap_sos_mask].tail(3).index:
            sos_variants.append({
                'type': 'gap_sos',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume': df.loc[idx, 'Volume'],
                'gap_size': round(df.loc[idx, 'Gap'] * 100, 2),
                'strength': 'strong',
                'description': f"向上跳空{round(df.loc[idx, 'Gap'] * 100, 1)}%且放量，强势突破信号"
            })

        # 2. 巨量SOS (High Volume SOS)
        high_vol_sos_mask = (
            (df['Volume'] > df['Volume_MA20'] * 2.5) &
            (df['Price_Change'] > min_price_change) &
            (df['Close'] > df['Open'])
        )

        for idx in df[high_vol_sos_mask].tail(3).index:
            volume_ratio = df.loc[idx, 'Volume'] / df.loc[idx, 'Volume_MA20']
            sos_variants.append({
                'type': 'high_volume_sos',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume': df.loc[idx, 'Volume'],
                'volume_ratio': round(volume_ratio, 1),
                'price_change': round(df.loc[idx, 'Price_Change'] * 100, 2),
                'strength': 'very_strong',
                'description': f"巨量突破（量比{round(volume_ratio, 1)}倍），超级强势信号"
            })

        # 3. 连续突破SOS (Consecutive Breakthrough SOS)
        df['Resistance'] = df['High'].rolling(20).max()
        breakthrough_mask = (
            (df['Close'] > df['Resistance'].shift(1)) &
            (df['Volume'] > df['Volume_MA20'] * 1.3)
        )

        # 寻找连续突破
        for i in range(len(df) - 2):
            if breakthrough_mask.iloc[i] and breakthrough_mask.iloc[i + 1]:
                sos_variants.append({
                    'type': 'consecutive_sos',
                    'date': df.index[i + 1],
                    'price': df['Close'].iloc[i + 1],
                    'volume': df['Volume'].iloc[i + 1],
                    'strength': 'strong',
                    'description': "连续两天放量突破，持续性强势信号"
                })
                break

        # 4. 底部反转SOS (Bottom Reversal SOS)
        # 检测长期下跌后的强力反转
        df['MA50'] = df['Close'].rolling(50).mean()
        bottom_reversal_mask = (
            (df['Close'] < df['MA50'] * 0.95) &  # 价格低于50日均线5%以上
            (df['Price_Change'] > min_price_change * 2) &  # 大幅上涨
            (df['Volume'] > df['Volume_MA20'] * 2) &  # 大幅放量
            (df['Close'] > df['Open'])  # 收阳线
        )

        for idx in df[bottom_reversal_mask].tail(2).index:
            sos_variants.append({
                'type': 'bottom_reversal_sos',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume': df.loc[idx, 'Volume'],
                'price_change': round(df.loc[idx, 'Price_Change'] * 100, 2),
                'strength': 'very_strong',
                'description': "长期下跌后的底部放量反转，潜在趋势转变信号"
            })

        if sos_variants:
            return {
                'detected': True,
                'variants': sos_variants,
                'total_signals': len(sos_variants),
                'latest_variant': sos_variants[-1],
                'overall_strength': self._calculate_overall_sos_strength(sos_variants)
            }

        return {'detected': False, 'reason': 'no_sos_variants_found'}

    def detect_sow_variants(self) -> Dict:
        """
        检测SOW变体形态 - 增强版
        包括：跳空缺口SOW、巨量SOW、破位SOW等多种变体
        """
        if self.data is None or len(self.data) < 60:
            return {'detected': False, 'reason': 'insufficient_data'}

        sow_variants = []
        df = self.data.copy()
        volatility_class = self._classify_volatility()
        threshold_map = {'low': 0.02, 'medium': 0.035, 'high': 0.05}
        min_price_change = threshold_map.get(volatility_class, 0.035)

        # 计算技术指标
        df['Volume_MA20'] = df['Volume'].rolling(20).mean()
        df['Price_Change'] = df['Close'].pct_change()
        df['Gap'] = (df['Open'] - df['Low'].shift(1)) / df['Low'].shift(1)

        # 1. 跳空缺口SOW (Gap SOW)
        gap_threshold = 0.015  # 1.5%以上的向下跳空
        gap_sow_mask = (
            (df['Gap'] < -gap_threshold) &
            (df['Volume'] > df['Volume_MA20'] * 1.5) &
            (df['Close'] < df['Open'])  # 跳空后收阴线
        )

        for idx in df[gap_sow_mask].tail(3).index:
            sow_variants.append({
                'type': 'gap_sow',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume': df.loc[idx, 'Volume'],
                'gap_size': round(abs(df.loc[idx, 'Gap']) * 100, 2),
                'strength': 'strong',
                'description': f"向下跳空{round(abs(df.loc[idx, 'Gap']) * 100, 1)}%且放量，弱势突破信号"
            })

        # 2. 巨量SOW (High Volume SOW)
        high_vol_sow_mask = (
            (df['Volume'] > df['Volume_MA20'] * 2.5) &
            (df['Price_Change'] < -min_price_change) &
            (df['Close'] < df['Open'])
        )

        for idx in df[high_vol_sow_mask].tail(3).index:
            volume_ratio = df.loc[idx, 'Volume'] / df.loc[idx, 'Volume_MA20']
            sow_variants.append({
                'type': 'high_volume_sow',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume': df.loc[idx, 'Volume'],
                'volume_ratio': round(volume_ratio, 1),
                'price_change': round(df.loc[idx, 'Price_Change'] * 100, 2),
                'strength': 'very_strong',
                'description': f"巨量下跌（量比{round(volume_ratio, 1)}倍），超级弱势信号"
            })

        # 3. 破位SOW (Breakdown SOW)
        df['Support'] = df['Low'].rolling(20).min()
        breakdown_mask = (
            (df['Close'] < df['Support'].shift(1)) &
            (df['Volume'] > df['Volume_MA20'] * 1.3)
        )

        for idx in df[breakdown_mask].tail(3).index:
            sow_variants.append({
                'type': 'breakdown_sow',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume': df.loc[idx, 'Volume'],
                'support_level': df.loc[idx, 'Support'],
                'strength': 'strong',
                'description': "跌破支撑位且放量，技术性破位信号"
            })

        # 4. 顶部反转SOW (Top Reversal SOW)
        # 检测长期上涨后的强力反转
        df['MA50'] = df['Close'].rolling(50).mean()
        top_reversal_mask = (
            (df['Close'] > df['MA50'] * 1.05) &  # 价格高于50日均线5%以上
            (df['Price_Change'] < -min_price_change * 2) &  # 大幅下跌
            (df['Volume'] > df['Volume_MA20'] * 2) &  # 大幅放量
            (df['Close'] < df['Open'])  # 收阴线
        )

        for idx in df[top_reversal_mask].tail(2).index:
            sow_variants.append({
                'type': 'top_reversal_sow',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume': df.loc[idx, 'Volume'],
                'price_change': round(df.loc[idx, 'Price_Change'] * 100, 2),
                'strength': 'very_strong',
                'description': "长期上涨后的顶部放量反转，潜在趋势转变信号"
            })

        if sow_variants:
            return {
                'detected': True,
                'variants': sow_variants,
                'total_signals': len(sow_variants),
                'latest_variant': sow_variants[-1],
                'overall_strength': self._calculate_overall_sow_strength(sow_variants)
            }

        return {'detected': False, 'reason': 'no_sow_variants_found'}

    def _calculate_overall_sos_strength(self, variants: List[Dict]) -> str:
        """计算SOS变体的总体强度"""
        if not variants:
            return 'none'

        strength_scores = {
            'very_strong': 3,
            'strong': 2,
            'moderate': 1,
            'weak': 0
        }

        total_score = sum(strength_scores.get(v.get('strength', 'weak'), 0) for v in variants)

        if total_score >= 6:
            return 'very_strong'
        elif total_score >= 4:
            return 'strong'
        elif total_score >= 2:
            return 'moderate'
        else:
            return 'weak'

    def _calculate_overall_sow_strength(self, variants: List[Dict]) -> str:
        """计算SOW变体的总体强度"""
        # 使用与SOS相同的评分逻辑
        return self._calculate_overall_sos_strength(variants)

    def detect_pattern_confirmation(self) -> Dict:
        """
        形态确认机制 - 检查形态是否得到后续价格行为的确认
        确认原则：
        1. Spring确认：后续价格上涨且不创新低
        2. SOS确认：后续持续上涨且缩量回调
        3. Upthrust确认：后续确实下跌且量能配合
        """
        if self.data is None or len(self.data) < 20:
            return {'detected': False, 'reason': 'insufficient_data'}

        confirmation_results = {}

        # 检查Spring确认
        spring_result = self.detect_spring()
        if spring_result.get('detected'):
            confirmation_results['spring'] = self._check_spring_confirmation(spring_result)

        # 检查SOS确认
        sos_result = self.detect_sos()
        if sos_result.get('detected'):
            confirmation_results['sos'] = self._check_sos_confirmation(sos_result)

        # 检查Upthrust确认
        upthrust_result = self.detect_upthrust()
        if upthrust_result.get('detected'):
            confirmation_results['upthrust'] = self._check_upthrust_confirmation(upthrust_result)

        if confirmation_results:
            confirmed_patterns = {
                k: v for k, v in confirmation_results.items() if v.get('confirmed', False)
            }

            return {
                'has_confirmation': len(confirmed_patterns) > 0,
                'confirmation_results': confirmation_results,
                'confirmed_patterns': list(confirmed_patterns.keys()),
                'total_confirmations': len(confirmed_patterns),
                'reliability_score': self._calculate_reliability_score(confirmation_results)
            }

        return {'has_confirmation': False, 'reason': 'no_patterns_to_confirm'}

    def _check_spring_confirmation(self, spring_result: Dict) -> Dict:
        """检查Spring形态是否得到确认"""
        if not spring_result.get('signals'):
            return {'confirmed': False, 'reason': 'no_spring_signals'}

        latest_spring = spring_result['signals'][-1]
        spring_date = latest_spring['date']
        spring_price = latest_spring['breakdown_price']

        # 检查后续价格行为
        subsequent_data = self.data[self.data.index > spring_date].head(10)

        if len(subsequent_data) < 3:
            return {'confirmed': False, 'reason': 'insufficient_subsequent_data'}

        # 确认条件：
        # 1. 后续价格没有创新低
        # 2. 至少有一根K线收盘价高于Spring日的收盘价
        # 3. 整体呈上升趋势

        no_new_low = subsequent_data['Low'].min() >= spring_price * 0.98
        higher_close = (subsequent_data['Close'] > subsequent_data['Open']).sum() >= len(subsequent_data) * 0.6

        # 简单趋势检查：最近收盘价高于3天前
        if len(subsequent_data) >= 3:
            uptrend = subsequent_data['Close'].iloc[-1] > subsequent_data['Close'].iloc[0]
        else:
            uptrend = False

        confirmed = no_new_low and (higher_close or uptrend)

        return {
            'confirmed': confirmed,
            'no_new_low': no_new_low,
            'higher_close_ratio': higher_close,
            'uptrend': uptrend,
            'confirmation_strength': 'strong' if confirmed and uptrend else ('moderate' if confirmed else 'weak')
        }

    def _check_sos_confirmation(self, sos_result: Dict) -> Dict:
        """检查SOS形态是否得到确认"""
        if not sos_result.get('signals'):
            return {'confirmed': False, 'reason': 'no_sos_signals'}

        latest_sos = sos_result['signals'][-1]
        sos_date = latest_sos['date']
        breakthrough_level = latest_sos['breakthrough_level']

        # 检查后续价格行为
        subsequent_data = self.data[self.data.index > sos_date].head(10)

        if len(subsequent_data) < 3:
            return {'confirmed': False, 'reason': 'insufficient_subsequent_data'}

        # 确认条件：
        # 1. 价格保持在突破位上方
        # 2. 有适当的缩量回调（健康回调）
        # 3. 整体趋势向上

        above_breakthrough = subsequent_data['Close'].min() >= breakthrough_level * 0.97

        # 检查是否有健康的缩量回调
        volume_ma = self.data['Volume_MA20']
        subsequent_volume = self.data[self.data.index > sos_date]['Volume'].head(5)

        if len(subsequent_volume) > 0:
            pullback_volume_ok = subsequent_volume.mean() <= volume_ma.mean() * 0.9
        else:
            pullback_volume_ok = False

        # 趋势检查
        if len(subsequent_data) >= 3:
            uptrend = subsequent_data['Close'].iloc[-1] > subsequent_data['Close'].iloc[0]
        else:
            uptrend = False

        confirmed = above_breakthrough and uptrend

        return {
            'confirmed': confirmed,
            'above_breakthrough': above_breakthrough,
            'pullback_volume_ok': pullback_volume_ok,
            'uptrend': uptrend,
            'confirmation_strength': 'strong' if confirmed and pullback_volume_ok else ('moderate' if confirmed else 'weak')
        }

    def _check_upthrust_confirmation(self, upthrust_result: Dict) -> Dict:
        """检查Upthrust形态是否得到确认"""
        if not upthrust_result.get('detected'):
            return {'confirmed': False, 'reason': 'no_upthrust_signals'}

        upthrusts = upthrust_result.get('upthrusts', [])
        if not upthrusts:
            return {'confirmed': False, 'reason': 'no_upthrust_details'}

        latest_upthrust = upthrusts[-1]
        upthrust_date = latest_upthrust['date']
        resistance_level = latest_upthrust['resistance_level']

        # 检查后续价格行为
        subsequent_data = self.data[self.data.index > upthrust_date].head(10)

        if len(subsequent_data) < 3:
            return {'confirmed': False, 'reason': 'insufficient_subsequent_data'}

        # 确认条件：
        # 1. 价格确实跌回阻力位下方
        # 2. 没有再次突破阻力位
        # 3. 整体呈下降趋势

        below_resistance = subsequent_data['Close'].max() < resistance_level * 1.02

        # 检查是否有再次尝试突破
        no_retest = subsequent_data['High'].max() < resistance_level * 1.01

        # 趋势检查
        if len(subsequent_data) >= 3:
            downtrend = subsequent_data['Close'].iloc[-1] < subsequent_data['Close'].iloc[0]
        else:
            downtrend = False

        confirmed = below_resistance and (no_retest or downtrend)

        return {
            'confirmed': confirmed,
            'below_resistance': below_resistance,
            'no_retest': no_retest,
            'downtrend': downtrend,
            'confirmation_strength': 'strong' if confirmed and downtrend else ('moderate' if confirmed else 'weak')
        }

    def _calculate_reliability_score(self, confirmation_results: Dict) -> float:
        """
        根据形态确认结果计算信号可靠性评分
        范围：0-1，越高表示信号越可靠
        """
        if not confirmation_results:
            return 0.0

        total_score = 0.0
        count = 0

        for pattern_type, confirmation in confirmation_results.items():
            if not confirmation.get('confirmed', False):
                continue

            strength = confirmation.get('confirmation_strength', 'weak')
            if strength == 'strong':
                total_score += 1.0
            elif strength == 'moderate':
                total_score += 0.7
            elif strength == 'weak':
                total_score += 0.4

            count += 1

        if count == 0:
            return 0.0

        return min(total_score / count, 1.0)

    def detect_divergence(self, window: int = 30) -> Dict:
        """量价/RSI背离检测
        顶背离识别：价格创新高但 RSI/成交量未创新高，预示上涨动能衰竭
        底背离识别：价格创新低但 RSI/成交量未创新低，预示下跌动能衰竭
        """
        if self.data is None or len(self.data) < window:
            return {'detected': False, 'reason': 'insufficient_data'}

        df = self.data.tail(window).copy()
        if 'RSI' not in df.columns or df['RSI'].isna().all():
            return {'detected': False, 'reason': 'RSI not calculated'}

        mid = len(df) // 2
        df_early = df.iloc[:mid]
        df_late = df.iloc[mid:]

        if len(df_early) < 5 or len(df_late) < 5:
            return {'detected': False}

        # 1. 顶背离
        price_high_early = df_early['High'].max()
        price_high_late = df_late['High'].max()
        rsi_high_early = df_early['RSI'].max()
        rsi_high_late = df_late['RSI'].max()
        vol_high_early = df_early['Volume'].max()
        vol_high_late = df_late['Volume'].max()

        top_div = False
        top_confidence = 0.8
        top_desc = ""

        if price_high_late > price_high_early and rsi_high_late < rsi_high_early:
            top_div = True
            top_desc = f"价格创新高（{price_high_early:.2f} -> {price_high_late:.2f}），但RSI未创新高（{rsi_high_early:.1f} -> {rsi_high_late:.1f}），预示上涨动能衰竭"
            if vol_high_late < vol_high_early:
                top_confidence = 0.9
                top_desc += "。同时成交量也确认衰竭。"

        # 2. 底背离
        price_low_early = df_early['Low'].min()
        price_low_late = df_late['Low'].min()
        rsi_low_early = df_early['RSI'].min()
        rsi_low_late = df_late['RSI'].min()
        vol_low_early = df_early['Volume'].max()
        vol_low_late = df_late['Volume'].max()

        bottom_div = False
        bottom_confidence = 0.8
        bottom_desc = ""

        if price_low_late < price_low_early and rsi_low_late > rsi_low_early:
            bottom_div = True
            bottom_desc = f"价格创新低（{price_low_early:.2f} -> {price_low_late:.2f}），但RSI未创新低（{rsi_low_early:.1f} -> {rsi_low_late:.1f}），预示下跌动能衰竭"
            if vol_low_late < vol_low_early:
                bottom_confidence = 0.9
                bottom_desc += "。同时成交量也确认衰竭。"

        if top_div:
            return {
                'detected': True,
                'type': 'top_divergence',
                'confidence': top_confidence,
                'description': top_desc,
                'details': {
                    'price_early': float(price_high_early),
                    'price_late': float(price_high_late),
                    'rsi_early': float(rsi_high_early),
                    'rsi_late': float(rsi_high_late),
                    'vol_early': float(vol_high_early),
                    'vol_late': float(vol_high_late)
                }
            }
        elif bottom_div:
            return {
                'detected': True,
                'type': 'bottom_divergence',
                'confidence': bottom_confidence,
                'description': bottom_desc,
                'details': {
                    'price_early': float(price_low_early),
                    'price_late': float(price_low_late),
                    'rsi_early': float(rsi_low_early),
                    'rsi_late': float(rsi_low_late),
                    'vol_early': float(vol_low_early),
                    'vol_late': float(vol_low_late)
                }
            }

        return {'detected': False}

    def calculate_sequence_score(self, events: Dict, phase: str) -> Dict:
        """事件序列量化评分
        完整度评估：计算积累/分布阶段的事件链完整度 (0-100分)
        缺失事件追踪：自动识别并列出缺失的关键威科夫事件
        动态置信度调整：
        ≥80% 完整度：系数 1.0（不调整）
        ≥60% 完整度：系数 0.9（轻微下调）
        ≥40% 完整度：系数 0.75（适度下调）
        <40% 完整度：系数 0.6（大幅下调）
        """
        is_accum = 'Accumulation' in phase or 'Unknown' in phase
        if is_accum:
            critical_events = {
                'climax': 'selling_climax',
                'automatic_reaction': 'automatic_rally',
                'secondary_test': 'secondary_test',
                'spring_upthrust': 'spring',
                'sos_sow': 'sos',
                'lps_lpsy': 'lps'
            }
        else:
            critical_events = {
                'climax': 'buying_climax',
                'automatic_reaction': 'automatic_reaction',
                'secondary_test': 'secondary_test',
                'spring_upthrust': 'upthrust',
                'sos_sow': 'sow',
                'lps_lpsy': 'lpsy'
            }

        detected_count = 0
        missing_events = []

        for k, expected_type in critical_events.items():
            ev = events.get(k)
            if ev and ev.get('detected'):
                t = ev.get('type') or ev.get('_type')
                if not t or expected_type in str(t).lower():
                    detected_count += 1
                else:
                    missing_events.append(expected_type)
            else:
                missing_events.append(expected_type)

        completeness = round((detected_count / len(critical_events)) * 100, 1)
        base_score = 40 + (detected_count / len(critical_events)) * 60

        if completeness >= 80:
            adj_factor = 1.0
        elif completeness >= 60:
            adj_factor = 0.9
        elif completeness >= 40:
            adj_factor = 0.75
        else:
            adj_factor = 0.6

        final_score = round(base_score * adj_factor, 1)
        rating = self._get_sequence_rating(final_score, completeness)

        return {
            'completeness': completeness,
            'score': final_score,
            'rating': rating,
            'missing_events': missing_events,
            'adjustment_factor': adj_factor
        }

    def _get_sequence_rating(self, score: float, completeness: float) -> str:
        """根据分值和完整度进行信号评级
        S 级：score≥85 且 completeness≥80（顶级信号，重仓机会）
        A 级：score≥70 且 completeness≥60（优质信号，正常仓位）
        B 级：score≥55 且 completeness≥40（普通信号，轻仓试探）
        C 级：其他（弱信号，建议观望）
        """
        if score >= 85 and completeness >= 80:
            return "S (顶级信号，重仓机会)"
        elif score >= 70 and completeness >= 60:
            return "A (优质信号，正常仓位)"
        elif score >= 55 and completeness >= 40:
            return "B (普通信号，轻仓试探)"
        else:
            return "C (弱信号，建议观望)"

    def identify_phase(self) -> Dict:
        """
        增强版阶段识别 (V2)
        基于威科夫事件序列，而非简单的均线排列
        返回包含置信度、细分事件、多时间框架等综合判断的字典
        """
        if self.data is None:
            return {'phase': 'Unknown', 'confidence': 0.0}

        events = {
            'climax': self.detect_climax(),
            'automatic_reaction': None,
            'secondary_test': None,
            'spring_upthrust': None,
            'sos_sow': None,
            'lps_lpsy': None
        }
        
        if events['climax']['detected']:
            events['automatic_reaction'] = self.detect_automatic_reaction(events['climax'])
        
        if events['climax']['detected'] and events['automatic_reaction'] and events['automatic_reaction']['detected']:
            events['secondary_test'] = self.detect_secondary_test(
                events['climax'], 
                events['automatic_reaction']
            )
        
        # 将现有的形态检测合并进去，对 sos/sow 先计算一次再复用
        spring_res = self.detect_spring()
        upthrust_res = self.detect_upthrust()
        sos_res = self.detect_sos()
        sow_res = self.detect_sow()
        # 将预先计算的结果传入，避免 detect_lps/detect_lpsy 内部再次调用 detect_sos/detect_sow
        lps_res = self.detect_lps(sos_result=sos_res)
        lpsy_res = self.detect_lpsy(sow_result=sow_res)

        if spring_res.get('detected'):
            events['spring_upthrust'] = {**spring_res, '_type': 'spring'}
        elif upthrust_res.get('detected'):
            events['spring_upthrust'] = {**upthrust_res, '_type': 'upthrust'}

        if sos_res.get('detected'):
            events['sos_sow'] = {**sos_res, '_type': 'sos'}
        elif sow_res.get('detected'):
            events['sos_sow'] = {**sow_res, '_type': 'sow'}

        if lps_res.get('detected'):
            events['lps_lpsy'] = {**lps_res, '_type': 'lps'}
        elif lpsy_res.get('detected'):
            events['lps_lpsy'] = {**lpsy_res, '_type': 'lpsy'}

        # 步骤2：根据事件序列判断阶段
        phase, confidence = self._determine_phase_from_events(events)
        
        # 如果事件序列无法判断（常见情况），退回到使用原有的交易区间和均线判断逻辑
        if phase == 'Unknown':
            tr_info = self.detect_trading_range()
            if not tr_info.get('is_consolidation'):
                ma20 = self.data['MA20'].iloc[-1]
                ma50 = self.data['MA50'].iloc[-1]
                ma200 = self.data['MA200'].iloc[-1]
                current = self.data['Close'].iloc[-1]
                
                if current > ma20 > ma50 > ma200:
                    phase = "Markup Phase E (强势上涨)"
                    confidence = 0.6
                elif current > ma20 > ma50 and ma20 < ma200:
                    phase = "Accumulation Phase D (可能在建仓末期)"
                    confidence = 0.5
                elif current < ma20 < ma50 < ma200:
                    phase = "Markdown Phase E (强势下跌)"
                    confidence = 0.6
                elif current < ma20 < ma50 and ma20 > ma200:
                    phase = "Distribution Phase D (可能在出货末期)"
                    confidence = 0.5
                else:
                    phase = "Trending (趋势中)"
                    confidence = 0.4
            else:
                position = tr_info['position']
                vol_trend = tr_info['volume_trend']
                
                if vol_trend == 'decreasing':
                    if position < 0.3:
                        phase = "Accumulation Phase B/C (可能在建仓中)"
                    elif position < 0.7:
                        phase = "Accumulation Phase C-D (可能在震仓)"
                    else:
                        phase = "Accumulation Phase D-E (准备突破)"
                    confidence = 0.5
                else:
                    if position > 0.7:
                        phase = "Distribution Phase B/C (可能在出货中)"
                    elif position > 0.3:
                        phase = "Distribution Phase C-D (可能在假突破)"
                    else:
                        phase = "Distribution Phase D-E (准备跌破)"
                    confidence = 0.5

        # 步骤3：结合均线趋势确认
        ma_confidence = self._check_ma_confirmation(phase)
        
        # 步骤4：结合成交量确认
        vol_confidence = self._check_volume_confirmation(phase)
        
        final_confidence = confidence * 0.5 + ma_confidence * 0.3 + vol_confidence * 0.2

        # 结合事件序列量化评分和背离检测进行智能调整
        seq_score = self.calculate_sequence_score(events, phase)
        final_confidence *= seq_score.get('adjustment_factor', 1.0)
        div_res = self.detect_divergence()

        return {
            'phase': phase,
            'confidence': min(final_confidence, 1.0),
            'events_detected': events,
            'ma_confidence': ma_confidence,
            'vol_confidence': vol_confidence,
            'sequence_score': seq_score,
            'divergence': div_res
        }

    def _determine_phase_from_events(self, events: Dict) -> Tuple[str, float]:
        """根据事件序列判断阶段 - 修复版
        修复: 使用结构化 '_type' 字段区分 Spring vs Upthrust，替代脆弱的字符串包含判断
        """
        su = events.get('spring_upthrust') or {}
        ss = events.get('sos_sow') or {}
        cl = events.get('climax') or {}
        ar = events.get('automatic_reaction') or {}
        st = events.get('secondary_test') or {}

        is_spring   = su.get('detected') and su.get('_type') == 'spring'
        is_upthrust = su.get('detected') and su.get('_type') == 'upthrust'
        is_sos      = ss.get('detected') and ss.get('_type') == 'sos'
        is_sow      = ss.get('detected') and ss.get('_type') == 'sow'

        # Spring + SOS → 积累期 Phase D (最强买入信号)
        if is_spring and is_sos:
            return 'Accumulation Phase D (积累期突破)', 0.85
        # Spring 独立 → Phase C
        if is_spring:
            return 'Accumulation Phase C (积累期震仓)', 0.70
        # Upthrust + SOW → 派发期 Phase D (最强卖出信号)
        if is_upthrust and is_sow:
            return 'Distribution Phase D (派发期跌破)', 0.85
        # Upthrust 独立 → Phase C
        if is_upthrust:
            return 'Distribution Phase C (派发期诱多)', 0.70
        # CL + AR → Phase A
        if cl.get('detected') and ar.get('detected'):
            if cl.get('type') == 'selling_climax':
                return 'Accumulation Phase A (恐慌抛售停止)', 0.75
            else:
                return 'Distribution Phase A (买入高潮停止)', 0.75
        # ST → Phase B
        if st.get('detected'):
            if cl.get('type') == 'selling_climax':
                return 'Accumulation Phase B (积累期测试)', 0.60
            else:
                return 'Distribution Phase B (派发期测试)', 0.60
        return 'Unknown', 0.30

    def _check_ma_confirmation(self, phase: str) -> float:
        """检查均线是否确认阶段判断
        修复: 原逻辑完全倒置。
          - Markup 上涨期: 价格应在 MA200 上方，且均线多头排列才给高分
          - Accumulation 积累期: 价格在底部区域，MA20 开始好转
          - Markdown 下跌期: 价格应在 MA200 下方，均线空头排列给高分
          - Distribution 派发期: 价格在高位，MA20 开始向下
        """
        ma20 = self.data['MA20'].iloc[-1]
        ma50 = self.data['MA50'].iloc[-1]
        ma200 = self.data['MA200'].iloc[-1]
        current = self.data['Close'].iloc[-1]

        if 'Markup' in phase:
            # 上涨期: 价格高于 MA200，且均线多头排列，得高分
            if current > ma200 and ma20 > ma50 > ma200:
                return 0.9
            elif current > ma200 and ma20 > ma50:
                return 0.7
            elif current > ma200:
                return 0.5
            else:
                return 0.3
        elif 'Accumulation' in phase:
            # 积累期: 价格仍在底部 (< MA200)，但 MA20 已开始好转向上
            if current < ma200 and ma20 > ma50:
                return 0.8
            elif current < ma200:
                return 0.5
            else:
                return 0.4
        elif 'Markdown' in phase:
            # 下跌期: 价格低于 MA200，均线空头排列给高分
            if current < ma200 and ma20 < ma50 < ma200:
                return 0.9
            elif current < ma200 and ma20 < ma50:
                return 0.7
            elif current < ma200:
                return 0.5
            else:
                return 0.3
        elif 'Distribution' in phase:
            # 派发期: 价格仍在高位 (> MA200)，但 MA20 开始向下
            if current > ma200 and ma20 < ma50:
                return 0.8
            elif current > ma200:
                return 0.6
            else:
                return 0.4
        return 0.5

    def _check_volume_confirmation(self, phase: str) -> float:
        """检查成交量是否确认阶段判断 - 升级版
        升级: 区分积累期子阶段的量价结构
          - Phase A/B 吸笹期: 大跌放量/小涨缩量 才是主力吸笹特征（跌天量 > 涨天量反而对）
          - Phase D/E 突破期: 涨天量 > 跌天量 才是健康突破特征
        """
        df = self.data.tail(20)
        up_days = df[df['Close'] > df['Close'].shift(1)]
        down_days = df[df['Close'] < df['Close'].shift(1)]

        if len(up_days) == 0 or len(down_days) == 0:
            return 0.5

        avg_up_vol = up_days['Volume'].mean()
        avg_down_vol = down_days['Volume'].mean()
        vol_ratio = avg_up_vol / avg_down_vol if avg_down_vol > 0 else 1

        if 'Markup' in phase:
            # 上涨期: 涨天放量、跌天缩量 = 健康特征
            if vol_ratio > 1.3: return 0.9
            if vol_ratio > 1.1: return 0.7
            if vol_ratio > 0.9: return 0.5
            return 0.3
        elif 'Accumulation' in phase:
            # 积累期 Phase A/B: 大跌放量吵跌，小涨缩量轻浮 = 主力吸笹中 (跌天量 > 涨天量)
            # 积累期 Phase D/E: 涨天量开始放大，准备突破 (涨天量 > 跌天量)
            if 'Phase A' in phase or 'Phase B' in phase:
                # A/B 阶段吸笹期: 跌天量大 = 应该吸笹在进行，得分要反过来
                if vol_ratio < 0.8: return 0.8  # 涨天缩量，吸笹特征
                if vol_ratio < 1.0: return 0.6
                return 0.4
            else:
                # C/D/E 阶段: 需要涨天放量证明多头力量
                if vol_ratio > 1.2: return 0.8
                if vol_ratio > 1.0: return 0.6
                return 0.4
        elif 'Markdown' in phase:
            # 下跌期: 跌天放量、涨天缩量 = 健康下跌
            if vol_ratio < 0.7: return 0.9
            if vol_ratio < 0.9: return 0.7
            if vol_ratio < 1.1: return 0.5
            return 0.3
        elif 'Distribution' in phase:
            if 'Phase A' in phase or 'Phase B' in phase:
                # 派发期 A/B: 涨天放量，跌天缩量 = 证明主力在出货
                if vol_ratio > 1.2: return 0.8
                if vol_ratio > 1.0: return 0.6
                return 0.4
            else:
                # C/D/E: 跌天量开始放大，市场开始崩溃
                if vol_ratio < 0.8: return 0.8
                if vol_ratio < 1.0: return 0.6
                return 0.4
        return 0.5

    def _classify_volatility(self) -> str:
        """根据 ATR 占比分类股票股性（高/中/低波动）"""
        if self.data is None or len(self.data) < 14:
            return 'medium'
            
        current_price = self.data['Close'].iloc[-1]
        atr = self.data['ATR'].iloc[-1]
        atr_pct = atr / current_price if current_price > 0 else 0
        
        if atr_pct < 0.02:
            return 'low'     # 大盘蓝筹
        elif atr_pct > 0.04:
            return 'high'    # 小盘活跃股
        else:
            return 'medium'  # 中等波动

