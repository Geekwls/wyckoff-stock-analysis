#!/usr/bin/env python3
"""Phase 9–13 真实股票数据验证脚本"""
import json
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


def analyze_one(symbol: str, market: str, period: str = "1y") -> dict:
    row = {
        "symbol": symbol,
        "market": market,
        "ok": False,
        "error": None,
        "bars": 0,
        "phase": None,
        "confidence": None,
        "coordinator_phase": None,
        "identifier_phase": None,
        "phase_description": None,
        "phase_source": None,
        "direction": None,
        "action": None,
        "spring": "-",
        "joc": "-",
        "sos": "-",
        "fti": "-",
        "sow": "-",
        "vsa": "-",
        "revisions": 0,
    }
    try:
        with WyckoffAnalyzer(symbol, period, WyckoffConfig()) as az:
            data = az.fetch_data()
            if data is None or data.empty:
                row["error"] = "no_data"
                return row
            row["bars"] = len(data)

            phase_res = az.pattern_detector.identify_phase()
            events = phase_res.get("events_detected")

            row["phase"] = phase_res.get("phase")
            row["confidence"] = phase_res.get("confidence")
            row["identifier_phase"] = phase_res.get("identifier_phase")
            row["phase_description"] = phase_res.get("phase_description")
            row["phase_source"] = phase_res.get("phase_source")
            row["coordinator_phase"] = getattr(events, "coordinator_final_phase", None) if events else None
            row["revisions"] = len(getattr(events, "phase_revision_log", []) or []) if events else 0

            row["spring"] = _flag(events, "spring")
            row["joc"] = _flag(events, "joc")
            row["sos"] = _flag(events, "sos")
            row["fti"] = _flag(events, "fti")
            row["sow"] = _flag(events, "sow")
            vsa = getattr(events, "vsa_signals", None) if events else None
            if isinstance(vsa, dict):
                row["vsa"] = "Y" if any(vsa.get(k) for k in ("is_no_supply", "is_no_demand", "is_stopping_vol")) else "-"

            # 交易计划（复用已带 cache 的 detector，避免 orchestrator 二次建 detector 崩溃）
            try:
                patterns = SignalExtractor.build_scoring_payload(phase_res)
                patterns["symbol"] = symbol
                targets = az.orchestrator._calculate_targets(az.pattern_detector, patterns)
                plan = az.orchestrator.rec_engine.generate_trading_plan(az.data, patterns, targets)
                row["direction"] = getattr(plan, "direction", None) or (
                    plan.get("direction") if isinstance(plan, dict) else None
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


def main():
    print("=" * 72)
    print("威科夫真实股票验证 (Phase 9–13)")
    print("=" * 72)

    results = []
    for i, (symbol, market) in enumerate(SYMBOLS):
        if i > 0:
            time.sleep(6)  # 降低 yfinance 限流概率
        print(f"\n分析 {symbol} ({market}) ...", flush=True)
        row = analyze_one(symbol, market)
        results.append(row)
        if row["ok"]:
            print(
                f"  ✓ phase={row['phase']} conf={row['confidence']} "
                f"dir={row['direction']} act={row.get('action')} "
                f"[Sp/J/SOS/FTI/SOW={row['spring']}/{row['joc']}/{row['sos']}/{row['fti']}/{row['sow']}] "
                f"bars={row['bars']} rev={row['revisions']}"
            )
        else:
            print(f"  ✗ {row['error']}")

    ok_count = sum(1 for r in results if r["ok"])
    print("\n" + "=" * 72)
    print(f"完成: {ok_count}/{len(results)} 成功")
    print("=" * 72)

    # 批量扫描 smoke test (美股)
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
