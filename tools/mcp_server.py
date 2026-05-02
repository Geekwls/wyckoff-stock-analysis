#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析 MCP (Model Context Protocol) Server
"""
import sys
import os
import json
from mcp.server.fastmcp import FastMCP

# Ensure the parent directory is in the path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from tools.wyckoff_analyzer import WyckoffAnalyzer, batch_scan

mcp = FastMCP("Wyckoff Stock Analyzer")

@mcp.tool()
def analyze_stock_wyckoff(symbol: str, period: str = "1y") -> str:
    """
    Use Wyckoff logic to analyze a specific stock's volume and price action.
    Returns a comprehensive JSON string detailing market phase, cause/effect targets,
    and key Wyckoff events (Spring, Upthrust, SOS, SOW, etc.).
    
    Args:
        symbol: The stock symbol (e.g., 'AAPL' or 'sh.600519' for Chinese A-shares).
        period: Time period to analyze (default: '1y').
    """
    try:
        analyzer = WyckoffAnalyzer(symbol, period=period)
        json_result = analyzer.generate_json()
        return json_result
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def batch_analyze_sector(symbols: list[str], period: str = "1y") -> str:
    """
    Batch scan a list of stock symbols to find high-probability Wyckoff setups.
    
    Args:
        symbols: List of stock symbols.
        period: Time period (default: '1y').
    """
    try:
        results = batch_scan(symbols, period=period, show_progress=False)
        return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run()
