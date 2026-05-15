import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class VolumeContextAnalyzer:
    """
    成交量相对强度 (Relative Volume Strength, RVS) 分析器 (P2 #5)
    理论依据：同样的放量/缩量，必须在大盘背景下解读才有意义。
    """
    
    @staticmethod
    def calculate_rvs(stock_df: pd.DataFrame, market_df: Optional[pd.DataFrame] = None, industry_dfs: Optional[Dict[str, pd.DataFrame]] = None) -> Dict:
        """
        计算相对量能强度
        
        Args:
            stock_df: 个股数据
            market_df: 指数数据 (可选)
            industry_dfs: 同行业其他个股数据 (用于降级方案)
            
        Returns:
            RVS 分析结果
        """
        if len(stock_df) < 5:
            return {"status": "insufficient_data"}
            
        # 计算个股近期量能变化 (5日均量 vs 20日均量)
        stock_vol_5 = stock_df['Volume'].tail(5).mean()
        stock_vol_20 = stock_df['Volume'].tail(20).mean()
        stock_vol_ratio = stock_vol_5 / max(stock_vol_20, 1e-9)
        
        comparison_ratio = 1.0
        method = "none"
        
        # 优先使用大盘指数
        if market_df is not None and len(market_df) >= 20:
            market_vol_5 = market_df['Volume'].tail(5).mean()
            market_vol_20 = market_df['Volume'].tail(20).mean()
            comparison_ratio = market_vol_5 / max(market_vol_20, 1e-9)
            method = "market_index"
        # 降级方案：同行业中位数 (P2 #5)
        elif industry_dfs and len(industry_dfs) >= 3:
            industry_ratios = []
            for sym, df in industry_dfs.items():
                if len(df) >= 20:
                    v5 = df['Volume'].tail(5).mean()
                    v20 = df['Volume'].tail(20).mean()
                    industry_ratios.append(v5 / max(v20, 1e-9))
            if industry_ratios:
                comparison_ratio = np.median(industry_ratios)
                method = "industry_median"
        
        # 计算相对强度
        rvs_score = stock_vol_ratio / max(comparison_ratio, 1e-9)
        
        if rvs_score > 1.5:
            label = "强 (独立放量)"
            meaning = "个股量能显著强于大盘/行业，资金活跃度极高，可能存在独立行情。"
        elif rvs_score > 1.2:
            label = "较强"
            meaning = "量能稳步走强，优于市场平均水平。"
        elif rvs_score < 0.7:
            label = "弱 (独立缩量)"
            meaning = "市场活跃时个股缩量，反映资金关注度不足，缺乏进攻动能。"
        else:
            label = "中性"
            meaning = "量能变化与市场节奏基本同步。"
            
        return {
            "status": "ok",
            "rvs_score": round(float(rvs_score), 2),
            "stock_vol_ratio": round(float(stock_vol_ratio), 2),
            "market_vol_ratio": round(float(comparison_ratio), 2),
            "method": method,
            "label": label,
            "meaning": meaning
        }
