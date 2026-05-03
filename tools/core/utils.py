import pandas as pd
from typing import Dict, List, Optional

class PhaseClassifier:
    """负责解析和分类阶段字符串"""
    
    @staticmethod
    def is_accumulation(phase_str: str) -> bool:
        return 'Accumulation' in phase_str or '建仓' in phase_str
        
    @staticmethod
    def is_distribution(phase_str: str) -> bool:
        return 'Distribution' in phase_str or '出货' in phase_str
        
    @staticmethod
    def is_markup(phase_str: str) -> bool:
        return 'Markup' in phase_str or '上涨' in phase_str
        
    @staticmethod
    def is_markdown(phase_str: str) -> bool:
        return 'Markdown' in phase_str or '下跌' in phase_str

    @staticmethod
    def get_market_side(phase_str: str) -> str:
        """返回买方(bullish)或卖方(bearish)市场侧"""
        if PhaseClassifier.is_accumulation(phase_str) or PhaseClassifier.is_markup(phase_str):
            return "bullish"
        if PhaseClassifier.is_distribution(phase_str) or PhaseClassifier.is_markdown(phase_str):
            return "bearish"
        return "neutral"
