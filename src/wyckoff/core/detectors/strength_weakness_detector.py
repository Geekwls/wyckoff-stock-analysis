import pandas as pd
from typing import Dict, Optional, Tuple, List, Any
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig, WyckoffThresholds

class StrengthWeaknessDetector(BaseDetector):
    """
    负责检测 SOS (Sign of Strength) 和 SOW (Sign of Weakness) 及其变体
    
    重要理论约束：
    - SOS (强势信号) 只发生在吸筹阶段末期或上涨趋势中
    - 在派发阶段，向上突破应归类为 UT (Upthrust) 或 UTAD (派发后的上冲回落)
    - 系统必须根据当前阶段动态调整信号分类
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds):
        super().__init__()
        self.data = data
        self.config = config
        self.thresholds = thresholds
    
    def _ensure_columns(self, df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """确保所需的指标列存在，缺失时动态计算"""
        df = df.copy()
        col_map = {
            'Volume_MA20': lambda d: d['Volume'].rolling(20, min_periods=1).mean(),
            'MA20': lambda d: d['Close'].rolling(20, min_periods=1).mean(),
        }
        for col in columns:
            if col not in df.columns and col in col_map:
                df[col] = col_map[col](df)
        return df

    def update_analysis_context(self, phase: str):
        """更新当前阶段，用于动态调整信号分类"""
        super().update_analysis_context(phase)
    
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
        
        关键约束：
        - SOS 只发生在吸筹阶段末期或上涨趋势中
        - 当 phase == Distribution 时，所有向上突破尝试一律归为 upthrust，不生成 sos
        - 这是解决信号混乱最根本的一刀
        """
        if self.data is None or len(self.data) < window:
            return {'detected': False}
        
        # 关键约束：在派发阶段，直接返回未检测到SOS
        # 所有向上突破尝试一律归为 upthrust，由 detect_upthrust() 处理
        if self._is_distribution_phase():
            return {'detected': False, 'reason': 'distribution_phase_no_sos'}
        
        df = self.data.tail(window).copy()
        vol_ma = df['Volume'].rolling(20).mean()
        price_pct_change = df['Close'].pct_change()
        
        # 使用配置中的阈值
        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['strong']
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
            
            return {
                'detected': True, 
                'type': 'sos', 
                'date': idx, 
                'price': df.loc[idx, 'Close'], 
                'volume_ratio': round(df.loc[idx, 'Volume']/vol_ma.loc[idx], 2), 
                'price_change': round(price_pct_change.loc[idx], 4), 
                'breakthrough_level': round(tr_high, 3),
                'breakout_type': breakout_type,
                'phase_context': 'accumulation_or_uptrend',
                'interpretation': interpretation
            }
        return {'detected': False}

    def detect_sow(self, window: int = 40) -> Dict:
        """检测标准 SOW"""
        if self.data is None or len(self.data) < window:
            return {'detected': False}
        df = self.data.tail(window).copy()
        vol_ma = df['Volume'].rolling(20).mean()
        price_pct_change = df['Close'].pct_change()
        
        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['strong']
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
            return {
                'detected': True, 
                'type': 'sow', 
                'date': idx, 
                'price': df.loc[idx, 'Close'], 
                'volume_ratio': round(df.loc[idx, 'Volume']/vol_ma.loc[idx], 2), 
                'price_change': round(price_pct_change.loc[idx], 4), 
                'breakdown_level': df['Low'].rolling(20).min().iloc[-1]
            }
        return {'detected': False}

    def detect_lps(self, window: int = 30, spring_res: Dict = None) -> Dict:
        """
        检测 LPS (Last Point of Support)

        阶段约束（新增修复）：
        - 仅在 Accumulation / Reaccumulation 阶段才标记为正式 LPS
        - Markup 阶段降级为 "pullback"（缩量回踩）
        - 阶段不明或 Distribution 降级为 "pullback_weak"（缩量回调，支撑测试）

        Args:
            window: 检测窗口
            spring_res: Spring检测结果，用于验证LPS低点>Spring低点
        """
        if self.data is None or len(self.data) < 60:
            return {'detected': False}

        # 提取 Spring 低点（若有）
        spring_low = None
        if spring_res and spring_res.get('detected'):
            sl = spring_res.get('latest_spring') or (
                spring_res.get('signals', [{}])[-1] if spring_res.get('signals') else {}
            )
            spring_low = sl.get('breakdown_price') if isinstance(sl, dict) else (
                getattr(sl, 'breakdown_price', None) if hasattr(sl, 'breakdown_price') else None
            )

        # 判断阶段上下文
        is_accumulation = self._is_accumulation_phase()
        is_markup = (self._current_phase is not None
                     and ('Markup' in self._current_phase or '上涨' in self._current_phase))
        is_distribution = self._is_distribution_phase()

        df = self._ensure_columns(self.data.tail(window), ['Volume_MA20', 'MA20'])
        df_wide = self._ensure_columns(self.data, ['Volume_MA20'])
        vol_ma = df_wide['Volume_MA20'].reindex(df.index)

        lps_signals = []
        for i in range(5, len(df)):
            current = df.iloc[i]

            is_pullback = (current['Low'] < df.iloc[i-5:i]['High'].max()) and (current['Close'] > df['MA20'].iloc[i])
            low_volume = current['Volume'] < vol_ma.iloc[i] * self.thresholds.VOLUME_CONFIRMATION['weak']
            higher_low = current['Low'] > df.iloc[i-20:i-5]['Low'].min()

            # 修复 #5: LPS 低点必须 > Spring 低点（书：回调不破Spring低点）
            if spring_low is not None and current['Low'] <= spring_low:
                continue

            if is_pullback and low_volume and higher_low:
                signal = {
                    'date': df.index[i],
                    'price': current['Close'],
                    'volume_ratio': round(current['Volume'] / vol_ma.iloc[i], 2),
                    'support_level': df['MA20'].iloc[i]
                }

                # 阶段约束：只有 Accumulation 阶段才叫 LPS
                if is_accumulation:
                    signal['signal_type'] = 'lps'
                    note = '吸筹阶段最后支撑点（LPS）'
                elif is_markup:
                    signal['signal_type'] = 'pullback'
                    note = ('上涨趋势缩量回踩（非正式LPS，因缺少SC/AR/ST吸筹前置结构；'
                            '此处定义为趋势中的正常回调支撑测试）')
                elif is_distribution:
                    signal['signal_type'] = 'pullback_weak'
                    note = '派发阶段支撑测试，供应仍可能主导，不视为买入信号'
                else:
                    signal['signal_type'] = 'pullback'
                    note = ('阶段不明，仅视为缩量回调支撑测试，'
                            '不等同于威科夫定义的LPS（缺少SC/AR/ST前置结构）')

                if spring_low is not None:
                    note += f' | LPS低点({current["Low"]:.2f}) > Spring低点({spring_low:.2f}) ✓'
                signal['note'] = note

                lps_signals.append(signal)

        if lps_signals:
            return {
                'detected': True,
                'signals': lps_signals,
                'latest': lps_signals[-1],
                'spring_low': spring_low,
                'phase_context': {
                    'phase': self._current_phase or 'unknown',
                    'is_accumulation': is_accumulation,
                    'has_lps_qualification': is_accumulation,
                    'note': ('当前阶段不是标准Accumulation，'
                             '信号已按阶段上下文重新定性为"缩量回踩"而非正式LPS'
                             if not is_accumulation else None)
                }
            }
        return {'detected': False}

    def detect_lpsy(self, window: int = 30, trading_range: Dict = None) -> Dict:
        """
        检测 LPSY (Last Point of Supply)
        
        威科夫严格定义：价格跌破关键支撑后，出现的缩量无力反弹。
        若支撑未被跌破，信号归类为"weak_reaction"而非 LPSY。
        
        Args:
            window: 检测窗口
            trading_range: 当前交易区间（需包含 'low' 支撑位）
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
        
        # 检查支撑是否已被有效跌破（仅检查窗口近半段，避免引用BC前历史低点）
        support_broken = False
        if tr_support is not None:
            recent_half = df.tail(max(len(df) // 2, 5))
            support_broken = recent_half['Low'].min() < tr_support
        
        signals = []
        weak_reactions = []
        for i in range(5, len(df)):
            current = df.iloc[i]
            
            is_rebound = (current['High'] > df.iloc[i-5:i]['Low'].min()) and (current['Close'] < df['MA20'].iloc[i])
            low_volume = current['Volume'] < vol_ma.iloc[i] * self.thresholds.VOLUME_CONFIRMATION['weak']
            lower_high = current['High'] < df.iloc[i-20:i-5]['High'].max()
            
            if is_rebound and low_volume and lower_high:
                signal = {
                    'date': df.index[i],
                    'price': current['Close'],
                    'volume': float(current['Volume']),
                    'volume_ratio': round(current['Volume'] / vol_ma.iloc[i], 2),
                    'resistance_level': df['MA20'].iloc[i]
                }
                if tr_support is not None and not support_broken:
                    signal['signal_type'] = 'weak_reaction'
                    signal['note'] = f'支撑 {tr_support:.2f} 未被跌破，此为TR内弱势反抽，非严格LPSY'
                    weak_reactions.append(signal)
                else:
                    signal['signal_type'] = 'lpsy'
                    signals.append(signal)
        
        result = {'detected': bool(signals or weak_reactions)}
        if signals:
            result['signals'] = signals
            result['latest'] = signals[-1]
        if weak_reactions:
            result['weak_reactions'] = weak_reactions
            result['latest_weak'] = weak_reactions[-1]
        if tr_support is not None:
            result['support_level'] = tr_support
            result['support_broken'] = support_broken
        return result

    def detect_sos_variants(self) -> Dict:
        return self._detect_variants(is_bullish=True)

    def detect_sow_variants(self) -> Dict:
        return self._detect_variants(is_bullish=False)

    def _detect_variants(self, is_bullish: bool) -> Dict:
        """参数化变体检测，合并 SOS/SOW 逻辑 (P2 #8)"""
        if self.data is None or len(self.data) < 60:
            return {'detected': False}
            
        df = self.data.copy()
        df['Volume_MA20'] = df['Volume'].rolling(20).mean()
        df['Price_Change'] = df['Close'].pct_change()
        
        variants = []
        vol_ratio = self.thresholds.VOLUME_CONFIRMATION['strong']
        
        if is_bullish:
            # 1. 跳空缺口 SOS
            gap_mask = (df['Open'] > df['High'].shift(1) * (1 + self.thresholds.JOC_TEST_BAND)) & (df['Volume'] > df['Volume_MA20'] * vol_ratio)
            for idx in df[gap_mask].tail(3).index:
                variants.append({'type': 'gap_sos', 'date': idx, 'price': df.loc[idx, 'Close'], 'strength': 'strong'})
            
            # 2. 涨停 SOS (LIMIT_UP_THRESHOLD)
            limit_mask = (df['Price_Change'] >= self.thresholds.LIMIT_UP_THRESHOLD) & (df['Volume'] > df['Volume_MA20'] * 1.2)
            for idx in df[limit_mask].tail(2).index:
                variants.append({'type': 'limit_up_sos', 'date': idx, 'price': df.loc[idx, 'Close'], 'strength': 'very_strong'})
        else:
            # 1. 跳空缺口 SOW
            gap_mask = (df['Open'] < df['Low'].shift(1) * (1 - self.thresholds.JOC_TEST_BAND)) & (df['Volume'] > df['Volume_MA20'] * vol_ratio)
            for idx in df[gap_mask].tail(3).index:
                variants.append({'type': 'gap_sow', 'date': idx, 'price': df.loc[idx, 'Close'], 'strength': 'strong'})
                
            # 2. 跌停 SOW
            limit_mask = (df['Price_Change'] <= self.thresholds.LIMIT_DOWN_THRESHOLD) & (df['Volume'] > df['Volume_MA20'] * 1.2)
            for idx in df[limit_mask].tail(2).index:
                variants.append({'type': 'limit_down_sow', 'date': idx, 'price': df.loc[idx, 'Close'], 'strength': 'very_strong'})

        if variants:
            return {
                'detected': True, 
                'variants': variants, 
                'latest_variant': variants[-1], 
                'overall_strength': self._calculate_strength(variants)
            }
        return {'detected': False}

    def _calculate_strength(self, variants: List[Dict]) -> str:
        scores = {'very_strong': 3, 'strong': 2, 'moderate': 1, 'weak': 0}
        total = sum(scores.get(v.get('strength', 'weak'), 0) for v in variants)
        if total >= 5: return 'very_strong'
        if total >= 3: return 'strong'
        if total >= 1: return 'moderate'
        return 'weak'
