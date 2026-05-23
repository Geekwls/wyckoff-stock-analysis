"""Searchlight arbitration between legacy Wyckoff phase and WIE microstructure."""
from typing import Any, Dict, Iterable, Optional

from ..config.settings import WyckoffThresholds
from .utils import PhaseAdapter

_RESOLUTION_HINTS = {
    'legacy_distribution_but_wie_absorption_or_demand_dominates': (
        '结构标派发，但微观结构显示吸收/需求主导，禁止做空，等待结构重估'
    ),
    'legacy_accumulation_but_wie_panic_or_distribution_dominates': (
        '结构标吸筹，但微观结构显示恐慌/派发主导，禁止做多，等待结构重估'
    ),
    'microstructure_aligned_or_inconclusive': '结构与微观背景一致或证据不足，沿用结构阶段',
    'entropy_degraded_watch': '微观状态高熵，结构置信度下调，建议减半仓位或观望',
    'no_microstructure_context': '缺少 WIE3 微观背景，仅依据结构阶段决策',
}


def _state_to_dict(market_state: Any) -> Dict[str, Any]:
    if not market_state:
        return {}
    if hasattr(market_state, 'to_dict'):
        return market_state.to_dict()
    if isinstance(market_state, dict):
        return dict(market_state)
    return {
        key: getattr(market_state, key)
        for key in (
            'state_probs',
            'aps',
            'is_confidence_degraded',
            'hidden_weakness',
            'hidden_strength',
            'regime',
        )
        if hasattr(market_state, key)
    }


def _probability_sum(probs: Dict[str, Any], prefixes: Iterable[str]) -> float:
    total = 0.0
    for key, value in probs.items():
        if not any(str(key).startswith(prefix) for prefix in prefixes):
            continue
        try:
            total += float(value)
        except (TypeError, ValueError):
            pass
    return round(total, 4)


def _resolve_trade_bias(
    *,
    phase: str,
    contradiction: bool,
    bias: str,
    phase_is_distribution: bool,
    phase_is_accumulation: bool,
    entropy_degraded: bool,
) -> str:
    if contradiction or entropy_degraded:
        return 'watch_only'
    if phase_is_accumulation or PhaseAdapter.is_markup(phase):
        return 'long_ok'
    if phase_is_distribution:
        return 'short_ok'
    return 'neutral'


def _resolve_dominant_evidence(
    *,
    contradiction: bool,
    entropy_degraded: bool,
    available: bool,
) -> str:
    if not available:
        return 'inconclusive'
    if contradiction:
        return 'conflict'
    if entropy_degraded:
        return 'microstructure'
    return 'structure'


def _resolve_confidence_multiplier(
    *,
    contradiction: bool,
    entropy_degraded: bool,
    bias: str,
) -> float:
    if contradiction and entropy_degraded:
        return 0.4
    if contradiction:
        return 0.55
    if entropy_degraded:
        return 0.75
    return 1.0


def _empty_arbitration(action: str, phase: str = '') -> Dict[str, Any]:
    return {
        'available': False,
        'has_contradiction': False,
        'action': action,
        'legacy_phase': phase or None,
        'confidence_multiplier': 1.0,
        'trade_bias': 'neutral',
        'dominant_evidence': 'inconclusive',
        'resolution_hint': _RESOLUTION_HINTS.get(action, _RESOLUTION_HINTS['no_microstructure_context']),
    }


def build_searchlight_arbitration(
    phase: str,
    market_state: Any,
    thresholds: Optional[WyckoffThresholds] = None,
) -> Dict[str, Any]:
    """Compare legacy phase labeling with WIE microstructure without mutating phase."""
    th = thresholds or WyckoffThresholds()
    bullish_prob_threshold = th.SEARCHLIGHT_BULLISH_PROB_THRESHOLD
    bearish_prob_threshold = th.SEARCHLIGHT_BEARISH_PROB_THRESHOLD
    aps_absorption_threshold = th.SEARCHLIGHT_APS_ABSORPTION_THRESHOLD

    state_dict = _state_to_dict(market_state)
    if not state_dict:
        return _empty_arbitration('no_microstructure_context', phase)

    probs = state_dict.get('state_probs') or {}
    bullish_prob = _probability_sum(probs, ('S1:', 'S3:', 'S4:'))
    bearish_prob = _probability_sum(probs, ('S0:', 'S5:'))
    aps = float(state_dict.get('aps') or 0.0)
    entropy_degraded = bool(state_dict.get('is_confidence_degraded'))
    hidden_weakness = bool(state_dict.get('hidden_weakness'))
    hidden_strength = bool(state_dict.get('hidden_strength'))

    phase_is_distribution = PhaseAdapter.is_distribution(phase)
    phase_is_accumulation = PhaseAdapter.is_accumulation(phase) or PhaseAdapter.is_markup(phase)

    contradiction = False
    bias = 'neutral'
    reason = 'microstructure_aligned_or_inconclusive'

    if (
        phase_is_distribution
        and bullish_prob >= bullish_prob_threshold
        and (aps >= aps_absorption_threshold or hidden_strength)
    ):
        contradiction = True
        bias = 'bullish_microstructure'
        reason = 'legacy_distribution_but_wie_absorption_or_demand_dominates'
    elif phase_is_accumulation and (bearish_prob >= bearish_prob_threshold or hidden_weakness):
        contradiction = True
        bias = 'bearish_microstructure'
        reason = 'legacy_accumulation_but_wie_panic_or_distribution_dominates'

    if entropy_degraded and not contradiction:
        reason = 'entropy_degraded_watch'

    confidence_multiplier = _resolve_confidence_multiplier(
        contradiction=contradiction,
        entropy_degraded=entropy_degraded,
        bias=bias,
    )
    trade_bias = _resolve_trade_bias(
        phase=phase,
        contradiction=contradiction,
        bias=bias,
        phase_is_distribution=phase_is_distribution,
        phase_is_accumulation=phase_is_accumulation,
        entropy_degraded=entropy_degraded,
    )
    if contradiction:
        trade_bias = 'watch_only'
    dominant_evidence = _resolve_dominant_evidence(
        contradiction=contradiction,
        entropy_degraded=entropy_degraded,
        available=True,
    )
    resolution_hint = _RESOLUTION_HINTS.get(reason, _RESOLUTION_HINTS['microstructure_aligned_or_inconclusive'])
    if contradiction:
        resolution_hint = _RESOLUTION_HINTS[reason]

    return {
        'available': True,
        'has_contradiction': contradiction,
        'action': 'review_phase_with_wie_context' if contradiction else 'use_legacy_phase',
        'legacy_phase': phase,
        'microstructure_regime': state_dict.get('regime'),
        'bias': bias,
        'reason': reason,
        'bullish_probability': bullish_prob,
        'bearish_probability': bearish_prob,
        'aps': aps,
        'entropy_degraded': entropy_degraded,
        'confidence_multiplier': confidence_multiplier,
        'trade_bias': trade_bias,
        'dominant_evidence': dominant_evidence,
        'resolution_hint': resolution_hint,
    }
