#!/usr/bin/env python3
"""Export strategy decision audit events to JSONL for backtest / manual review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wyckoff.facade import WyckoffAnalyzer
from wyckoff.core.report_generator import WyckoffReportGenerator
from wyckoff.core.strategy_decision_audit import write_audit_jsonl


def _load_audit_from_report(analyzer: WyckoffAnalyzer) -> dict:
    payload = json.loads(WyckoffReportGenerator(analyzer).generate_json())
    return payload.get('strategy_decision_audit') or {}


def main() -> int:
    parser = argparse.ArgumentParser(description='Export strategy decision audit log to JSONL')
    parser.add_argument('symbol', help='Ticker symbol, e.g. AAPL or sh.600519')
    parser.add_argument('--period', default='1y', help='Data period (default: 1y)')
    parser.add_argument(
        '-o', '--output',
        default='decision_audit.jsonl',
        help='Output JSONL path (default: decision_audit.jsonl)',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite output file instead of appending',
    )
    args = parser.parse_args()

    analyzer = WyckoffAnalyzer(args.symbol, period=args.period)
    analyzer.fetch_data()
    audit = _load_audit_from_report(analyzer)

    written = write_audit_jsonl(audit, args.output, append=not args.overwrite)
    summary = audit.get('summary') or {}
    print(
        f"[audit-export] symbol={args.symbol} events={written} "
        f"total={summary.get('total_events', 0)} -> {args.output}"
    )
    return 0 if written >= 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
