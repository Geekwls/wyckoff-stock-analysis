"""
威科夫分析系统 - 市场情绪 + 水温分析器

整合 VIX、大盘均线排列、全市场广度，输出五大水温分类：
- RISK_ON      → 多头环境，可积极做多
- NEUTRAL      → 中性，按个股结构操作
- RISK_OFF     → 防御，收紧仓位
- CRASH        → 恐慌，停止开仓
- PANIC_REPAIR → 超跌反弹窗口
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)

# 五大 water temperature regime
REGIME_LABELS = {
    "RISK_ON": "风险偏好多头",
    "NEUTRAL": "中性震荡",
    "RISK_OFF": "防御收缩",
    "CRASH": "恐慌危机",
    "PANIC_REPAIR": "超跌修复",
}

REGIME_GUIDANCE = {
    "RISK_ON": "大盘均线多头排列，VIX 低位，市场情绪积极。可积极参与趋势行情，持股容忍度可适当放宽。",
    "NEUTRAL": "大盘方向不明，VIX 中性。以个股结构为准，降低仓位预期，严格止损。",
    "RISK_OFF": "大盘走弱或波动上升，防御为主。收紧仓位，只参与最强结构的个股，严控止损。",
    "CRASH": "大盘快速下跌，恐慌情绪蔓延。停止一切开仓，减仓观望。",
    "PANIC_REPAIR": "市场经历恐慌后出现超跌反弹窗口。可轻仓参与最强结构的超跌反弹，快进快出。",
}


class SentimentAnalyzer:
    """
    市场情绪分析器
    整合VIX、大盘均线排列等指标评估市场水温
    """
    
    VIX_THRESHOLDS = {
        'extreme_fear': 30,
        'fear': 22,
        'greed': 15,
    }
    
    IMPLICATIONS = {
        'extreme_fear': "大盘处于极度恐慌或剧烈波动环境，技术信号极易失效",
        'fear': "大盘恐慌情绪上升，警惕向下突破或大幅震荡",
        'greed': "大盘波动极低，多头环境良好或处于温水煮青蛙的赶顶期",
        'neutral': "大盘情绪平稳，个股的技术信号和形态的有效性较高",
    }
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._is_us_market = not (symbol.startswith('sh.') or symbol.startswith('sz.') or symbol.endswith('.HK'))
        self._is_hk_market = symbol.endswith('.HK')
    
    def analyze(self, index_data: Optional[pd.DataFrame] = None, index_symbol: str = "") -> Dict[str, Any]:
        """
        分析市场情绪 + 水温分类
        """
        try:
            current_vix, benchmark_used = self._fetch_vix()
            is_realized_vol = False
            
            if current_vix is None and index_data is not None and len(index_data) >= 20:
                current_vix, benchmark_used = self._calculate_realized_volatility(index_data, index_symbol)
                is_realized_vol = True
            
            sentiment = self._classify_sentiment(current_vix) if current_vix else "unknown"
            implication = self.IMPLICATIONS.get(sentiment, "无法判断")
            
            # 水温分类（基于均线排列 + VIX/已实现波动率）
            regime = "NEUTRAL"
            if index_data is not None and len(index_data) >= 60:
                regime = self._classify_regime(index_data, current_vix, is_realized_vol)
            
            return {
                "market_sentiment": sentiment,
                "vix_level": round(current_vix, 2) if current_vix else None,
                "implication": implication,
                "benchmark_used": benchmark_used or "",
                "regime": regime,
                "regime_label": REGIME_LABELS.get(regime, "未知"),
                "regime_guidance": REGIME_GUIDANCE.get(regime, ""),
            }
        except Exception as e:
            logger.warning("获取市场情绪数据失败: %s", e)
            return {"market_sentiment": "unknown", "vix_level": None, "implication": "获取情绪数据失败", "regime": "NEUTRAL"}

    def _classify_regime(self, index_data: pd.DataFrame, vix: Optional[float], 
                         is_realized_vol: bool = False) -> str:
        """
        五大水温分类。
        
        判断逻辑（按优先级）：
        1. CRASH: 指数近 5 日跌幅 > 5% 且 VIX > 30（或已实现波动率 > 50）
        2. PANIC_REPAIR: 近 20 日最低至今反弹 < 5%，但之前曾跌超 8%
        3. RISK_ON: MA20 > MA50 > MA200 多头排列 + VIX < 18
        4. RISK_OFF: MA20 < MA50 或 MA50 < MA200 空头排列 + VIX > 20
        5. NEUTRAL: 其余
        
        Args:
            index_data: 指数数据
            vix: VIX 值或已实现波动率
            is_realized_vol: 是否为已实现波动率（A 股使用）
        """
        close = index_data['Close']
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        last_close = close.iloc[-1]
        
        if pd.isna(ma20) or pd.isna(ma50):
            return "NEUTRAL"
        
        # 已实现波动率阈值（比 VIX 高，因为历史波动率通常更高）
        crash_threshold = 50 if is_realized_vol else 30
        fear_threshold = 35 if is_realized_vol else 22
        greed_threshold = 20 if is_realized_vol else 15
        
        # CRASH check
        recent_5d = close.tail(5)
        if len(recent_5d) >= 5:
            ret_5d = (recent_5d.iloc[-1] / recent_5d.iloc[0] - 1) * 100
            if ret_5d < -5 and vix and vix > crash_threshold:
                return "CRASH"
        
        # PANIC_REPAIR check
        low_20d = close.tail(20).min()
        if low_20d > 0:
            rebound = (last_close / low_20d - 1) * 100
            max_drop_20d = (low_20d / close.tail(20).max() - 1) * 100
            if max_drop_20d < -8 and rebound < 5:
                return "PANIC_REPAIR"
        
        # RISK_ON
        if pd.notna(ma200):
            if ma20 > ma50 > ma200 and last_close > ma20:
                if vix is None or vix < greed_threshold:
                    return "RISK_ON"
                return "NEUTRAL"
        
        # RISK_OFF
        if pd.notna(ma200):
            if ma20 < ma50 < ma200 and last_close < ma20:
                if vix and vix > fear_threshold:
                    return "RISK_OFF"
                return "NEUTRAL"
        
        if pd.notna(ma200) and ma20 < ma50:
            return "RISK_OFF"
        
        return "NEUTRAL"
    
    def _fetch_vix(self) -> tuple[Optional[float], str]:
        try:
            import yfinance as yf
            if self._is_us_market:
                vix = yf.download('^VIX', period='5d', progress=False)
                if not vix.empty:
                    last_close = vix['Close'].iloc[-1]
                    if isinstance(last_close, pd.Series):
                        last_close = last_close.iloc[0] if len(last_close) > 0 else None
                    if last_close is not None and not pd.isna(last_close):
                        return float(last_close), '^VIX (CBOE Implied Volatility)'
            elif self._is_hk_market:
                vhsi = yf.download('^VHSI', period='5d', progress=False)
                if not vhsi.empty:
                    last_close = vhsi['Close'].iloc[-1]
                    if isinstance(last_close, pd.Series):
                        last_close = last_close.iloc[0] if len(last_close) > 0 else None
                    if last_close is not None and not pd.isna(last_close):
                        return float(last_close), '^VHSI (HSI Implied Volatility)'
            return None, ""
        except Exception as e:
            logger.debug("获取VIX失败: %s", e)
            return None, ""
    
    def _calculate_realized_volatility(self, data: pd.DataFrame, index_symbol: str) -> tuple[Optional[float], str]:
        try:
            returns = data['Close'].pct_change().dropna()
            if len(returns) < 20:
                return None, ""
            volatility = returns.rolling(20).std().iloc[-1] * np.sqrt(252) * 100
            if pd.isna(volatility):
                return None, ""
            return float(volatility), f'{index_symbol} (20-day Realized Volatility)'
        except Exception as e:
            logger.debug("计算波动率失败: %s", e)
            return None, ""
    
    def _classify_sentiment(self, vix_level: float) -> str:
        if vix_level >= self.VIX_THRESHOLDS['extreme_fear']:
            return 'extreme_fear'
        elif vix_level >= self.VIX_THRESHOLDS['fear']:
            return 'fear'
        elif vix_level <= self.VIX_THRESHOLDS['greed']:
            return 'greed'
        return 'neutral'
