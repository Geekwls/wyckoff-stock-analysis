#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析 MCP (Model Context Protocol) Server (应用层)
Wyckoff Analysis MCP Server

这是应用层代码，仅调用库层 (src/wyckoff/) 的公共 API。
不依赖任何其他应用层代码。
"""

import sys
import os
import json
from mcp.server.fastmcp import FastMCP

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# 从库层导入（仅使用公共 API）
from src.wyckoff.facade import WyckoffAnalyzer, batch_scan
from src.wyckoff.exceptions import *
from src.wyckoff.schemas import ErrorResponseModel
from src.wyckoff.core.enums import ErrorCode

# 创建 MCP 服务器
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

    Returns:
        JSON string with analysis results or error response.
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

    Returns:
        JSON string with batch scan results or error response.
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
