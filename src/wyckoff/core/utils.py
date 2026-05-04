import pandas as pd
from typing import Dict, List, Optional, Union
from .enums import WyckoffPhase, MarketSide

class PhaseAdapter:
    """负责解析和分类阶段（支持 Enum 和 String，实现双轨期兼容）"""
    
    @staticmethod
    def is_accumulation(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return 'Accumulation' in p_str or '建仓' in p_str or phase == WyckoffPhase.PHASE_A or phase == WyckoffPhase.PHASE_B
        
    @staticmethod
    def is_distribution(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return 'Distribution' in p_str or '出货' in p_str
        
    @staticmethod
    def is_markup(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return 'Markup' in p_str or '上涨' in p_str or phase == WyckoffPhase.PHASE_E
        
    @staticmethod
    def is_markdown(phase: Union[str, WyckoffPhase]) -> bool:
        p_str = str(phase)
        return 'Markdown' in p_str or '下跌' in p_str

    @staticmethod
    def is_entry_phase(phase: Union[str, WyckoffPhase]) -> bool:
        """判断是否为可入场阶段 (C/D)"""
        if isinstance(phase, WyckoffPhase):
            return phase in [WyckoffPhase.PHASE_C, WyckoffPhase.PHASE_D]
        p_str = str(phase)
        return 'Phase C' in p_str or 'Phase D' in p_str

    @staticmethod
    def get_market_side(phase: Union[str, WyckoffPhase]) -> str:
        """返回买方(bullish)或卖方(bearish)市场侧"""
        if PhaseAdapter.is_accumulation(phase) or PhaseAdapter.is_markup(phase):
            return MarketSide.BULLISH.value
        if PhaseAdapter.is_distribution(phase) or PhaseAdapter.is_markdown(phase):
            return MarketSide.BEARISH.value
        return MarketSide.NEUTRAL.value

# 为了兼容性，保留 PhaseClassifier 别名
PhaseClassifier = PhaseAdapter
