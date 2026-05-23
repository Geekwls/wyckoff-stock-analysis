#!/usr/bin/env python3
"""Phase 9–27 真实股票数据验证脚本"""
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wyckoff.facade import WyckoffAnalyzer, batch_scan
from wyckoff.config.settings import WyckoffConfig
from wyckoff.core.signal_extractor import SignalExtractor


SYMBOLS = [
    ("AAPL", "美股"),
    ("MSFT", "美股"),
    ("NVDA", "美股"),
    ("sh.600519", "A股茅台"),
    ("sz.000001", "A股平安"),
    ("0700.HK", "港股腾讯"),
]

YFINANCE_MARKETS = {"美股", "港股腾讯"}


def _flag(events, name: str) -> str:
    if events is None:
        return "-"
    obj = getattr(events, name, None)
    if obj is None:
        return "-"
    detected = getattr(obj, "detected", None)
    if detected is None and isinstance(obj, dict):
        detected = obj.get("detected")
    return "Y" if detected else "-"


def _arbitration_summary(events, phase_res: dict | None = None) -> dict | None:
    if events is not None:
        arb = getattr(events, "arbitration_result", None)
        if arb is not None:
            dominant = getattr(arb, "dominant_signal", None)
            return {
                "has_conflict": getattr(arb, "has_conflict", False),
                "reason": getattr(arb, "arbitration_reason", None),
                "dominant": getattr(dominant, "signal_type", None) if dominant else None,
                "suggested_phase": getattr(arb, "suggested_phase", None),
            }
    if phase_res:
        for log in phase_res.get("phase_revisions") or []:
            if "[事件仲裁]" in log:
                return {"has_conflict": True, "reason": log, "dominant": None, "suggested_phase": None}
    return None


def analyze_one(symbol: str, market: str, period: str = "1y") -> dict:
    row = {
        "symbol": symbol,
        "market": market,
        "ok": False,
        "error": None,
        "bars": 0,
        "phase": None,
        "effective_phase": None,
        "confidence": None,
        "coordinator_phase": None,
        "identifier_phase": None,
        "phase_description": None,
        "phase_source": None,
        "direction": None,
        "action": None,
        "spring": "-",
        "joc": "-",
        "lps": "-",
        "lps_obs": "-",
        "sos": "-",
        "fti": "-",
        "lpsy": "-",
        "sow": "-",
        "ps": "-",
        "vsa": "-",
        "dead_corner": "-",
        "rs_trend": None,
        "entry_zone": None,
        "signal_score": None,
        "arbitration": None,
        "revisions": 0,
    }
    try:
        with WyckoffAnalyzer(symbol, period, WyckoffConfig()) as az:
            data = az.fetch_data()
            if data is None or data.empty:
                row["error"] = "no_data"
                return row
            row["bars"] = len(data)

            phase_res = az.identify_phase_with_rs()
            events = phase_res.get("events_detected")

            row["phase"] = SignalExtractor.get_effective_phase(phase_res)
            row["effective_phase"] = row["phase"]
            row["confidence"] = phase_res.get("confidence")
            row["identifier_phase"] = phase_res.get("identifier_phase")
            row["phase_description"] = phase_res.get("phase_description")
            row["phase_source"] = phase_res.get("phase_source")
            row["coordinator_phase"] = getattr(events, "coordinator_final_phase", None) if events else None
            row["revisions"] = len(getattr(events, "phase_revision_log", []) or []) if events else 0
            row["arbitration"] = _arbitration_summary(events, phase_res)
            rs = phase_res.get("relative_strength") or {}
            row["rs_trend"] = rs.get("rs_trend") if isinstance(rs, dict) else None

            row["spring"] = _flag(events, "spring")
            row["joc"] = _flag(events, "joc")
            lps_obj = getattr(events, "lps", None) if events else None
            row["lps"] = "Y" if SignalExtractor.is_formal_lps(lps_obj) else "-"
            row["lps_obs"] = "Y" if SignalExtractor.has_lps_observation(lps_obj) else "-"
            row["sos"] = _flag(events, "sos")
            row["fti"] = _flag(events, "fti")
            row["lpsy"] = "Y" if SignalExtractor.is_formal_lpsy(getattr(events, "lpsy", None) if events else None) else "-"
            row["sow"] = _flag(events, "sow")
            row["ps"] = _flag(events, "preliminary_support")
            vsa = getattr(events, "vsa_signals", None) if events else None
            if isinstance(vsa, dict):
                row["vsa"] = "Y" if any(vsa.get(k) for k in ("is_no_supply", "is_no_demand", "is_stopping_vol")) else "-"
            vsa_meng = getattr(events, "vsa_menhongtao", None) if events else None
            if row["vsa"] == "-" and isinstance(vsa_meng, dict):
                row["vsa"] = "Y" if any(
                    (vsa_meng.get(k) or {}).get("detected")
                    for k in ("no_supply", "no_demand", "stopping_vol")
                ) else "-"
            dc = getattr(events, "dead_corner_breakout", None) if events else None
            if isinstance(dc, dict):
                row["dead_corner"] = "Y" if dc.get("detected") else "-"

            try:
                patterns = SignalExtractor.build_scoring_payload(phase_res)
                patterns["symbol"] = symbol
                if row["rs_trend"]:
                    patterns["relative_strength"] = rs
                market_env = az._analyze_market_environment()
                env = market_env.get("environment") if isinstance(market_env, dict) else market_env
                patterns["market_env"] = env
                quality = az.orchestrator.rec_engine.calculate_signal_quality(
                    az.data, patterns, env
                )
                row["signal_score"] = getattr(quality, "score", None)
                targets = az.orchestrator._calculate_targets(az.pattern_detector, patterns)
                plan = az.orchestrator.rec_engine.generate_trading_plan(az.data, patterns, targets)
                row["direction"] = getattr(plan, "direction", None) or (
                    plan.get("direction") if isinstance(plan, dict) else None
                )
                row["entry_zone"] = getattr(plan, "entry_zone", None) or (
                    plan.get("entry_zone") if isinstance(plan, dict) else None
                )
                row["action"] = getattr(plan, "action", None) or (
                    plan.get("action") if isinstance(plan, dict) else None
                )
            except Exception as plan_err:
                row["direction"] = f"plan_err:{plan_err}"

            row["ok"] = True
    except Exception as e:
        row["error"] = str(e)
        row["trace"] = traceback.format_exc(limit=3)
    return row


def _parse_args():
    parser = argparse.ArgumentParser(description="威科夫真实股票验证")
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="仅验证指定代码（默认全量 SYMBOLS）",
    )
    parser.add_argument(
        "--ashare-only",
        action="store_true",
        help="仅 A 股（跳过 Yahoo 限流标的）",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="标的间休眠秒数（Yahoo 默认 12s，A 股 2s）",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Yahoo 仅使用本地过期缓存（设 WYCKOFF_YF_CACHE_ONLY=1）",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    if args.cache_only:
        os.environ["WYCKOFF_YF_CACHE_ONLY"] = "1"

    selected = list(SYMBOLS)
    if args.ashare_only:
        selected = [s for s in SYMBOLS if s[0].startswith(("sh.", "sz."))]
    if args.symbols:
        sym_set = set(args.symbols)
        selected = [s for s in SYMBOLS if s[0] in sym_set]

    print("=" * 72)
    print("威科夫真实股票验证 (Phase 9–27)")
    print("=" * 72)

    results = []
    for i, (symbol, market) in enumerate(selected):
        if i > 0:
            default_sleep = 12.0 if market in YFINANCE_MARKETS else 2.0
            time.sleep(args.sleep if args.sleep is not None else default_sleep)
        print(f"\n分析 {symbol} ({market}) ...", flush=True)
        row = analyze_one(symbol, market)
        results.append(row)
        if row["ok"]:
            arb = row.get("arbitration") or {}
            arb_note = ""
            if arb.get("has_conflict"):
                arb_note = f" arb={arb.get('dominant')} ({arb.get('reason', '')[:40]})"
            print(
                f"  ✓ phase={row['phase']} conf={row['confidence']} "
                f"dir={row['direction']} score={row.get('signal_score')} rs={row.get('rs_trend')} "
                f"[Sp/J/LPS/LPS~obs/SOS/FTI/LPSY/SOW={row['spring']}/{row['joc']}/{row['lps']}/"
                f"{row.get('lps_obs', '-')}/{row['sos']}/{row['fti']}/{row['lpsy']}/{row['sow']}] "
                f"bars={row['bars']} rev={row['revisions']}{arb_note}"
            )
            if row.get("entry_zone"):
                zone = str(row["entry_zone"])
                if len(zone) > 72:
                    zone = zone[:69] + "..."
                print(f"    zone: {zone}")
        else:
            print(f"  ✗ {row['error']}")

    ok_count = sum(1 for r in results if r["ok"])
    print("\n" + "=" * 72)
    print(f"完成: {ok_count}/{len(results)} 成功")
    print("=" * 72)

    if not args.ashare_only and any(s[0] in {"AAPL", "MSFT"} for s in selected):
        print("\n批量扫描 smoke: AAPL, MSFT ...")
        try:
            batch = batch_scan(["AAPL", "MSFT"], period="6mo", scan_mode="quick", show_progress=False)
            s = batch.get("summary", {})
            print(
                f"  batch OK: scanned={s.get('total_scanned')} signals={s.get('signal_count')} "
                f"failed={s.get('failed_count')}"
            )
        except Exception as e:
            print(f"  batch FAIL: {e}")

    out_path = ROOT / "code-review" / "REAL_STOCK_VALIDATION.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n详细结果已写入: {out_path}")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
