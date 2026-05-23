"""WIE3 HMM transition-matrix calibration from weak-labeled microstructure sequences."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

from .market_state import RegimeState

_STATE_LABELS = [s.value for s in RegimeState]
_LABEL_TO_IDX = {label: i for i, label in enumerate(_STATE_LABELS)}


def default_transition_matrix() -> Dict[str, Dict[str, float]]:
    from .state_engine import EventDrivenStateEngine

    return EventDrivenStateEngine._build_default_transition_matrix()


def weak_label_state(
    *,
    close: float,
    aps: float,
    cds: float,
    lcs: float,
    vpoc: float,
    exp_eff: float,
    clv: float,
    retention: float,
    hidden_weakness: bool = False,
    event_flag: str = 'NORMAL',
) -> str:
    """Map microstructure features to a weak S0–S5 label (same heuristics as state_engine)."""
    is_breakdown = (clv < -0.6 and exp_eff < 0.5) or hidden_weakness or (aps < 5 and cds < 10)
    if is_breakdown:
        return RegimeState.S0_PANIC_LIQUIDATION.value

    scores = {
        RegimeState.S0_PANIC_LIQUIDATION.value: 0.0,
        RegimeState.S1_ABSORPTION.value: max(0.0, (aps - 8.0) / 10.0),
        RegimeState.S2_NEUTRAL_COMPRESSION.value: max(0.0, (cds - 10.0) / 20.0 + lcs / 10.0),
        RegimeState.S3_DEMAND_EMERGENCE.value: (
            max(0.0, (exp_eff - 1.2) / 2.0) if close > vpoc else 0.0
        ) + (5.0 if 'SPRING' in event_flag and aps > 10 else 0.0),
        RegimeState.S4_MARKUP.value: (
            max(0.0, (exp_eff - 1.5) / 2.0 + (retention - 1.0))
            if close > vpoc * 1.05 and exp_eff > 1.5 and retention > 1.1
            else 0.0
        ),
        RegimeState.S5_DISTRIBUTION.value: max(0.0, 3.0 if clv < -0.4 and retention < 0.8 else 0.0),
    }
    return max(scores.items(), key=lambda item: item[1])[0]


def estimate_transition_matrix(
    labels: Sequence[str],
    *,
    smoothing: float = 0.5,
    blend_default: float = 0.25,
) -> Dict[str, Dict[str, float]]:
    """Estimate row-stochastic transition matrix with Laplace smoothing."""
    n = len(_STATE_LABELS)
    counts = np.full((n, n), smoothing, dtype=float)

    prev_idx = None
    for label in labels:
        idx = _LABEL_TO_IDX.get(label)
        if idx is None:
            continue
        if prev_idx is not None:
            counts[prev_idx, idx] += 1.0
        prev_idx = idx

    matrix: Dict[str, Dict[str, float]] = {}
    for i, from_label in enumerate(_STATE_LABELS):
        row = counts[i]
        total = row.sum()
        matrix[from_label] = {
            to_label: float(row[j] / total)
            for j, to_label in enumerate(_STATE_LABELS)
        }

    if blend_default <= 0:
        return _normalize_matrix(matrix)

    base = default_transition_matrix()
    blended: Dict[str, Dict[str, float]] = {}
    alpha = min(max(blend_default, 0.0), 1.0)
    for from_label in _STATE_LABELS:
        blended[from_label] = {}
        for to_label in _STATE_LABELS:
            blended[from_label][to_label] = (
                alpha * base[from_label][to_label] + (1.0 - alpha) * matrix[from_label][to_label]
            )
    return _normalize_matrix(blended)


def _normalize_matrix(matrix: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    normalized: Dict[str, Dict[str, float]] = {}
    for from_label in _STATE_LABELS:
        row = matrix.get(from_label) or {}
        values = [max(0.0, float(row.get(to_label, 0.0))) for to_label in _STATE_LABELS]
        total = sum(values)
        if total <= 0:
            uniform = 1.0 / len(_STATE_LABELS)
            normalized[from_label] = {to_label: round(uniform, 4) for to_label in _STATE_LABELS}
            continue
        normalized[from_label] = {
            to_label: round(values[i] / total, 4) for i, to_label in enumerate(_STATE_LABELS)
        }
    return normalized


def labels_from_wie3_frames(
    closes: np.ndarray,
    aps_vals: np.ndarray,
    cds_vals: np.ndarray,
    lcs_vals: np.ndarray,
    vpocs: np.ndarray,
    exp_effs: np.ndarray,
    clvs: np.ndarray,
    retentions: np.ndarray,
    hidden_weaknesses: np.ndarray,
    event_flags: Iterable[str],
) -> List[str]:
    labels: List[str] = []
    flags = list(event_flags)
    for i in range(len(closes)):
        labels.append(
            weak_label_state(
                close=float(closes[i]),
                aps=float(aps_vals[i]),
                cds=float(cds_vals[i]),
                lcs=float(lcs_vals[i]),
                vpoc=float(vpocs[i]),
                exp_eff=float(exp_effs[i]),
                clv=float(clvs[i]),
                retention=float(retentions[i]),
                hidden_weakness=bool(hidden_weaknesses[i]),
                event_flag=str(flags[i]) if i < len(flags) else 'NORMAL',
            )
        )
    return labels


def save_transition_matrix(path: Path, matrix: Dict[str, Dict[str, float]], meta: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        'version': 'wie3-calibration-v1',
        'states': _STATE_LABELS,
        'transition_matrix': matrix,
        'meta': meta or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def load_transition_matrix(path: Path) -> Optional[Dict[str, Dict[str, float]]]:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    matrix = payload.get('transition_matrix')
    if not isinstance(matrix, dict):
        return None
    return matrix


def resolve_transition_matrix_path(thresholds: Any = None) -> Optional[Path]:
    """Resolve configured/default WIE3 transition matrix path."""
    custom = getattr(thresholds, 'WIE3_TRANSITION_MATRIX_PATH', None) if thresholds else None
    if custom:
        return Path(str(custom)).expanduser()

    repo_default = Path(__file__).resolve().parents[3] / 'fixtures' / 'wie3' / 'transition_matrix_default.json'
    if repo_default.is_file():
        return repo_default
    return None
