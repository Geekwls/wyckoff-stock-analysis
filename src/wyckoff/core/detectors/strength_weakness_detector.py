import pandas as pd
from typing import Dict, List, Optional, Any
from ...config.settings import WyckoffConfig, WyckoffThresholds

class StrengthWeaknessDetector:
    """负责检测 SOS (Sign of Strength) 和 SOW (Sign of Weakness) 及其变体"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds):
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect_sos(self, window: int = 40) -> Dict:
        """检测标准 SOS"""
        if self.data is None or len(self.data) < window:
            return {'detected': False}
        df = self.data.tail(window).copy()
        vol_ma = df['Volume'].rolling(20).mean()
        price_pct_change = df['Close'].pct_change()
        
        # 使用配置中的阈值
        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['strong']
        price_change_threshold = self.thresholds.SOS_PRICE_CHANGE_DEFAULT
        
        sos_mask = (df['Close'] > df['Open']) & (df['Volume'] > vol_ma * vol_ratio_threshold) & (price_pct_change > price_change_threshold)
        if sos_mask.any():
            idx = df[sos_mask].index[-1]
            return {
                'detected': True, 
                'type': 'sos', 
                'date': idx, 
                'price': df.loc[idx, 'Close'], 
                'volume_ratio': round(df.loc[idx, 'Volume']/vol_ma.loc[idx], 2), 
                'price_change': round(price_pct_change.loc[idx], 4), 
                'breakthrough_level': df['High'].rolling(20).max().iloc[-1]
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
        
        df = self.data.tail(window).copy()
        vol_ma = self.data['Volume_MA20'].reindex(df.index)
        
        # 逻辑：价格在 MA20 之上，且回踩缩量，低点抬高
        lps_signals = []
        for i in range(5, len(df)):
            current = df.iloc[i]
            
            # 回调缩量条件
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

    def detect_lpsy(self, window: int = 30) -> Dict:
        """检测 LPSY (Last Point of Supply)"""
        if self.data is None or len(self.data) < 60:
            return {'detected': False}
            
        df = self.data.tail(window).copy()
        vol_ma = self.data['Volume_MA20'].reindex(df.index)
        
        lpsy_signals = []
        for i in range(5, len(df)):
            current = df.iloc[i]
            
            # 逻辑：价格在 MA20 之下，反弹无力（缩量），高点降低
            is_rebound = (current['High'] > df.iloc[i-5:i]['Low'].min()) and (current['Close'] < df['MA20'].iloc[i])
            low_volume = current['Volume'] < vol_ma.iloc[i] * self.thresholds.VOLUME_CONFIRMATION['weak']
            lower_high = current['High'] < df.iloc[i-20:i-5]['High'].max()
            
            if is_rebound and low_volume and lower_high:
                lpsy_signals.append({
                    'date': df.index[i],
                    'price': current['Close'],
                    'volume_ratio': round(current['Volume'] / vol_ma.iloc[i], 2),
                    'resistance_level': df['MA20'].iloc[i]
                })
                
        if lpsy_signals:
            return {'detected': True, 'signals': lpsy_signals, 'latest': lpsy_signals[-1]}
        return {'detected': False}

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
