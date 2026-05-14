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
from src.wyckoff.exceptions import AnalysisError, DataFetchError, WyckoffError
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


@mcp.tool()
def detect_wyckoff_phase(symbol: str, period: str = "1y") -> str:
    """
    [ATOMIC TOOL — Token Efficient] Detect the current Wyckoff phase for a stock.

    Use this tool INSTEAD of analyze_stock_wyckoff when the user asks ONLY about:
    - "What phase is X in?"
    - "Is X accumulating or distributing?"
    - "Where is X in the Wyckoff cycle?"

    Skips RS analysis, multi-timeframe, sentiment, and report generation.
    Token cost: ~5-10% of full analyze_stock_wyckoff.

    Returns a compact JSON with:
      - phase: current Wyckoff phase (e.g. "Accumulation Phase C")
      - phase_confidence: float 0-1
      - sequence_completeness: float 0-1 (event chain completeness)
      - current_price: float
      - key_events_summary: { sos_detected, sow_detected, spring_detected, trading_range }
      - phase_advice: phase-linked position advice per Wyckoff theory

    Args:
        symbol: Stock symbol (e.g. 'AAPL' or 'sh.600519').
        period: Time period (default: '1y').
    """
    try:
        with WyckoffAnalyzer(symbol, period=period) as analyzer:
            analyzer.fetch_data()
            return analyzer.generate_phase_json()
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
def get_trading_levels(symbol: str, period: str = "1y") -> str:
    """
    [ATOMIC TOOL — Token Efficient] Get key price levels for a stock.

    Use this tool INSTEAD of analyze_stock_wyckoff when the user asks ONLY about:
    - "What is the support / resistance for X?"
    - "Where should I set my stop loss?"
    - "What are the price targets for X?"
    - "Give me the key levels for X"

    Skips phase scoring, RS analysis, multi-timeframe, historical performance, and report generation.
    Token cost: ~5-10% of full analyze_stock_wyckoff.

    Returns a compact JSON with:
      - current_price: float
      - trading_range: { high, low, range_pct }
      - stop_loss: { conservative: { value, derivation, note }, aggressive: { ... } }
      - targets: { target_1: { value, derivation, note }, target_2: { ... } }
      - key_confirmation_level: { value, derivation, note } (from SOS analysis, if available)
      - atr: float (14-day ATR used for calculations)

    Args:
        symbol: Stock symbol (e.g. 'AAPL' or 'sh.600519').
        period: Time period (default: '1y').
    """
    try:
        with WyckoffAnalyzer(symbol, period=period) as analyzer:
            analyzer.fetch_data()
            return analyzer.generate_levels_json()
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
def analyze_signal_conflict(symbol: str, period: str = "1y") -> str:
    """
    [ATOMIC TOOL — Token Efficient] Analyze contradictory SOS and SOW signals.

    Use this tool INSTEAD of analyze_stock_wyckoff when the user asks:
    - "Is this a shakeout or a bull trap?"
    - "Explain the conflict between SOS and SOW."
    - "Why are there contradictory signals?"

    Token cost: ~10-15% of full analyze_stock_wyckoff.

    Returns a JSON with:
      - has_conflict: boolean
      - interpretation: "shakeout_bullish" | "trap_bearish" | "uncertain"
      - confidence: float 0-1
      - reasons: list of strings (detailed evidence)
      - confirmation_criteria: list of strings (what to watch for)
      - breakdown_level: { value, derivation, note }

    Args:
        symbol: Stock symbol (e.g. 'AAPL' or 'sh.600519').
        period: Time period (default: '1y').
    """
    try:
        with WyckoffAnalyzer(symbol, period=period) as analyzer:
            analyzer.fetch_data()
            return analyzer.generate_conflict_json()
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
