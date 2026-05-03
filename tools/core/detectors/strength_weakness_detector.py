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
        
        # 使用配置中的阈值
        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['strong']
        price_change_threshold = 0.02 # TODO: 迁移至 thresholds
        
        sos_mask = (df['Close'] > df['Open']) & (df['Volume'] > vol_ma * vol_ratio_threshold) & (df['Close'].pct_change() > price_change_threshold)
        if sos_mask.any():
            idx = df[sos_mask].index[-1]
            return {
                'detected': True, 
                'type': 'sos', 
                'date': idx, 
                'price': df.loc[idx, 'Close'], 
                'volume_ratio': round(df.loc[idx, 'Volume']/vol_ma.loc[idx], 2), 
                'price_change': round(df.loc[idx, 'Close'].pct_change(), 4), 
                'breakthrough_level': df['High'].rolling(20).max().iloc[-1]
            }
        return {'detected': False}

    def detect_sow(self, window: int = 40) -> Dict:
        """检测标准 SOW"""
        if self.data is None or len(self.data) < window:
            return {'detected': False}
        df = self.data.tail(window).copy()
        vol_ma = df['Volume'].rolling(20).mean()
        
        vol_ratio_threshold = self.thresholds.VOLUME_CONFIRMATION['strong']
        price_change_threshold = -0.02
        
        sow_mask = (df['Close'] < df['Open']) & (df['Volume'] > vol_ma * vol_ratio_threshold) & (df['Close'].pct_change() < price_change_threshold)
        if sow_mask.any():
            idx = df[sow_mask].index[-1]
            return {
                'detected': True, 
                'type': 'sow', 
                'date': idx, 
                'price': df.loc[idx, 'Close'], 
                'volume_ratio': round(df.loc[idx, 'Volume']/vol_ma.loc[idx], 2), 
                'price_change': round(df.loc[idx, 'Close'].pct_change(), 4), 
                'breakdown_level': df['Low'].rolling(20).min().iloc[-1]
            }
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
