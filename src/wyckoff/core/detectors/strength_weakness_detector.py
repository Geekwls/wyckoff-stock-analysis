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
        
        sos_mask = (df['Close'] > df['Open']) & (df['Volume'] > vol_ma * vol_ratio_threshold) & (price_pct_change > price_change_threshold)
        if sos_mask.any():
            idx = df[sos_mask].index[-1]
            
            # 在吸筹阶段或上涨趋势中，才是真正的SOS
            return {
                'detected': True, 
                'type': 'sos', 
                'date': idx, 
                'price': df.loc[idx, 'Close'], 
                'volume_ratio': round(df.loc[idx, 'Volume']/vol_ma.loc[idx], 2), 
                'price_change': round(price_pct_change.loc[idx], 4), 
                'breakthrough_level': df['High'].rolling(20).max().iloc[-1],
                'phase_context': 'accumulation_or_uptrend',
                'interpretation': '吸筹阶段的强势突破，是买入信号'
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
        
        sow_mask = (df['Close'] < df['Open']) & (df['Volume'] > vol_ma * vol_ratio_threshold) & (price_pct_change < price_change_threshold)
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

    def detect_lps(self, window: int = 30) -> Dict:
        """检测 LPS (Last Point of Support)"""
        if self.data is None or len(self.data) < 60:
            return {'detected': False}
        
        df = self._ensure_columns(self.data.tail(window), ['Volume_MA20', 'MA20'])
        df_wide = self._ensure_columns(self.data, ['Volume_MA20'])
        vol_ma = df_wide['Volume_MA20'].reindex(df.index)
        
        lps_signals = []
        for i in range(5, len(df)):
            current = df.iloc[i]
            
            is_pullback = (current['Low'] < df.iloc[i-5:i]['High'].max()) and (current['Close'] > df['MA20'].iloc[i])
            low_volume = current['Volume'] < vol_ma.iloc[i] * self.thresholds.VOLUME_CONFIRMATION['weak']
            higher_low = current['Low'] > df.iloc[i-20:i-5]['Low'].min()
            
            if is_pullback and low_volume and higher_low:
                lps_signals.append({
                    'date': df.index[i],
                    'price': current['Close'],
                    'volume_ratio': round(current['Volume'] / vol_ma.iloc[i], 2),
                    'support_level': df['MA20'].iloc[i]
                })
        
        if lps_signals:
            return {'detected': True, 'signals': lps_signals, 'latest': lps_signals[-1]}
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
        
        # 检查支撑是否已被跌破（在检测窗口范围内）
        support_broken = False
        if tr_support is not None:
            support_broken = df['Low'].min() < tr_support
        
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
