#!/usr/bin/env python3
"""Calibrate WIE3 HMM transition matrix from historical OHLCV microstructure sequences."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from wyckoff.config.settings import WyckoffConfig
from wyckoff.core.data_fetcher import WyckoffDataFetcher
from wyckoff.core.wie3_calibration import (
    estimate_transition_matrix,
    labels_from_wie3_frames,
    save_transition_matrix,
)
from wyckoff.core.wie3_market_state_service import WIE3MarketStateService


DEFAULT_SYMBOLS = [
    "sh.600519",
    "sz.000001",
    "sh.600036",
    "sz.300750",
]


def _collect_labels(symbol: str, period: str, config: WyckoffConfig) -> list[str]:
    fetcher = WyckoffDataFetcher(config)
    _, data = fetcher.fetch_data(symbol, period)
    if data is None or data.empty:
        raise RuntimeError(f"no data for {symbol}")

    service = WIE3MarketStateService(config.thresholds)
    if not service._ensure_engines():
        raise RuntimeError("WIE3 engines unavailable")

    df_vsa = service.vsa_analyzer.analyze(data)
    df_eff = service.efficiency_analyzer.analyze(df_vsa)
    df_aps = service.aps_analyzer.analyze(df_eff)
    df_regime = service.regime_tracker.track(df_vsa, df_eff, df_aps)
    df_rs, _ = service._resolve_relative_strength(df_regime, effective_index=None)

    n_rows = len(df_rs)
    closes = data['Close'].values
    aps_vals = df_aps['aps'].values if 'aps' in df_aps.columns else np.zeros(n_rows)
    cds_vals = df_regime['cds'].values if 'cds' in df_regime.columns else np.zeros(n_rows)
    lcs_vals = df_regime['lcs'].values if 'lcs' in df_regime.columns else np.zeros(n_rows)
    vpocs = df_regime['vpoc_price'].values if 'vpoc_price' in df_regime.columns else np.zeros(n_rows)
    exp_effs = (
        df_vsa['expansion_efficiency'].values
        if 'expansion_efficiency' in df_vsa.columns else np.zeros(n_rows)
    )
    clvs = df_vsa['clv'].values if 'clv' in df_vsa.columns else np.zeros(n_rows)
    retentions = (
        df_rs['liquidity_retention'].values
        if 'liquidity_retention' in df_rs.columns else np.ones(n_rows)
    )
    hidden_weakness = (
        df_rs['hidden_weakness'].values
        if 'hidden_weakness' in df_rs.columns else np.zeros(n_rows, dtype=bool)
    )
    event_flags = (
        df_regime['event_flag'].astype(str).tolist()
        if 'event_flag' in df_regime.columns else ['NORMAL'] * n_rows
    )

    return labels_from_wie3_frames(
        closes, aps_vals, cds_vals, lcs_vals, vpocs,
        exp_effs, clvs, retentions, hidden_weakness, event_flags,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="WIE3 HMM transition matrix calibration")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=DEFAULT_SYMBOLS,
        help="Symbols to include in calibration",
    )
    parser.add_argument("--period", default="2y", help="History period per symbol")
    parser.add_argument(
        "--output",
        default=str(ROOT / "fixtures" / "wie3" / "transition_matrix_default.json"),
        help="Output JSON path",
    )
    parser.add_argument("--smoothing", type=float, default=0.5)
    parser.add_argument("--blend-default", type=float, default=0.25)
    args = parser.parse_args()

    config = WyckoffConfig()
    all_labels: list[str] = []
    per_symbol: dict[str, int] = {}

    for symbol in args.symbols:
        print(f"Collecting weak labels: {symbol} ...", flush=True)
        labels = _collect_labels(symbol, args.period, config)
        all_labels.extend(labels)
        per_symbol[symbol] = len(labels)
        print(f"  ✓ {len(labels)} bars")

    matrix = estimate_transition_matrix(
        all_labels,
        smoothing=args.smoothing,
        blend_default=args.blend_default,
    )
    out_path = Path(args.output)
    save_transition_matrix(
        out_path,
        matrix,
        meta={
            "symbols": args.symbols,
            "period": args.period,
            "label_count": len(all_labels),
            "per_symbol": per_symbol,
            "smoothing": args.smoothing,
            "blend_default": args.blend_default,
        },
    )
    print(f"\nSaved calibrated matrix → {out_path}")
    print(json.dumps(matrix, ensure_ascii=False, indent=2)[:600] + "...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
