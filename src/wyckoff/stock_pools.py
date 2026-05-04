#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析系统 - 预定义数据池
Wyckoff Analysis - Predefined Stock Pools

注：原来的 WyckoffScreener 已由 tools/services/screener_service.py 替代。
"""

# ============================================================
# 预定义股票池 (Predefined Stock Pools)
# ============================================================

STOCK_POOLS = {
    # 美股核心
    'sp500_top': ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'JPM', 'V'],
    'tech_giants': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'INTC', 'CRM', 'ADBE', 'ORCL'],
    'semiconductors': ['NVDA', 'AMD', 'INTC', 'MU', 'ASML', 'TSM', 'SOXX'],
    
    # 中概股
    'china_adrs': ['BABA', 'JD', 'PDD', 'BIDU', 'NTES', 'TCEHY', 'LI', 'NIO', 'TME', 'BILI'],
    
    # 行业细分
    'ev': ['TSLA', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'BYDDF'],
    
    # A股蓝筹
    'a_share_blue': ['600519', '002594', '300750', '601318', '600036', '000858', '000333'],
    'a_share_tech': ['002475', '002415', '688981', '300124', '603501', '002371'],
    
    # 常用简称映射
    'tech': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'INTC', 'CSCO']
}

# ============================================================
# 帮助信息
# ============================================================

def get_pool(name: str) -> list:
    """获取指定名称的股票池"""
    return STOCK_POOLS.get(name, [])

def list_pools() -> list:
    """列出所有可用的股票池名称"""
    return list(STOCK_POOLS.keys())
