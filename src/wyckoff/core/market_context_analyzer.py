import logging
import pandas as pd
from typing import Dict, Any, Optional
from .enums import MarketEnvironment
from .laws.effort_result import EffortResultMixin
from .market_breadth_analyzer import MarketBreadthAnalyzer
from .point_and_figure import calculate_cause_effect_from_pnf

logger = logging.getLogger(__name__)

class IndexEVRAnalyzer(EffortResultMixin):
    """
    用于指数的努力vs结果分析器
    复用 EffortResultMixin 的核心逻辑。
    """
    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.pattern_detector = None
    
    def _get_current_phase_context(self) -> str:
        return "Market Index"
    
    def _phase_context_tail(self, phase: str, interpretation: str) -> str:
        return ""
    
    def _add_weekly_resonance_to_evr(self, daily_analysis: dict):
        # 指数暂不进行复杂的周线共振
        pass
    
    def _analyze_volume_health_context(self) -> dict:
        return {}
    
    def _analyze_signal_follow_through(self) -> dict:
        return {}
    
    def _detect_vsa_anomalies(self) -> dict:
        return {}

class MarketContextAnalyzer:
    """
    专家级市场环境分析器 (v2.6.0 P0 优化)
    整合均线排列、成交量能量 (EVR) 和量比分析。
    """
    
    def __init__(self, index_data: pd.DataFrame, index_symbol: str):
        self.data = index_data
        self.symbol = index_symbol
        self.evr_analyzer = IndexEVRAnalyzer(index_data)

    def analyze(self) -> Dict[str, Any]:
        """执行全面环境分析"""
        if self.data is None or len(self.data) < 20:
            return {
                "environment": MarketEnvironment.UNKNOWN, 
                "reason": "数据不足",
                "index_symbol": self.symbol
            }

        # 1. 基础均线分析
        ma_info = self._get_ma_alignment()
        base_env = ma_info['environment']

        # 2. 成交量能量 (EVR) 分析 (P0 核心增强)
        evr_info = self._get_volume_energy()
        
        # 3. 市场广度 (Market Breadth) 分析 (P1 增强)
        breadth_info = self._get_market_breadth()
        
        # 4. 点数图 (P&F) 因果测算 (P2 增强)
        pf_info = self._get_pf_targets()
        
        # 5. 逻辑联动：修正环境标签 (P0 + P1 + P2 核心逻辑)
        refined_env, refined_desc = self._refine_environment(base_env, ma_info['description'], evr_info, breadth_info)
        
        return {
            "environment": refined_env,
            "description": refined_desc,
            "trend_strength": ma_info['trend_strength'],
            "index_symbol": self.symbol,
            "current_price": ma_info['current_price'],
            "ma_alignment": ma_info,
            "volume_energy": evr_info,
            "breadth": breadth_info,
            "pf_targets": pf_info,
            "warning": self._consolidate_warnings(evr_info, breadth_info)
        }

    def _consolidate_warnings(self, evr_info: Dict, breadth_info: Dict) -> Optional[str]:
        """合并多个维度的警告信息"""
        warnings = []
        if evr_info.get('warning'):
            warnings.append(evr_info['warning'])
        if breadth_info.get('warning'):
            warnings.append(breadth_info['warning'])
        
        return " | ".join(warnings) if warnings else None

    def _get_market_breadth(self) -> Dict:
        """获取市场广度信息 (P1)
        
        注意：单股分析时默认跳过，因为获取全 A 股数据耗时较长（60+秒）
        仅在批量扫描或明确要求时启用
        """
        # 单股分析默认跳过市场广度
        return {"status": "SKIPPED", "reason": "单股分析默认跳过（耗时较长）"}

    def _get_pf_targets(self) -> Dict:
        """计算大盘 P&F 目标 (P2)"""
        try:
            # 大盘通常使用 1.0% 的箱体大小 (保守)
            pf_res = calculate_cause_effect_from_pnf(self.data, box_size_pct=1.0)
            return pf_res
        except Exception as e:
            logger.debug(f"Index P&F target calculation failed: {e}")
            return {"status": "UNKNOWN", "reason": str(e)}

    def _get_ma_alignment(self) -> Dict:
        """获取指数均线排列状态"""
        close = self.data['Close']
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        
        # 兜底处理：如果数据少于200天，MA200设为None
        ma200 = None
        if len(self.data) >= 200:
            ma200 = close.rolling(200).mean().iloc[-1]
            
        current_price = close.iloc[-1]
        
        # 多头排列：MA20 > MA50 (> MA200)
        if ma20 > ma50 and (ma200 is None or ma50 > ma200) and current_price > ma20:
            env = MarketEnvironment.STRONG_BULL
            desc = "多头排列：均线系统向上"
            strength = "strong"
        elif ma20 > ma50:
            env = MarketEnvironment.WEAK_BULL
            desc = "弱势多头：短期均线向上"
            strength = "weak"
        elif ma20 < ma50 and (ma200 is None or ma50 < ma200) and current_price < ma20:
            env = MarketEnvironment.STRONG_BEAR
            desc = "空头排列：均线系统向下"
            strength = "strong"
        elif ma20 < ma50:
            env = MarketEnvironment.BEAR
            desc = "弱势空头：短期均线向下"
            strength = "weak"
        else:
            env = MarketEnvironment.RANGE_BOUND
            desc = "震荡整理：方向不明"
            strength = "neutral"
            
        return {
            "environment": env,
            "description": desc,
            "trend_strength": strength,
            "current_price": round(float(current_price), 2),
            "ma20": round(float(ma20), 2),
            "ma50": round(float(ma50), 2),
            "ma200": round(float(ma200), 2) if ma200 else None,
            "price_vs_ma200_pct": round(((current_price - ma200) / ma200 * 100), 2) if ma200 else None
        }

    def _get_volume_energy(self) -> Dict:
        """计算指数的努力vs结果"""
        try:
            evr_result = self.evr_analyzer.analyze_effort_vs_result_law()
            short_tf = evr_result.get('timeframe_analysis', {}).get('short', {})
            interpretation = short_tf.get('interpretation', 'NORMAL')
            
            # 计算波段量能比 (5日总量 vs 历史均值)
            vol_ratio = short_tf.get('volume_effort', 1.0)
            price_change = short_tf.get('price_result', 0)
            
            warning = None
            
            # P0 增强逻辑：针对指数优化背离阈值
            # 1. 缩量上涨检测 (对于指数，vol_ratio < 0.8 已经是显著萎缩)
            if interpretation == 'NORMAL' and vol_ratio < 0.8 and price_change > 1.0:
                interpretation = 'RESULT_WITHOUT_EFFORT'
                warning = "指数上涨但成交量显著萎缩，存在量价背离风险 (Demand Exhaustion)"
            
            # 2. 已由基础逻辑识别出的背离
            elif interpretation == 'RESULT_WITHOUT_EFFORT' and price_change > 0.5:
                warning = "指数上涨但成交量萎缩，警惕多头动能衰减"
            
            # 3. 努力无结果检测 (放量滞涨)
            elif interpretation == 'EFFORT_WITHOUT_RESULT' and abs(price_change) < 1.0:
                warning = "指数放量滞涨，警惕供应正在吸收需求 (Stopping Volume / Absorption)"

            return {
                "interpretation": interpretation,
                "vol_ratio": round(vol_ratio, 2),
                "price_result_pct": round(price_change, 2),
                "meaning": short_tf.get('meaning', ""),
                "warning": warning
            }
        except Exception as e:
            logger.debug(f"Index EVR analysis skipped: {e}")
            return {"interpretation": "UNKNOWN", "vol_ratio": 1.0}

    def _refine_environment(self, base_env: MarketEnvironment, base_desc: str, evr_info: Dict, breadth_info: Dict = None) -> tuple:
        """基于量价能量和市场广度修正环境标签"""
        refined_env = base_env
        refined_desc = base_desc
        breadth_info = breadth_info or {}
        
        interp = evr_info.get('interpretation')
        vol_ratio = evr_info.get('vol_ratio', 1.0)
        breadth_align = breadth_info.get('alignment')
        
        # 1. 多头环境修正
        if base_env == MarketEnvironment.STRONG_BULL:
            # 量价背离修正
            if interp == 'RESULT_WITHOUT_EFFORT':
                refined_env = MarketEnvironment.WEAK_BULL
                refined_desc += " | ⚠️ 警告：缩量上涨，需求不足"
            
            # 市场广度背离修正 (P1)
            if breadth_align == 'DIVERGENT':
                refined_env = MarketEnvironment.WEAK_BULL
                refined_desc += " | ⚠️ 警告：广度背离 (Narrow Market)"
                
            elif vol_ratio > 1.3 and breadth_align == 'ALIGNED':
                refined_desc += " | ✅ 深度共振：量价与广度同步向好"
        
        # 2. 空头环境修正
        elif base_env in (MarketEnvironment.BEAR, MarketEnvironment.STRONG_BEAR):
            if interp == 'RESULT_WITHOUT_EFFORT' or vol_ratio < 0.7:
                # 缩量下跌是典型的供应枯竭前兆
                refined_desc += " | ⏳ 警示：缩量下跌，供应趋于枯竭 (Potential Bottom)"
            elif vol_ratio > 1.5:
                refined_desc += " | ❌ 警告：放量下跌，抛售压力巨大"
                
        return refined_env, refined_desc
