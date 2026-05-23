"""Shared Searchlight/WIE3 pattern enrichment for orchestrator and screener paths."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

import pandas as pd

from ..config.settings import WyckoffThresholds
from .searchlight_arbitrator import build_searchlight_arbitration
from .signal_extractor import SignalExtractor
from .wie3_market_state_service import WIE3MarketStateService

logger = logging.getLogger(__name__)

ResolveIndexFn = Callable[[], Optional[pd.DataFrame]]


def enrich_patterns_with_searchlight(
    patterns: Dict[str, Any],
    data: pd.DataFrame,
    wie3_service: WIE3MarketStateService,
    thresholds: Optional[WyckoffThresholds] = None,
    *,
    index_df: Optional[pd.DataFrame] = None,
    resolve_index_df: Optional[ResolveIndexFn] = None,
) -> Dict[str, Any]:
    """Attach Searchlight/WIE arbitration without mutating legacy phase labels."""
    if patterns.get('searchlight_arbitration'):
        return patterns

    th = thresholds or WyckoffThresholds()
    phase = SignalExtractor.get_effective_phase(patterns)

    try:
        benchmark_df = index_df
        if benchmark_df is None and resolve_index_df is not None:
            benchmark_df = resolve_index_df()
        result = wie3_service.analyze(
            data,
            index_df=benchmark_df,
            resolve_index_df=resolve_index_df,
        )
        market_state = result.market_state if result else None
        patterns['microstructure_background'] = (
            market_state.to_dict() if hasattr(market_state, 'to_dict') else market_state
        )
        patterns['searchlight_arbitration'] = build_searchlight_arbitration(
            phase, market_state, th
        )
    except Exception as exc:
        logger.debug("Searchlight enrichment skipped: %s", exc)
        patterns['searchlight_arbitration'] = build_searchlight_arbitration(
            phase, None, th
        )

    return apply_searchlight_phase_adjustment(patterns)


def apply_searchlight_phase_adjustment(patterns: Dict[str, Any]) -> Dict[str, Any]:
    """Apply soft phase-confidence adjustment from Searchlight (does not mutate phase label)."""
    sl = patterns.get('searchlight_arbitration') or {}
    if not isinstance(sl, dict) or not sl.get('available'):
        return patterns

    multiplier = float(sl.get('confidence_multiplier') or 1.0)
    if multiplier != 1.0 and patterns.get('confidence') is not None:
        try:
            patterns['confidence'] = round(float(patterns['confidence']) * multiplier, 4)
        except (TypeError, ValueError):
            pass

    hint = sl.get('resolution_hint')
    if hint:
        notes = list(patterns.get('searchlight_phase_notes') or [])
        if hint not in notes:
            notes.append(hint)
        patterns['searchlight_phase_notes'] = notes

    return patterns


def searchlight_scan_fields(patterns: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten Searchlight arbitration for batch/screener result rows."""
    sl = patterns.get('searchlight_arbitration') or {}
    if not isinstance(sl, dict):
        return {
            'searchlight_available': False,
            'searchlight_contradiction': False,
            'searchlight_bias': None,
            'searchlight_entropy_degraded': False,
        }
    return {
        'searchlight_available': bool(sl.get('available')),
        'searchlight_contradiction': bool(sl.get('has_contradiction')),
        'searchlight_bias': sl.get('bias'),
        'searchlight_entropy_degraded': bool(sl.get('entropy_degraded')),
        'searchlight_trade_bias': sl.get('trade_bias'),
        'searchlight_resolution_hint': sl.get('resolution_hint'),
        'searchlight_dominant_evidence': sl.get('dominant_evidence'),
    }
