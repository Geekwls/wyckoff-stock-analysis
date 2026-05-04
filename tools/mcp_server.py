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
from tools.exceptions import *
from tools.schemas import ErrorResponseModel
from tools.error_codes import ErrorCode

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
        with WyckoffAnalyzer(symbol, period=period) as analyzer:
            json_result = analyzer.generate_json()
            return json_result
    except WyckoffError as e:
        resp = ErrorResponseModel(
            error_code=e.error_code.value,
            error=str(e),
            type=type(e).__name__,
            retriable=isinstance(e, (DataFetchError, WyckoffError))
        )
        return resp.model_dump_json()
    except Exception as e:
        resp = ErrorResponseModel(
            error_code=ErrorCode.SYSTEM_UNKNOWN.value,
            error=str(e),
            type="UnknownError"
        )
        return resp.model_dump_json()

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
    except WyckoffError as e:
        resp = ErrorResponseModel(
            error_code=e.error_code.value,
            error=str(e),
            type=type(e).__name__,
            retriable=isinstance(e, (DataFetchError, WyckoffError))
        )
        return resp.model_dump_json()
    except Exception as e:
        resp = ErrorResponseModel(
            error_code=ErrorCode.SYSTEM_UNKNOWN.value,
            error=str(e),
            type="UnknownError"
        )
        return resp.model_dump_json()

if __name__ == "__main__":
    mcp.run()
