#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Library-layer MCP compatibility helpers.

This keeps backward-compatible imports for tests/tools that previously used
`src.wyckoff.mcp_server.analyze_stock_wyckoff`.
"""

from .facade import WyckoffAnalyzer
from .exceptions import WyckoffError, DataFetchError
from .schemas import ErrorResponseModel
from .core.enums import ErrorCode


def analyze_stock_wyckoff(symbol: str, period: str = "1y") -> str:
    """Analyze a symbol and return JSON payload, compatible with old MCP helper."""
    try:
        with WyckoffAnalyzer(symbol, period=period) as analyzer:
            return analyzer.generate_json()
    except WyckoffError as e:
        resp = ErrorResponseModel(
            error_code=e.error_code.value,
            error=str(e),
            type=type(e).__name__,
            retriable=isinstance(e, (DataFetchError, WyckoffError)),
        )
        return resp.model_dump_json()
    except Exception as e:
        resp = ErrorResponseModel(
            error_code=ErrorCode.SYSTEM_UNKNOWN.value,
            error=str(e),
            type="UnknownError",
        )
        return resp.model_dump_json()
