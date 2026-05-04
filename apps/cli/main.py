#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wyckoff CLI entrypoint."""

import argparse
import json
from wyckoff.facade import WyckoffAnalyzer, batch_scan


def main() -> None:
    parser = argparse.ArgumentParser(description="Wyckoff stock analyzer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze one symbol")
    analyze.add_argument("symbol", help="Stock symbol")
    analyze.add_argument("--period", default="1y", help="Analysis period")
    analyze.add_argument("--format", choices=["json", "text"], default="json")

    scan = subparsers.add_parser("scan", help="Batch scan symbols")
    scan.add_argument("symbols", nargs="+", help="Stock symbol list")
    scan.add_argument("--period", default="1y", help="Analysis period")

    args = parser.parse_args()

    if args.command == "analyze":
        with WyckoffAnalyzer(args.symbol, period=args.period) as analyzer:
            if args.format == "text":
                print(analyzer.generate_report())
            else:
                print(analyzer.generate_json())
        return

    results = batch_scan(args.symbols, period=args.period)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
