import logging
import pandas as pd
from typing import Dict, Any, Optional
from .stock_data_provider import StockDataProvider

logger = logging.getLogger(__name__)

class MarketBreadthAnalyzer:
    """
    市场广度分析器 (v2.6.0 P1)
    用于识别“虚假多头”行情，通过全市场涨跌分布 (ADR) 评估指数强度。
    """
    
    @staticmethod
    def get_current_breadth_sh_sz() -> Dict[str, Any]:
        """
        获取 A 股全市场当前广度 (基于 ADR)
        
        Returns:
            Dict containing:
            - adr: 涨跌比 (Advance/Decline)
            - advance_count: 上涨家数
            - decline_count: 下跌家数
            - status: 广度评价 (Healthy, Neutral, Narrow, etc.)
        """
        try:
            # 获取实时全 A 股数据
            df = StockDataProvider.get_all_a_shares_with_info()
            if df is None or df.empty:
                return {"status": "UNKNOWN", "reason": "无法获取市场全景数据"}
            
            # 计算涨跌分布
            advances = len(df[df['pct_change'] > 0])
            declines = len(df[df['pct_change'] < 0])
            unchanged = len(df[df['pct_change'] == 0])
            total = len(df)
            
            # 防止除零
            safe_declines = max(declines, 1)
            adr = advances / safe_declines
            
            # 计算上涨家数占比
            advance_ratio = (advances / total * 100) if total > 0 else 0
            
            # 状态判定
            status = "NEUTRAL"
            if adr > 1.5:
                status = "HEALTHY"
            elif adr < 0.6:
                status = "FEARFUL"
            
            # 特殊警告：二八行情检测 (指数由少数权重拉升，大多数股票下跌)
            # 这通常通过 ADR 与 指数涨幅对比来判定 (在 ContextAnalyzer 中实现)
            
            return {
                "adr": round(adr, 2),
                "advance_count": advances,
                "decline_count": declines,
                "unchanged_count": unchanged,
                "advance_ratio_pct": round(advance_ratio, 1),
                "total_stocks": total,
                "status": status,
                "timestamp": pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')
            }
            
        except Exception as e:
            logger.warning(f"获取市场广度数据失败: {e}")
            return {"status": "UNKNOWN", "reason": str(e)}

    @staticmethod
    def analyze_market_internal_resonance(index_change_pct: float, breadth_data: Dict) -> Dict[str, Any]:
        """
        分析市场内部共振 (指数与广度对比)
        
        Args:
            index_change_pct: 基准指数当日前后变动百分比
            breadth_data: get_current_breadth_sh_sz 返回的字典
            
        Returns:
            Dict containing:
            - alignment: "ALIGNED" (共振), "DIVERGENT" (背离)
            - warning: 具体的警告信息 (如 "二八行情", "虚假拉升")
        """
        if breadth_data.get('status') == 'UNKNOWN':
            return {"alignment": "UNKNOWN"}
            
        adr = breadth_data.get('adr', 1.0)
        advance_ratio = breadth_data.get('advance_ratio_pct', 50.0)
        
        alignment = "ALIGNED"
        warning = None
        
        # 1. 虚假上涨 (Index up, Breadth down)
        if index_change_pct > 0.5 and adr < 0.8:
            alignment = "DIVERGENT"
            warning = "【虚假强势】指数上涨但涨跌比(ADR)低于0.8，呈现典型的'二八行情'，赚钱效应极差。"
        
        # 2. 指数诱多 (Index stable/up, Breadth bleeding)
        elif index_change_pct >= -0.2 and advance_ratio < 30:
            alignment = "DIVERGENT"
            warning = "【内部溃散】市场广度严重恶化，上涨家数不足30%，警惕指数补跌。"
            
        # 3. 恐慌背离 (Index down, Breadth showing strength)
        elif index_change_pct < -1.0 and adr > 1.2:
            alignment = "DIVERGENT"
            warning = "【护盘/背离】指数大跌但上涨家数占比尚可，可能存在护盘力量或局部活跃。"

        return {
            "alignment": alignment,
            "warning": warning,
            "adr_raw": adr
        }
