import pandas as pd
import numpy as np
import logging
from typing import Any, Dict, List, Optional, cast
from .base_detector import BaseDetector, USE_VECTORIZED
from ...config.settings import WyckoffConfig, WyckoffThresholds

logger = logging.getLogger(__name__)

class StrengthWeaknessDetector(BaseDetector):
    """
    负责检测 SOS (Sign of Strength) 和 SOW (Sign of Weakness) 及其变体

    重要理论约束：
    - SOS (强势信号) 只发生在吸筹阶段末期或上涨趋势中
    - 在派发阶段，向上突破应归类为 UT (Upthrust) 或 UTAD (派发后的上冲回落)
    - 系统必须根据当前阶段动态调整信号分类
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds
        #  P0-2修复：初始化信号屏蔽集合
        self._blocked_signals = set()
        # 孟洪涛原则：信号质量优先级
        self._signal_priority = {
            'joc': 90,      # JOC 是最高质量的突破信号
            'fti': 90,      # FTI 是最高质量的跌破信号
            'spring': 85,   # Spring 是最重要的吸筹形态
            'upthrust': 80, # Upthrust 是重要的派发形态
            'sos': 60,      # SOS 是一般突破信号
            'sow': 60,      # SOW 是一般跌破信号
        }
        # 已检测到的高优先级信号（用于排他逻辑）
        self._detected_high_priority_signals = set()

    def _ensure_columns(self, df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """确保所需的指标列存在，缺失时从缓存获取或动态计算"""
        df = df.copy()
        for col in columns:
            if col in df.columns:
                continue

            if self._indicator_cache:
                try:
                    df[col] = self._indicator_cache.get(col)
                    continue
                except Exception:
                    pass

            # 降级逻辑
            if col == 'Volume_MA20':
                df[col] = df['Volume'].rolling(20, min_periods=1).mean()
            elif col == 'MA20':
                df[col] = df['Close'].rolling(20, min_periods=1).mean()
            elif col == 'ATR':
                atr_series = self._calculate_atr_series(df, period=14)
                df[col] = atr_series.reindex(df.index)

        return df

    @staticmethod
    def _get_event_field(event_obj, key: str, default=None):
        """兼容 dict / Pydantic 事件对象的字段读取。"""
        if event_obj is None:
            return default
        if isinstance(event_obj, dict):
            return event_obj.get(key, default)
        return getattr(event_obj, key, default)

    @classmethod
    def _latest_event_detail(cls, event_obj, latest_key: str = 'latest'):
        latest = cls._get_event_field(event_obj, latest_key)
        if latest:
            return latest
        signals = cls._get_event_field(event_obj, 'signals', []) or []
        return signals[-1] if signals else None

    @staticmethod
    def _numeric_value(value, default=None):
        if isinstance(value, dict):
            value = value.get('value', default)
        elif hasattr(value, 'value'):
            value = getattr(value, 'value')
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def update_analysis_context(self, phase: str):
        """更新当前阶段，用于动态调整信号分类"""
        super().update_analysis_context(phase)

    def reset_blocked_signals(self):
        """
        🔧 P0-2修复：重置信号屏蔽状态

        应在每次分析开始时调用，避免上一次分析的屏蔽状态污染下一次分析。
        """
        self._blocked_signals.clear()
        self._detected_high_priority_signals.clear()

    def block_signal(self, signal_type: str):
        """
        🔧 P0-2修复：屏蔽特定信号类型

        Args:
            signal_type: 信号类型，如 'sos' 或 'sow'
        """
        self._blocked_signals.add(signal_type)

    def register_high_priority_signal(self, signal_type: str):
        """
        孟洪涛原则：注册高优先级信号（用于排他逻辑）

        当检测到 JOC/FTI 等高优先级信号时，调用此方法注册。
        后续检测到的低优先级信号（如 SOS）将被忽略。

        Args:
            signal_type: 信号类型，如 'joc', 'fti', 'spring', 'upthrust'
        """
        if signal_type in self._signal_priority and self._signal_priority[signal_type] >= 80:
            self._detected_high_priority_signals.add(signal_type)
            logger.info(f"[孟洪涛原则] 注册高优先级信号: {signal_type}，将屏蔽同方向的低优先级信号")

    def _should_exclude_signal(self, signal_type: str) -> tuple:
        """
        孟洪涛原则：检查信号是否应被高优先级信号排除

        Returns:
            (should_exclude: bool, reason: str)
        """
        if signal_type not in self._signal_priority:
            return False, ""

        current_priority = self._signal_priority[signal_type]

        # 检查是否有高优先级信号已检测到
        for detected_signal in self._detected_high_priority_signals:
            detected_priority = self._signal_priority.get(detected_signal, 0)

            # 只比较同方向的信号
            if detected_priority > current_priority:
                # 做多方向信号
                if signal_type in ('sos',) and detected_signal in ('joc', 'spring'):
                    return True, f"已被高优先级信号 {detected_signal.upper()} 排除（孟洪涛原则：{detected_signal.upper()} > {signal_type.upper()}）"
                # 做空方向信号
                if signal_type in ('sow',) and detected_signal in ('fti', 'upthrust'):
                    return True, f"已被高优先级信号 {detected_signal.upper()} 排除（孟洪涛原则：{detected_signal.upper()} > {signal_type.upper()}）"

        return False, ""

    def _is_signal_blocked(self, signal_type: str) -> bool:
        """检查信号是否被屏蔽"""
        return signal_type in self._blocked_signals


    def _is_distribution_phase(self) -> bool:
        """判断当前是否处于派发阶段"""
        if self._current_phase is None:
            return False
        return 'distribution' in self._current_phase.lower() or '派发' in self._current_phase

    def _is_accumulation_phase(self) -> bool:
        """判断当前是否处于吸筹阶段"""
        if self._current_phase is None:
            return False
        return 'accumulation' in self._current_phase.lower() or '吸筹' in self._current_phase

    def detect_sos(self, window: int = 40) -> Dict:
        """
        检测标准 SOS (Sign of Strength)

        孟洪涛原则：如果已检测到 JOC（更高质量的突破信号），则忽略 SOS
        """
        # 孟洪涛原则：检查是否被高优先级信号排除
        should_exclude, exclude_reason = self._should_exclude_signal('sos')
        if should_exclude:
            logger.info(f"[孟洪涛原则] SOS信号被排除: {exclude_reason}")
            return {'detected': False, 'reason': 'excluded_by_high_priority_signal', 'note': exclude_reason}

        if USE_VECTORIZED:
            try:
                return self._detect_sos_vectorized(window)
            except Exception as e:
                logger.warning(f"Vectorized SOS failed: {e}. Falling back to iterative method.")
                return self._detect_sos_iterative(window)
        return self._detect_sos_iterative(window)

    def _detect_sos_vectorized(self, window: int = 40) -> Dict:
        if self._is_signal_blocked('sos'):
            return {'detected': False, 'reason': 'signal_blocked_by_phase', 'note': '当前阶段为派发期，向上突破应归类为UT/UTAD，SOS信号已被屏蔽'}

        if self.data is None or len(self.data) < window:
            return {'detected': False}

        if self._is_distribution_phase():
            return {'detected': False, 'reason': 'distribution_phase_no_sos'}

        df = self.data.tail(window).copy()

        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['moderate']
        price_change_threshold = self.thresholds.SOS_PRICE_CHANGE_DEFAULT

        # 转换为 NumPy 数组（显式 asarray 收窄类型，消除 ExtensionArray → np.roll 的类型不兼容）
        closes = np.asarray(df['Close'].values, dtype=np.float64)
        opens  = np.asarray(df['Open'].values,  dtype=np.float64)
        highs  = np.asarray(df['High'].values,  dtype=np.float64)
        lows   = np.asarray(df['Low'].values,   dtype=np.float64)
        volumes = np.asarray(df['Volume'].values, dtype=np.float64)

        # 获取 vol_ma 并进行 shift(1).bfill() 消除未来前瞻偏差
        if self._indicator_cache and self._indicator_cache.get('Volume_MA20') is not None:
            vol_ma_series = self._indicator_cache.get('Volume_MA20').shift(1).bfill()
            vol_ma = np.asarray(vol_ma_series.reindex(df.index).values, dtype=np.float64)
        elif 'Volume_MA20' in df.columns:
            vol_ma_series = self.data['Volume_MA20'].shift(1).bfill()
            vol_ma = np.asarray(vol_ma_series.reindex(df.index).values, dtype=np.float64)
        else:
            vol_ma_all = self.data['Volume'].rolling(20, min_periods=1).mean().shift(1).bfill()
            vol_ma = np.asarray(vol_ma_all.reindex(df.index).values, dtype=np.float64)

        # price_pct_change - 使用 np.where 安全除法
        prev_closes = np.roll(closes, 1)
        prev_closes[0] = closes[0]
        safe_prev_closes = np.where(np.abs(prev_closes) > 1e-9, prev_closes, 1.0)
        price_pct_change = (closes - prev_closes) / safe_prev_closes

        # 安全计算 close_position
        denominators = highs - lows
        safe_denominators = np.where(denominators == 0, 1.0, denominators)
        close_position = (closes - lows) / safe_denominators

        upper_shadow = highs - closes
        body = np.abs(closes - opens)
        upper_shadow_ratio = upper_shadow / (body + 0.001)

        sos_mask = (
            (closes > opens) &
            (volumes > vol_ma * vol_ratio_threshold) &
            (price_pct_change > price_change_threshold) &
            (close_position >= 0.70) &
            (upper_shadow_ratio < 0.50)
        )

        sos_indices = np.where(sos_mask)[0]

        if len(sos_indices) > 0:
            idx_pos = sos_indices[-1]
            idx = df.index[idx_pos]

            # 区分突破性质
            if idx_pos >= 20:
                pre_sos_high = np.max(highs[idx_pos-20:idx_pos])
            else:
                pre_sos_high = np.max(highs[:idx_pos+1])

            tr_data = self.data.tail(60)
            tr_high = float(cast(Any, tr_data['High'].max()))
            sos_close = closes[idx_pos]

            if sos_close >= tr_high * 0.98:
                breakout_type = 'breakout_sos'
            elif sos_close >= pre_sos_high * 0.98:
                breakout_type = 'range_high_sos'
            else:
                breakout_type = 'within_range_sos'

            #  P1-2 增强：结合阶段细化分类
            is_phase_d = self._current_phase and 'Phase D' in self._current_phase

            if breakout_type == 'breakout_sos':
                if is_phase_d:
                    signal_rank = 'major_sos'
                    interpretation = '【主要强势信号】有效突破交易区间上沿，确认为 JOC 启动'
                else:
                    signal_rank = 'potential_major_sos'
                    interpretation = '强势突破 TR 上沿，需关注回踩确认（LPS）'
            elif breakout_type == 'range_high_sos':
                signal_rank = 'minor_sos'
                interpretation = '【次要强势信号】突破近期小区间高点，供应正在被吸收'
            else:
                signal_rank = 'minor_sos'
                interpretation = '【次要强势信号】区间内放量阳线，表明需求介入'

            vol_ratio_val = round(float(volumes[idx_pos] / vol_ma[idx_pos]) if vol_ma[idx_pos] > 0 else 1.0, 2)
            price_change_val = round(float(price_pct_change[idx_pos]), 4)
            breakthrough_level_val = {
                "value": round(float(tr_high), 3),
                "derivation": "max_high_in_60d_range",
                "note": "前期交易区间上沿阻力位"
            }
            sig_data = {
                'date': idx,
                'price': float(closes[idx_pos]),
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakthrough_level': breakthrough_level_val
            }
            return {
                'detected': True,
                'type': 'sos',
                'signal_rank': signal_rank,
                'date': idx,
                'price': float(closes[idx_pos]),
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakthrough_level': breakthrough_level_val,
                'breakout_type': breakout_type,
                'phase_context': self._current_phase or 'accumulation_or_uptrend',
                'interpretation': interpretation,
                'signals': [sig_data],
                'latest': sig_data
            }
        return {'detected': False}

    def _detect_sos_iterative(self, window: int = 40) -> Dict:
        """
        检测标准 SOS (Sign of Strength) - 迭代/Pandas 版
        """
        #  P0-2修复：检查信号是否被屏蔽
        if self._is_signal_blocked('sos'):
            return {
                'detected': False,
                'reason': 'signal_blocked_by_phase',
                'note': '当前阶段为派发期，向上突破应归类为UT/UTAD，SOS信号已被屏蔽'
            }

        if self.data is None or len(self.data) < window:
            return {'detected': False}

        # 关键约束：在派发阶段，直接返回未检测到SOS
        # 所有向上突破尝试一律归为 upthrust，由 detect_upthrust() 处理
        if self._is_distribution_phase():
            return {'detected': False, 'reason': 'distribution_phase_no_sos'}

        df = self.data.tail(window).copy()
        vol_ma_all = self.data['Volume'].rolling(20, min_periods=1).mean().shift(1).bfill()
        vol_ma = vol_ma_all.reindex(df.index)
        price_pct_change = df['Close'].pct_change()

        # 使用配置中的阈值
        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['moderate']
        price_change_threshold = self.thresholds.SOS_PRICE_CHANGE_DEFAULT

        # 修复 #6: SOS 必须收盘在日内高位（无长上影线），防止 UT 误判为 SOS
        close_position = (df['Close'] - df['Low']) / (df['High'] - df['Low']).replace(0, float('nan'))
        upper_shadow = df['High'] - df['Close']
        body = (df['Close'] - df['Open']).abs()
        upper_shadow_ratio = upper_shadow / (body + 0.001)

        sos_mask = (
            (df['Close'] > df['Open']) &
            (df['Volume'] > vol_ma * vol_ratio_threshold) &
            (price_pct_change > price_change_threshold) &
            (close_position >= 0.70) &                       # 收盘在高位70%以上
            (upper_shadow_ratio < 0.50)                       # 上影线不超过实体50%
        )
        if sos_mask.any():
            idx = df[sos_mask].index[-1]

            # 区分突破性质：SOS 是否突破了近期 TR 上沿
            pre_sos_high = df.loc[:idx]['High'].iloc[-20:].max() if len(df.loc[:idx]) >= 20 else df['High'].max()
            tr_data = self.data.tail(60)
            tr_high = tr_data['High'].max()
            sos_close = df.loc[idx, 'Close']

            if sos_close >= tr_high * 0.98:
                breakout_type = 'breakout_sos'
                interpretation = '强势突破前期盘整区间阻力，JOC前兆信号'
            elif sos_close >= pre_sos_high * 0.98:
                breakout_type = 'range_high_sos'
                interpretation = '突破近20日高点，但仍在更大区间之内'
            else:
                breakout_type = 'within_range_sos'
                interpretation = '区间内放量阳线，非突破性信号'

            vol_ratio_val = round(df.loc[idx, 'Volume']/cast(Any, vol_ma).loc[idx], 2)
            price_change_val = round(cast(Any, price_pct_change).loc[idx], 4)
            breakthrough_level_val = {
                "value": round(tr_high, 3),
                "derivation": "max_high_in_60d_range",
                "note": "前期交易区间上沿阻力位"
            }
            sig_data = {
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakthrough_level': breakthrough_level_val
            }
            return {
                'detected': True,
                'type': 'sos',
                'date': idx,
                'price': df.loc[idx, 'Close'],
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakthrough_level': breakthrough_level_val,
                'breakout_type': breakout_type,
                'phase_context': 'accumulation_or_uptrend',
                'interpretation': interpretation,
                'signals': [sig_data],
                'latest': sig_data
            }
        return {'detected': False}

    def detect_sow(self, window: int = 40, trading_range: Optional[Dict] = None) -> Dict:
        """
        检测 SOW (Sign of Weakness)

        孟洪涛原则：如果已检测到 FTI（更高质量的跌破信号），则忽略 SOW

        🔧 新增：根据威科夫理论，真正的SOW必须：
        1. 跌破交易区间下沿（或关键支撑位）
        2. 后续无力收回（维持在下沿下方）
        3. 在派发或再吸筹阶段的弱势表现

        Args:
            window: 检测窗口
            trading_range: 当前交易区间（用于验证是否跌破区间下沿）
        """
        # 孟洪涛原则：检查是否被高优先级信号排除
        should_exclude, exclude_reason = self._should_exclude_signal('sow')
        if should_exclude:
            logger.info(f"[孟洪涛原则] SOW信号被排除: {exclude_reason}")
            return {'detected': False, 'reason': 'excluded_by_high_priority_signal', 'note': exclude_reason}

        if USE_VECTORIZED:
            try:
                return self._detect_sow_vectorized(window, trading_range)
            except Exception as e:
                logger.warning(f"Vectorized SOW failed: {e}. Falling back to iterative method.")
                return self._detect_sow_iterative(window, trading_range)
        return self._detect_sow_iterative(window, trading_range)

    def _detect_sow_vectorized(self, window: int = 40, trading_range: Optional[Dict] = None) -> Dict:
        if self._is_signal_blocked('sow'):
            return {'detected': False, 'reason': 'signal_blocked_by_phase', 'note': '当前阶段为吸筹期，向下突破应归类为Spring，SOW信号已被屏蔽'}

        if self.data is None or len(self.data) < window:
            return {'detected': False}

        df = self.data.tail(window).copy()

        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['moderate']
        price_change_threshold = self.thresholds.SOW_PRICE_CHANGE_DEFAULT

        closes = np.asarray(df['Close'].values, dtype=np.float64)
        opens  = np.asarray(df['Open'].values,  dtype=np.float64)
        highs  = np.asarray(df['High'].values,  dtype=np.float64)
        lows   = np.asarray(df['Low'].values,   dtype=np.float64)
        volumes = np.asarray(df['Volume'].values, dtype=np.float64)

        # 获取 vol_ma 并进行 shift(1).bfill() 消除未来前瞻偏差
        if self._indicator_cache and self._indicator_cache.get('Volume_MA20') is not None:
            vol_ma_series = self._indicator_cache.get('Volume_MA20').shift(1).bfill()
            vol_ma = np.asarray(vol_ma_series.reindex(df.index).values, dtype=np.float64)
        elif 'Volume_MA20' in df.columns:
            vol_ma_series = self.data['Volume_MA20'].shift(1).bfill()
            vol_ma = np.asarray(vol_ma_series.reindex(df.index).values, dtype=np.float64)
        else:
            vol_ma_all = self.data['Volume'].rolling(20, min_periods=1).mean().shift(1).bfill()
            vol_ma = np.asarray(vol_ma_all.reindex(df.index).values, dtype=np.float64)

        # price_pct_change - 使用 np.where 安全除法
        prev_closes = np.roll(closes, 1)
        prev_closes[0] = closes[0]
        safe_prev_closes = np.where(np.abs(prev_closes) > 1e-9, prev_closes, 1.0)
        price_pct_change = (closes - prev_closes) / safe_prev_closes

        denominators = highs - lows
        safe_denominators = np.where(denominators == 0, 1.0, denominators)
        close_position = (closes - lows) / safe_denominators

        lower_shadow = lows - np.where(opens < closes, opens, closes)
        body = np.abs(closes - opens)
        lower_shadow_ratio = np.abs(lower_shadow) / (body + 0.001)

        sow_mask = (
            (closes < opens) &
            (volumes > vol_ma * vol_ratio_threshold) &
            (price_pct_change < price_change_threshold) &
            (close_position <= 0.30) &
            (lower_shadow_ratio < 0.50)
        )

        sow_indices = np.where(sow_mask)[0]

        if len(sow_indices) > 0:
            idx_pos = sow_indices[-1]
            idx = df.index[idx_pos]
            sow_price = float(closes[idx_pos])
            sow_low = float(lows[idx_pos])

            #  新增：验证是否跌破交易区间下沿
            tr_low = trading_range.get('low') if trading_range else None
            breakdown_level = df['Low'].rolling(20).min().iloc[-1]

            #  P1-2 增强：结合阶段细化分类
            is_phase_d = self._current_phase and 'Phase D' in self._current_phase

            if tr_low is not None:
                if sow_low < tr_low:
                    # 跌破区间下沿 → 真正的SOW
                    if is_phase_d:
                        signal_rank = 'major_sow'
                        interpretation = f'【主要弱势信号】跌破交易区间下沿{tr_low:.2f}元，确认为 FTI 启动'
                        signal_type = 'true_sow'
                    else:
                        signal_rank = 'major_sow'
                        interpretation = '【主要弱势信号】有效跌破 TR 下沿，供应占主导'
                        signal_type = 'true_sow'
                else:
                    # 未跌破区间下沿 → 区间内弱势
                    signal_rank = 'minor_sow'
                    signal_type = 'within_range_weakness'
                    interpretation = f'【次要弱势信号】区间内弱势表现（未跌破{tr_low:.2f}元），关注支撑测试'
            else:
                signal_rank = 'potential_sow'
                signal_type = 'potential_sow'
                interpretation = '放量下跌，但缺少交易区间信息验证'

            vol_ratio_val = round(float(volumes[idx_pos] / vol_ma[idx_pos]) if vol_ma[idx_pos] > 0 else 1.0, 2)
            price_change_val = round(float(price_pct_change[idx_pos]), 4)
            breakdown_level_val = {
                "value": float(breakdown_level),
                "derivation": "min_low_in_20d_window",
                "note": "近期支撑测试位"
            }
            sig_data = {
                'date': idx,
                'price': sow_price,
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakdown_level': breakdown_level_val
            }
            return {
                'detected': True,
                'type': 'sow',
                'signal_type': signal_type,
                'signal_rank': signal_rank,
                'date': idx,
                'price': sow_price,
                'low': sow_low,
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakdown_level': breakdown_level_val,
                'tr_low': tr_low,
                'interpretation': interpretation,
                'signals': [sig_data],
                'latest': sig_data
            }
        return {'detected': False}

    def _detect_sow_iterative(self, window: int = 40, trading_range: Optional[Dict] = None) -> Dict:
        """
        检测标准 SOW（Sign of Weakness）

        🔧 新增：根据威科夫理论，真正的SOW必须：
        1. 跌破交易区间下沿（或关键支撑位）
        2. 后续无力收回（维持在下沿下方）
        3. 在派发或再吸筹阶段的弱势表现

        Args:
            window: 检测窗口
            trading_range: 当前交易区间（用于验证是否跌破区间下沿）
        """
        #  P0-2修复：检查信号是否被屏蔽
        if self._is_signal_blocked('sow'):
            return {
                'detected': False,
                'reason': 'signal_blocked_by_phase',
                'note': '当前阶段为吸筹期，向下突破应归类为Spring，SOW信号已被屏蔽'
            }

        if self.data is None or len(self.data) < window:
            return {'detected': False}
        df = self.data.tail(window).copy()
        vol_ma_all = self.data['Volume'].rolling(20, min_periods=1).mean().shift(1).bfill()
        vol_ma = vol_ma_all.reindex(df.index)
        price_pct_change = df['Close'].pct_change()

        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['moderate']
        price_change_threshold = self.thresholds.SOW_PRICE_CHANGE_DEFAULT

        close_position = (df['Close'] - df['Low']) / (df['High'] - df['Low']).replace(0, float('nan'))
        lower_shadow = df['Low'] - df['Open'].where(df['Open'] < df['Close'], df['Close'])
        body = (df['Close'] - df['Open']).abs()
        lower_shadow_ratio = lower_shadow.abs() / (body + 0.001)

        sow_mask = (
            (df['Close'] < df['Open']) &
            (df['Volume'] > vol_ma * vol_ratio_threshold) &
            (price_pct_change < price_change_threshold) &
            (close_position <= 0.30) &                       # 收盘在低位30%以下
            (lower_shadow_ratio < 0.50)                       # 下影线不超过实体50%
        )
        if sow_mask.any():
            idx = df[sow_mask].index[-1]
            sow_price = df.loc[idx, 'Close']
            sow_low = df.loc[idx, 'Low']

            #  新增：获取交易区间下沿
            tr_low = trading_range.get('low') if trading_range else None
            breakdown_level = {
                "value": float(df['Low'].rolling(20).min().iloc[-1]),
                "derivation": "min_low_in_20d_window",
                "note": "近期支撑测试位"
            }

            #  新增：判断SOW类型
            if tr_low is not None:
                if sow_low < tr_low:
                    # 跌破区间下沿 → 真正的SOW
                    signal_type = 'true_sow'
                    interpretation = f'跌破交易区间下沿{tr_low:.2f}元，供应占主导'
                else:
                    # 未跌破区间下沿 → 区间内弱势
                    signal_type = 'within_range_weakness'
                    interpretation = f'区间内弱势表现（未跌破{tr_low:.2f}元），可能是震仓或正常回调'
            else:
                signal_type = 'potential_sow'
                interpretation = '放量下跌，但缺少交易区间信息验证'

            vol_ratio_val = round(df.loc[idx, 'Volume']/cast(Any, vol_ma).loc[idx], 2)
            price_change_val = round(cast(Any, price_pct_change).loc[idx], 4)
            sig_data = {
                'date': idx,
                'price': sow_price,
                'low': sow_low,
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakdown_level': breakdown_level,
                'tr_low': tr_low
            }
            return {
                'detected': True,
                'type': 'sow',
                'signal_type': signal_type,
                'date': idx,
                'price': sow_price,
                'low': sow_low,
                'volume_ratio': vol_ratio_val,
                'price_change': price_change_val,
                'breakdown_level': breakdown_level,
                'tr_low': tr_low,
                'interpretation': interpretation,
                'signals': [sig_data],
                'latest': sig_data
            }
        return {'detected': False}

    def detect_lps(
        self,
        window: int = 30,
        spring_res: Dict = None,
        trading_range: Dict = None,
        sos_result: Dict = None,
        joc_result: Dict = None,
    ) -> Dict:
        """
        检测 LPS (Last Point of Support)

        阶段约束：
        - 仅在 Accumulation / Reaccumulation 阶段才标记为正式 LPS
        - Markup 阶段降级为 "pullback"（缩量回踩）
        - 阶段不明或 Distribution 降级为 "pullback_weak"（缩量回调，支撑测试）

        Args:
            window: 检测窗口
            spring_res: Spring检测结果，用于验证LPS低点>Spring低点
            trading_range: 交易区间字典，用于提取 TR 上沿/下沿锚点
            sos_result: SOS检测结果（LPS必须发生在SOS/JOC强势信号之后）
            joc_result: JOC检测结果，用于将 LPS 锚定到 Creek 回测
        """
        if self.data is None or len(self.data) < 60:
            return {'detected': False}

        def _normalize_event_date(raw_date):
            if raw_date is None:
                return None
            event_date = pd.to_datetime(raw_date)
            if self.data.index.tz is not None and event_date.tz is None:
                event_date = event_date.tz_localize('UTC').tz_convert(self.data.index.tz)
            elif self.data.index.tz is None and event_date.tz is not None:
                event_date = event_date.tz_localize(None)
            return event_date

        # 提取 SOS/JOC 日期（LPS 必须发生在突破确认之后）
        breakout_dates = []
        if sos_result and self._get_event_field(sos_result, 'detected'):
            sos_detail = self._latest_event_detail(sos_result)
            sos_date = (
                self._get_event_field(sos_detail, 'date') or
                self._get_event_field(sos_result, 'date')
            )
            normalized_date = _normalize_event_date(sos_date)
            if normalized_date is not None:
                breakout_dates.append(('SOS', normalized_date))

        if joc_result and self._get_event_field(joc_result, 'detected'):
            joc_detail = self._latest_event_detail(joc_result)
            joc_date = (
                self._get_event_field(joc_detail, 'date') or
                self._get_event_field(joc_result, 'date')
            )
            normalized_date = _normalize_event_date(joc_date)
            if normalized_date is not None:
                breakout_dates.append(('JOC', normalized_date))

        # 提取 Spring 低点（若有）
        spring_low = None
        if spring_res and self._get_event_field(spring_res, 'detected'):
            sl = self._get_event_field(spring_res, 'latest_spring') or (
                self._get_event_field(spring_res, 'signals', [{}])[-1]
                if self._get_event_field(spring_res, 'signals') else {}
            )
            spring_low = self._numeric_value(self._get_event_field(sl, 'breakdown_price'))

        # 构建 LPS 回测锚点：优先 Creek/SOS 突破位，其次 TR 上沿，最后才是 TR 下沿。
        tr_support = None
        anchor_candidates = []

        if joc_result and self._get_event_field(joc_result, 'detected'):
            joc_detail = self._latest_event_detail(joc_result)
            creek_level = self._numeric_value(
                self._get_event_field(joc_detail, 'creek_level') or
                self._get_event_field(joc_result, 'creek_level')
            )
            if creek_level and creek_level > 0:
                anchor_candidates.append(('JOC Creek', creek_level))

        if sos_result and self._get_event_field(sos_result, 'detected'):
            sos_detail = self._latest_event_detail(sos_result)
            breakthrough_level = self._numeric_value(
                self._get_event_field(sos_detail, 'breakthrough_level') or
                self._get_event_field(sos_result, 'breakthrough_level')
            )
            if breakthrough_level and breakthrough_level > 0:
                anchor_candidates.append(('SOS突破位', breakthrough_level))

        if trading_range:
            tr_high = self._numeric_value(self._get_event_field(trading_range, 'high'))
            tr_support = self._numeric_value(self._get_event_field(trading_range, 'low'))
            if tr_high and tr_high > 0:
                anchor_candidates.append(('TR上沿', tr_high))
            if tr_support and tr_support > 0:
                anchor_candidates.append(('TR下沿', tr_support))

        # 判断阶段上下文
        is_accumulation = self._is_accumulation_phase()
        is_markup = (self._current_phase is not None
                     and ('Markup' in self._current_phase or '上涨' in self._current_phase))
        is_distribution = self._is_distribution_phase()

        #  P1-1修复：验证Phase A前置结构完整性（SC→AR→ST）
        phase_a_events = self.get_phase_a_events()
        has_complete_phase_a_structure = False
        phase_a_validation = {
            'sc_detected': False,
            'ar_detected': False,
            'st_detected': False,
            'structure_complete': False,
            'missing_events': []
        }

        if is_accumulation and phase_a_events:
            # 只有在吸筹阶段才验证Phase A结构
            phase_a_validation['sc_detected'] = (
                phase_a_events.get('climax', {}).get('type') == 'selling_climax' and
                phase_a_events.get('climax', {}).get('detected', False)
            )
            phase_a_validation['ar_detected'] = phase_a_events.get('ar', {}).get('detected', False)
            phase_a_validation['st_detected'] = phase_a_events.get('st', {}).get('detected', False)

            has_complete_phase_a_structure = (
                phase_a_validation['sc_detected'] and
                phase_a_validation['ar_detected'] and
                phase_a_validation['st_detected']
            )
            phase_a_validation['structure_complete'] = has_complete_phase_a_structure

            # 记录缺失的事件
            if not phase_a_validation['sc_detected']:
                phase_a_validation['missing_events'].append('SC（恐慌抛售）')
            if not phase_a_validation['ar_detected']:
                phase_a_validation['missing_events'].append('AR（自然反弹）')
            if not phase_a_validation['st_detected']:
                phase_a_validation['missing_events'].append('ST（二次测试）')

        df = self._ensure_columns(self.data.tail(window), ['Volume_MA20', 'MA20', 'ATR'])
        df_wide = self._ensure_columns(self.data, ['Volume_MA20'])
        vol_ma = df_wide['Volume_MA20'].reindex(df.index)

        lps_signals = []
        for i in range(5, len(df)):
            current = df.iloc[i]

            low_volume = current['Volume'] < vol_ma.iloc[i] * self.thresholds.VOLUME_CONFIRMATION['weak']
            higher_low = current['Low'] > df.iloc[i-20:i-5]['Low'].min()

            # 修复 #5: LPS 低点必须 > Spring 低点（书：回调不破Spring低点）
            if spring_low is not None and current['Low'] <= spring_low:
                continue

            # 威科夫 LPS：优先观察 SOS/JOC 后对 Creek / 突破位 / TR 上沿的缩量回测。
            near_lps_anchor = True
            matched_anchor_label = None
            matched_anchor_value = None
            matched_anchor_deviation = None
            if anchor_candidates:
                atr_val = current.get('ATR')
                if pd.isna(atr_val) or atr_val <= 0:
                    atr_pct = 0.015
                else:
                    atr_pct = atr_val / max(current['Close'], 1e-9)
                tolerance_upper = min(0.08, max(0.04, atr_pct * 1.5))

                matches = []
                for anchor_label, anchor_value in anchor_candidates:
                    low_pct_from_anchor = (current['Low'] - anchor_value) / max(anchor_value, 1e-9)
                    if -0.03 <= low_pct_from_anchor <= tolerance_upper:
                        matches.append((abs(low_pct_from_anchor), anchor_label, anchor_value, low_pct_from_anchor))

                near_lps_anchor = bool(matches)
                if matches:
                    _, matched_anchor_label, matched_anchor_value, matched_anchor_deviation = min(matches, key=lambda item: item[0])

            # B11: 有 Creek/SOS 锚点时，允许 Close 在 MA20 下方但贴近锚点
            is_pullback_shape = current['Low'] < df.iloc[i-5:i]['High'].max()
            close_above_ma20 = current['Close'] > df['MA20'].iloc[i]
            close_near_creek = (
                matched_anchor_value is not None
                and current['Close'] >= matched_anchor_value * 0.97
            )
            is_pullback = is_pullback_shape and (close_above_ma20 or close_near_creek)

            # 新增：VCP 波动率收缩验证 (P0)
            vcp_detected = False
            window_slice = df.iloc[max(0, i-2):i+1] # 最近 3 根
            if len(window_slice) >= 3:
                bodies = (window_slice['Close'] - window_slice['Open']).abs().values
                ranges = (window_slice['High'] - window_slice['Low']).values
                price_ref = current['Close']

                # 容差检查：body[-1] < body[-2] < body[-3]
                is_body_shrinking = True
                for b_idx in range(len(bodies) - 1, 0, -1):
                    curr_b, prev_b = bodies[b_idx], bodies[b_idx-1]
                    if prev_b < price_ref * 0.001: # 极小实体 (Dojs) 容差
                        if not (curr_b < prev_b * 1.2):
                            is_body_shrinking = False
                            break
                    else:
                        if not (curr_b < prev_b):
                            is_body_shrinking = False
                            break

                is_tight = (bodies[-1] / max(ranges[-1], 1e-9)) < 0.3 # 实体占波幅比例小
                vcp_detected = is_body_shrinking and is_tight

            if is_pullback and low_volume and higher_low and near_lps_anchor:
                signal = {
                    'date': df.index[i],
                    'price': current['Close'],
                    'volume_ratio': round(current['Volume'] / vol_ma.iloc[i], 2),
                    'support_level': matched_anchor_value if matched_anchor_value is not None else df['MA20'].iloc[i],
                    'anchor_type': matched_anchor_label,
                    'vcp_detected': bool(vcp_detected),
                    'confidence_score': 'HIGH' if vcp_detected else 'MEDIUM'
                }

                # 记录 LPS 锚点关系，保留 tr_support 兼容旧报告字段
                if matched_anchor_value is not None:
                    signal['lps_anchor'] = matched_anchor_value
                    signal['lps_anchor_deviation_pct'] = round(float(matched_anchor_deviation * 100), 2)
                if tr_support is not None:
                    signal['tr_support'] = tr_support

                # 阶段约束：只有 Accumulation 阶段且具备完整Phase A结构、且必须在 SOS 强势信号之后才叫 LPS
                if is_accumulation:
                    has_breakout_context = bool(breakout_dates)
                    current_date = pd.to_datetime(df.index[i])
                    is_after_breakout = any(current_date > event_date for _, event_date in breakout_dates)

                    if has_complete_phase_a_structure and has_breakout_context and is_after_breakout:
                        signal['signal_type'] = 'lps'
                        breakout_names = '/'.join(name for name, _ in breakout_dates)
                        note = f'吸筹阶段最后支撑点（LPS）| ✅ 具备完整Phase A结构（SC→AR→ST）并发生在 {breakout_names} 强势突破之后 ✓'
                        if matched_anchor_value is not None:
                            note += f' | 缩量回测{matched_anchor_label}{matched_anchor_value:.2f} ✓'
                    else:
                        signal['signal_type'] = 'support_test'
                        reasons = []
                        if not has_complete_phase_a_structure:
                            missing = ', '.join(phase_a_validation['missing_events'])
                            reasons.append(f'缺少完整Phase A结构：缺失[{missing}]')
                        if not has_breakout_context:
                            reasons.append('未检测到前置 SOS/JOC 强势突破信号')
                        elif not is_after_breakout:
                            latest_breakout = max(event_date for _, event_date in breakout_dates)
                            reasons.append(f'未发生在 SOS/JOC 强势信号之后 (最近突破日期: {latest_breakout.strftime("%Y-%m-%d") if hasattr(latest_breakout, "strftime") else latest_breakout})')

                        note = (f'⚠️ 降级为支撑测试（非正式LPS）| ' + ' | '.join(reasons) +
                                f' | 威科夫理论要求：LPS需前置SC→AR→ST吸筹结构，且必须发生在 SOS/JOC 强势突破之后进行确认性回测')
                elif is_markup:
                    signal['signal_type'] = 'pullback'
                    note = ('上涨趋势缩量回踩（非正式LPS，因缺少SC/AR/ST吸筹前置结构；'
                            '此处定义为趋势中的正常回调支撑测试）')
                elif is_distribution:
                    signal['signal_type'] = 'pullback_weak'
                    note = '派发阶段支撑测试，供应仍可能主导，不视为买入信号'
                else:
                    signal['signal_type'] = 'support_test'
                    note = ('阶段不明，仅视为缩量回调支撑测试，'
                            '不等同于威科夫定义的LPS（缺少SC/AR/ST前置结构）')

                if spring_low is not None:
                    note += f' | LPS低点({current["Low"]:.2f}) > Spring低点({spring_low:.2f}) ✓'

                if vcp_detected:
                    note += ' | [VCP] 波动率极度收缩确认供应耗尽 ✓'
                else:
                    note += ' | 仅缩量回踩，波动尚未完全收缩'

                signal['note'] = note

                lps_signals.append(signal)

        if lps_signals:
            # ─────────────────────────────────────────────────────────────────
            # Wave 4 偏差四修正：Weis Wave 相对成交量 Effort vs Result 校验
            # 理论依据：LPS 是缩量回调，回调波多量能必须小于其前序上涨波
            # 若 LPS 回调波成交量 >= 前序上涨波，证明供应仍活跃，信号降级为 MEDIUM
            # ─────────────────────────────────────────────────────────────────
            try:
                from ..weis_wave import WeisWaveGenerator
                ww_gen = WeisWaveGenerator(df, atr_multiplier=1.5)
                waves = ww_gen.generate()
                if waves and len(waves) >= 2:
                    down_waves = [w for w in waves if w.direction == 'down']
                    up_waves = [w for w in waves if w.direction == 'up']
                    if down_waves and up_waves:
                        last_down = down_waves[-1]
                        up_waves_before = [w for w in up_waves if w.end_idx < last_down.start_idx]
                        if up_waves_before:
                            prior_up = up_waves_before[-1]
                            effort_ratio = last_down.volume / max(prior_up.volume, 1e-9)
                            for sig in lps_signals:
                                sig['weis_wave'] = {
                                    'pullback_vol': round(last_down.volume, 0),
                                    'prior_up_vol': round(prior_up.volume, 0),
                                    'effort_ratio': round(effort_ratio, 3),
                                    'low_effort': effort_ratio < 0.618,
                                }
                                if effort_ratio >= 1.0 and sig.get('confidence_score') == 'HIGH':
                                    sig['confidence_score'] = 'MEDIUM'
                                    sig['note'] = sig.get('note', '') + (
                                        f' | [Weis Wave] 回调量({last_down.volume:.0f}) >= '
                                        f'上涨量({prior_up.volume:.0f})，'
                                        '供应活跃，信号降级 ⚠️'
                                    )
                                elif effort_ratio < 0.618:
                                    sig['note'] = sig.get('note', '') + (
                                        f' | [Weis Wave] 回调量={effort_ratio:.2f}x上涨量，'
                                        '缩量回调供应耗尽 ✔️'
                                    )
                                else:
                                    sig['note'] = sig.get('note', '') + (
                                        f' | [Weis Wave] 回调量/上涨量={effort_ratio:.2f}x'
                                    )
            except Exception as _ww_err:
                logger.debug(f"[Wave4] Weis Wave LPS 校验失败 (non-critical): {_ww_err}")

            return {
                'detected': True,
                'signals': lps_signals,
                'latest': lps_signals[-1],
                'spring_low': spring_low,
                'tr_support': tr_support,
                'anchor_candidates': [
                    {'type': label, 'level': level}
                    for label, level in anchor_candidates
                ],
                'phase_context': {
                    'phase': self._current_phase or 'unknown',
                    'is_accumulation': is_accumulation,
                    'has_breakout_context': bool(breakout_dates),
                    'has_lps_qualification': (
                        is_accumulation and
                        has_complete_phase_a_structure and
                        bool(breakout_dates)
                    ),
                    'note': ('当前阶段不是标准Accumulation，'
                             '信号已按阶段上下文重新定性为"缩量回踩"而非正式LPS'
                             if not is_accumulation else None),
                },
                'phase_a_validation': phase_a_validation if is_accumulation else None
            }
        return {'detected': False}


    def detect_lpsy(
        self,
        window: int = 30,
        trading_range: Optional[Dict] = None,
        fti_result: Optional[Dict] = None,
        sow_result: Optional[Dict] = None,
    ) -> Dict:
        """
        检测 LPSY (Last Point of Supply)

        威科夫严格定义：Ice/FTI 跌破后的缩量无力反弹。
        B7: 阻力锚定 Ice 层，且需 FTI 或 SOW 前置确认。

        Args:
            window: 检测窗口
            trading_range: 当前交易区间（需包含 'low' 支撑位）
            fti_result: FTI 检测结果（提供 ice_level）
            sow_result: SOW 检测结果（FTI 缺失时的替代确认）
        """
        if self.data is None or len(self.data) < 60:
            return {'detected': False}

        df = self._ensure_columns(self.data.tail(window), ['Volume_MA20', 'MA20'])
        df_wide = self._ensure_columns(self.data, ['Volume_MA20'])
        vol_ma = df_wide['Volume_MA20'].reindex(df.index)

        # 获取 TR 支撑位（如 AR 低点）
        tr_support = None
        if trading_range and 'low' in trading_range:
            tr_support = trading_range['low']

        # B7: Ice 层作为 LPSY 阻力锚点
        ice_level = None
        fti_confirmed = False
        if fti_result and self._get_event_field(fti_result, 'detected'):
            fti_detail = self._latest_event_detail(fti_result)
            ice_level = self._numeric_value(
                self._get_event_field(fti_detail, 'ice_level') or
                self._get_event_field(fti_result, 'ice_level')
            )
            fti_confirmed = bool(
                self._get_event_field(fti_detail, 'test_detected') or
                self._get_event_field(fti_result, 'test_detected')
            )

        has_fti_context = fti_confirmed or (
            sow_result and self._get_event_field(sow_result, 'detected')
        )

        # 检查支撑是否已被有效跌破（仅检查窗口近半段，避免引用BC前历史低点）
        support_broken = False
        if tr_support is not None:
            recent_half = df.tail(max(len(df) // 2, 5))
            support_broken = recent_half['Low'].min() < tr_support
        if ice_level and ice_level > 0:
            recent_half = df.tail(max(len(df) // 2, 5))
            support_broken = support_broken or recent_half['Close'].max() < ice_level * 0.99

        signals = []
        weak_reactions = []
        for i in range(5, len(df)):
            current = df.iloc[i]

            resistance = ice_level if ice_level and ice_level > 0 else df['MA20'].iloc[i]
            is_rebound = (current['High'] > df.iloc[i-5:i]['Low'].min()) and (current['Close'] < resistance)
            low_volume = current['Volume'] < vol_ma.iloc[i] * self.thresholds.VOLUME_CONFIRMATION['weak']
            lower_high = current['High'] < df.iloc[i-20:i-5]['High'].max()

            # 新增：LPSY 的 VCP 验证
            vcp_detected = False
            window_slice = df.iloc[max(0, i-2):i+1]
            if len(window_slice) >= 3:
                bodies = (window_slice['Close'] - window_slice['Open']).abs().values
                ranges = (window_slice['High'] - window_slice['Low']).values
                price_ref = current['Close']
                is_body_shrinking = True
                for b_idx in range(len(bodies) - 1, 0, -1):
                    curr_b, prev_b = bodies[b_idx], bodies[b_idx-1]
                    if prev_b < price_ref * 0.001:
                        if not (curr_b < prev_b * 1.2):
                            is_body_shrinking = False
                            break
                    else:
                        if not (curr_b < prev_b):
                            is_body_shrinking = False
                            break
                is_tight = (bodies[-1] / max(ranges[-1], 1e-9)) < 0.3
                vcp_detected = is_body_shrinking and is_tight

            if is_rebound and low_volume and lower_high:
                signal = {
                    'date': df.index[i],
                    'price': current['Close'],
                    'volume': float(current['Volume']),
                    'volume_ratio': round(current['Volume'] / vol_ma.iloc[i], 2),
                    'resistance_level': resistance,
                    'ice_level': ice_level,
                    'vcp_detected': bool(vcp_detected),
                    'confidence_score': 'HIGH' if vcp_detected else 'MEDIUM'
                }
                if not has_fti_context:
                    signal['signal_type'] = 'weak_reaction'
                    signal['note'] = '缺少 FTI/SOW 前置确认，此为弱势反抽，非严格 LPSY'
                    weak_reactions.append(signal)
                elif tr_support is not None and not support_broken:
                    signal['signal_type'] = 'weak_reaction'
                    signal['note'] = f'支撑 {tr_support:.2f} 未被跌破，此为TR内弱势反抽，非严格LPSY'
                    weak_reactions.append(signal)
                else:
                    signal['signal_type'] = 'lpsy'
                    signals.append(signal)

        result: Dict[str, Any] = {'detected': bool(signals or weak_reactions)}
        if signals:
            result['signals'] = signals
            result['latest'] = signals[-1]
        if weak_reactions:
            result['weak_reactions'] = weak_reactions
            result['latest_weak'] = weak_reactions[-1]
        if tr_support is not None:
            result['support_level'] = tr_support
            result['support_broken'] = support_broken
        if ice_level is not None:
            result['ice_level'] = ice_level
            result['fti_confirmed'] = fti_confirmed
        return result

    def detect_choch(self) -> Dict:
        """
        特征变异 (Change of Character, CHoCH) 检测

        理论依据：趋势中出现的第一个显著的反向波段，其强度远超前序波段，标志着供求秩序的改变。

        Returns:
            {
                'detected': bool,
                'direction': 'up' | 'down',
                'thrust_ratio': float,
                'volume_ratio': float,
                'description': str
            }
        """
        from ..weis_wave import WeisWaveGenerator
        if self.data is None or len(self.data) < 40:
            return {'detected': False}

        generator = WeisWaveGenerator(self.data)
        waves = generator.generate()
        if len(waves) < 4:
            return {'detected': False}

        last_wave = waves[-1]
        # 找到前序同方向的波段进行对比
        prev_same_dir = [w for w in waves[:-1] if w.direction == last_wave.direction]
        if len(prev_same_dir) < 2:
            return {'detected': False}

        avg_thrust = np.mean([w.thrust for w in prev_same_dir[-3:]])
        avg_vol = np.mean([w.volume for w in prev_same_dir[-3:]])

        # CHoCH 判定标准：推力或成交量显著超过均值（1.5倍以上）
        thrust_ratio = last_wave.thrust / avg_thrust if avg_thrust > 0 else 1.0
        volume_ratio = last_wave.volume / avg_vol if avg_vol > 0 else 1.0

        is_choch = (thrust_ratio > 1.8) or (volume_ratio > 2.0 and thrust_ratio > 1.2)

        if is_choch:
            dir_str = "上涨" if last_wave.direction == 'up' else "下跌"
            return {
                'detected': True,
                'direction': last_wave.direction,
                'thrust_ratio': round(thrust_ratio, 2),
                'volume_ratio': round(volume_ratio, 2),
                'date': last_wave.end_idx,
                'description': f"检测到{dir_str}特征变异(CHoCH)! 波段推力是前序均值的{thrust_ratio:.1f}倍，标志着供求关系发生根本性变化。"
            }
        return {'detected': False}

    def detect_sos_variants(self) -> Dict:
        return self._detect_variants(is_bullish=True)

    def detect_sow_variants(self) -> Dict:
        return self._detect_variants(is_bullish=False)

    def _detect_variants(self, is_bullish: bool) -> Dict:
        """参数化变体检测，合并 SOS/SOW 逻辑 (P2 #8)

        修复：增加阶段上下文判断，避免在派发期将跳空上涨误判为 SOS、
        或在吸筹期将跳空下跌误判为 SOW。
        """
        if self.data is None or len(self.data) < 60:
            return {'detected': False}

        # 检查阶段上下文
        is_distribution = self._is_distribution_phase()
        is_accumulation = self._is_accumulation_phase()

        df = self.data.copy()
        df['Volume_MA20'] = df['Volume'].rolling(20).mean()
        df['Price_Change'] = df['Close'].pct_change()

        variants = []
        vol_ratio = self.thresholds.VOLUME_CONFIRMATION['strong']

        if is_bullish:
            # 在派发期，向上跳空应归类为 UT/UTAD 而非 SOS
            type_prefix = 'gap_upthrust' if is_distribution else 'gap_sos'
            # 1. 跳空缺口
            gap_mask = (df['Open'] > df['High'].shift(1) * (1 + self.thresholds.JOC_TEST_BAND)) & (df['Volume'] > df['Volume_MA20'] * vol_ratio)
            for idx in df[gap_mask].tail(3).index:
                variants.append({
                    'type': type_prefix, 'date': idx, 'price': df.loc[idx, 'Close'],
                    'strength': 'strong',
                    'phase_context': 'distribution' if is_distribution else 'accumulation_or_uptrend'
                })

            # 2. 涨停
            limit_type = 'limit_up_upthrust' if is_distribution else 'limit_up_sos'
            limit_mask = (df['Price_Change'] >= self.thresholds.LIMIT_UP_THRESHOLD) & (df['Volume'] > df['Volume_MA20'] * 1.2)
            for idx in df[limit_mask].tail(2).index:
                variants.append({
                    'type': limit_type, 'date': idx, 'price': df.loc[idx, 'Close'],
                    'strength': 'very_strong',
                    'phase_context': 'distribution' if is_distribution else 'accumulation_or_uptrend'
                })
        else:
            # 在吸筹期，向下跳空应归类为 Spring 而非 SOW
            type_prefix = 'gap_spring' if is_accumulation else 'gap_sow'
            # 1. 跳空缺口 SOW
            gap_mask = (df['Open'] < df['Low'].shift(1) * (1 - self.thresholds.JOC_TEST_BAND)) & (df['Volume'] > df['Volume_MA20'] * vol_ratio)
            for idx in df[gap_mask].tail(3).index:
                variants.append({
                    'type': type_prefix, 'date': idx, 'price': df.loc[idx, 'Close'],
                    'strength': 'strong',
                    'phase_context': 'accumulation' if is_accumulation else 'distribution_or_downtrend'
                })

            # 2. 跌停
            limit_type = 'limit_down_spring' if is_accumulation else 'limit_down_sow'
            limit_mask = (df['Price_Change'] <= self.thresholds.LIMIT_DOWN_THRESHOLD) & (df['Volume'] > df['Volume_MA20'] * 1.2)
            for idx in df[limit_mask].tail(2).index:
                variants.append({
                    'type': limit_type, 'date': idx, 'price': df.loc[idx, 'Close'],
                    'strength': 'very_strong',
                    'phase_context': 'accumulation' if is_accumulation else 'distribution_or_downtrend'
                })

        if variants:
            return {
                'detected': True,
                'variants': variants,
                'latest_variant': variants[-1],
                'overall_strength': self._calculate_strength(variants),
                'phase_context': {
                    'is_distribution': is_distribution,
                    'is_accumulation': is_accumulation
                }
            }
        return {'detected': False}

    def _calculate_strength(self, variants: List[Dict]) -> str:
        scores = {'very_strong': 3, 'strong': 2, 'moderate': 1, 'weak': 0}
        total = sum(scores.get(v.get('strength', 'weak'), 0) for v in variants)
        if total >= 5:
            return 'very_strong'
        if total >= 3:
            return 'strong'
        if total >= 1:
            return 'moderate'
        return 'weak'
