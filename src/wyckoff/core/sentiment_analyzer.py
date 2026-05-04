"""
威科夫分析系统 - 市场情绪分析器
从report_generator.py中提取，负责市场情绪指标分析
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """
    市场情绪分析器
    整合VIX、历史波动率等指标评估市场情绪
    """
    
    # 情绪评级阈值
    VIX_THRESHOLDS = {
        'extreme_fear': 30,
        'fear': 22,
        'greed': 15
    }
    
    # 情绪含义映射
    IMPLICATIONS = {
        'extreme_fear': "大盘处于极度恐慌或剧烈波动环境，技术信号极易失效（暴涨暴跌），建议严控仓位",
        'fear': "大盘恐慌情绪上升，警惕向下突破或大幅震荡",
        'greed': "大盘波动极低，多头环境良好或处于温水煮青蛙的赶顶期，需防范高位诱多",
        'neutral': "大盘情绪平稳，个股的技术信号和形态的有效性较高"
    }
    
    def __init__(self, symbol: str):
        """
        初始化情绪分析器
        
        Args:
            symbol: 股票代码
        """
        self.symbol = symbol
        self._is_us_market = not (symbol.startswith('sh.') or symbol.startswith('sz.') or symbol.endswith('.HK'))
        self._is_hk_market = symbol.endswith('.HK')
    
    def analyze(self, index_data: Optional[pd.DataFrame] = None, index_symbol: str = "") -> Dict[str, Any]:
        """
        分析市场情绪
        
        Args:
            index_data: 大盘指数数据（可选）
            index_symbol: 大盘指数代码
            
        Returns:
            市场情绪分析结果
        """
        try:
            # 1. 尝试获取VIX/VHSI
            current_vix, benchmark_used = self._fetch_vix()
            
            # 2. 如果获取不到，使用大盘历史波动率
            if current_vix is None:
                if index_data is None or len(index_data) < 20:
                    return {"market_sentiment": "unknown", "vix_level": None, "implication": "无法获取大盘数据计算情绪"}
                current_vix, benchmark_used = self._calculate_realized_volatility(index_data, index_symbol)
            
            if current_vix is None:
                return {"market_sentiment": "unknown", "vix_level": None, "implication": "波动率计算失败"}
            
            # 3. 评级
            sentiment = self._classify_sentiment(current_vix)
            implication = self.IMPLICATIONS[sentiment]
            
            return {
                "market_sentiment": sentiment,
                "vix_level": round(current_vix, 2),
                "implication": implication,
                "benchmark_used": benchmark_used
            }
        except Exception as e:
            logger.warning("获取市场情绪数据失败: %s", e)
            return {"market_sentiment": "unknown", "vix_level": None, "implication": "获取情绪数据失败"}
    
    def _fetch_vix(self) -> tuple[Optional[float], str]:
        """
        获取VIX/VHSI指数
        
        Returns:
            (VIX值, 基准名称) 或 (None, "")
        """
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
        """
        计算历史实现波动率
        
        Args:
            data: 指数数据
            index_symbol: 指数代码
            
        Returns:
            (波动率值, 基准名称) 或 (None, "")
        """
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
        """
        根据VIX水平分类情绪
        
        Args:
            vix_level: VIX值
            
        Returns:
            情绪分类
        """
        if vix_level >= self.VIX_THRESHOLDS['extreme_fear']:
            return 'extreme_fear'
        elif vix_level >= self.VIX_THRESHOLDS['fear']:
            return 'fear'
        elif vix_level <= self.VIX_THRESHOLDS['greed']:
            return 'greed'
        else:
            return 'neutral'
