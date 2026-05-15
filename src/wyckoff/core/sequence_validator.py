"""
威科夫事件序列验证器

验证检测到的事件是否形成有效的威科夫因果链，
而非孤立的形态匹配。核心原则：
- 每个事件必须在其前置事件之后发生
- LPS 低点必须高于 Spring 低点
- SOS 必须在 LPS 之前出现
- JOC 必须跟随 Test of JOC
- 完整序列 = 高置信度；残缺序列 = 降级
"""
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple


class SequenceValidator:
    def __init__(self, raw_events: Dict[str, Any], data: pd.DataFrame):
        self.e = raw_events
        self.data = data

    def validate_all(self) -> Dict[str, Any]:
        spring_val = self._validate_spring_context()
        upthrust_val = self._validate_upthrust_context()
        lps_val = self._validate_lps_vs_spring()
        sos_val = self._validate_sos_context()
        joc_val = self._validate_joc_context()
        seq_score = self._calculate_sequence_score()
        conflicts = self._detect_conflicts()

        return {
            "spring": spring_val,
            "upthrust": upthrust_val,
            "lps": lps_val,
            "sos": sos_val,
            "joc": joc_val,
            "sequence_score": seq_score,
            "conflicts": conflicts,
        }

    # ── helpers ────────────────────────────────────────────
    @staticmethod
    def _get_date(raw: Any, *keys: str) -> Any:
        for k in keys:
            if isinstance(raw, dict):
                v = raw.get(k)
                if v is not None:
                    return v
            elif hasattr(raw, k):
                v = getattr(raw, k, None)
                if v is not None:
                    return v
        return None

    @staticmethod
    def _to_ts(v: Any) -> Any:
        """统一日期解析 — 委托至共享 TypeConverter"""
        from .utils import TypeConverter
        return TypeConverter.parse_date_naive(v)

    @staticmethod
    def _safe_get(raw: Any, key: str, default: Any = None) -> Any:
        if isinstance(raw, dict):
            return raw.get(key, default)
        return getattr(raw, key, default) if hasattr(raw, key) else default

    # ── Spring context ─────────────────────────────────────
    def _validate_spring_context(self) -> Dict[str, Any]:
        spring = self.e.get("spring", {})
        if not spring.get("detected"):
            return {"valid": False, "reason": "no_spring", "quality": "none"}

        climax = self.e.get("climax", {})
        ar = self.e.get("automatic_reaction", {})
        st = self.e.get("secondary_test", {})

        has_sc = climax.get("detected") and climax.get("type") == "selling_climax"
        has_ar = ar.get("detected")
        has_st = st.get("detected")
        pc = sum([has_sc, has_ar, has_st])

        spring_date = self._get_date(spring.get("latest_spring", {}), "date", "breakdown_date")
        if spring_date is None:
            # fallback to signals list
            signals = spring.get("signals", [])
            spring_date = self._get_date(signals[-1], "date") if signals else None
        spring_ts = self._to_ts(spring_date)

        sc_ts = self._to_ts(self._get_date(climax, "date")) if has_sc else None
        ar_ts = self._to_ts(self._get_date(ar, "date")) if has_ar else None
        st_ts = self._to_ts(self._get_date(st, "date")) if has_st else None

        order_ok = False
        if sc_ts and ar_ts and st_ts and spring_ts:
            order_ok = sc_ts < ar_ts < st_ts < spring_ts
        elif (has_sc + has_ar + has_st) >= 2 and spring_ts:
            avail = [t for t in [sc_ts, ar_ts, st_ts] if t is not None]
            order_ok = all(t < spring_ts for t in avail)

        notes = []
        if order_ok:
            notes.append("SC→AR→ST→Spring 时序正确 ✓")
        elif pc >= 2:
            notes.append("前置结构时序不完整，但存在部分吸筹证据 ⚠️")
        else:
            notes.append("缺少 SC/AR/ST 吸筹前置结构 ❌")

        if pc >= 3 and order_ok:
            q = "high"
        elif pc >= 2:
            q = "medium"
        elif pc >= 1:
            q = "low"
        else:
            q = "none"

        return {
            "valid": pc >= 1,
            "quality": q,
            "precursor_count": pc,
            "sequence_ordered": order_ok,
            "notes": notes,
        }

    # ── Upthrust context (distribution mirror of Spring) ───
    def _validate_upthrust_context(self) -> Dict[str, Any]:
        upthrust = self.e.get("upthrust", {})
        if not upthrust.get("detected"):
            return {"valid": False, "reason": "no_upthrust", "quality": "none"}

        climax = self.e.get("climax", {})
        ar = self.e.get("automatic_reaction", {})
        st = self.e.get("secondary_test", {})

        has_bc = climax.get("detected") and climax.get("type") == "buying_climax"
        has_ar = ar.get("detected")
        has_st = st.get("detected")
        pc = sum([has_bc, has_ar, has_st])

        upthrust_date = self._get_date(upthrust.get("latest_upthrust", {}), "date")
        if upthrust_date is None:
            upthrusts = upthrust.get("upthrusts", [])
            upthrust_date = self._get_date(upthrusts[-1], "date") if upthrusts else None
        upthrust_ts = self._to_ts(upthrust_date)

        bc_ts = self._to_ts(self._get_date(climax, "date")) if has_bc else None
        ar_ts = self._to_ts(self._get_date(ar, "date")) if has_ar else None
        st_ts = self._to_ts(self._get_date(st, "date")) if has_st else None

        order_ok = False
        if bc_ts and ar_ts and st_ts and upthrust_ts:
            order_ok = bc_ts < ar_ts < st_ts < upthrust_ts
        elif (has_bc + has_ar + has_st) >= 2 and upthrust_ts:
            avail = [t for t in [bc_ts, ar_ts, st_ts] if t is not None]
            order_ok = all(t < upthrust_ts for t in avail)

        notes = []
        if order_ok:
            notes.append("BC->AR->ST->Upthrust 时序正确")
        elif pc >= 2:
            notes.append("派发前置结构时序不完整，但存在部分派发证据")
        else:
            notes.append("缺少 BC/AR/ST 派发前置结构")

        if pc >= 3 and order_ok:
            q = "high"
        elif pc >= 2:
            q = "medium"
        elif pc >= 1:
            q = "low"
        else:
            q = "none"

        return {
            "valid": pc >= 1,
            "quality": q,
            "precursor_count": pc,
            "sequence_ordered": order_ok,
            "notes": notes,
        }

    # ── LPS vs Spring / SOS ────────────────────────────────
    def _validate_lps_vs_spring(self) -> Dict[str, Any]:
        lps = self.e.get("lps", {})
        if not lps.get("detected"):
            return {"valid": False, "reason": "no_lps"}

        latest = lps.get("latest", lps.get("signals", [{}])[-1]) if lps.get("signals") else {}
        lps_price = self._safe_get(latest, "price", 0)
        lps_date = self._to_ts(self._safe_get(latest, "date"))

        spring = self.e.get("spring", {})
        sos = self.e.get("sos", {})

        notes = []
        valid = False

        # Rule 1: LPS low > Spring low
        spring_break = None
        if spring.get("detected"):
            sl = spring.get("latest_spring", spring.get("signals", [{}])[-1]) if spring.get("signals") else {}
            spring_low = self._safe_get(sl, "breakdown_price", 0)
            spring_date = self._to_ts(self._safe_get(sl, "date") or self._safe_get(sl, "breakdown_date"))
            spring_break = spring_low

            if spring_low > 0 and lps_price > spring_low:
                notes.append(f"LPS({lps_price}) > Spring低点({spring_low}) ✓ 更高低点")
                valid = True
            elif spring_low > 0:
                notes.append(f"⚠️ LPS({lps_price}) <= Spring低点({spring_low}) 更低低点，吸筹可能失败")
            else:
                notes.append("Spring 低点数据不可用")

            # LPS date > Spring date
            if spring_date and lps_date and lps_date > spring_date:
                notes.append("LPS在Spring之后 ✓")
                valid = True
            elif spring_date and lps_date:
                notes.append("⚠️ LPS在Spring之前，时序异常")

        # Rule 2: SOS should precede LPS
        has_sos = sos.get("detected")
        if has_sos:
            sos_date = self._to_ts(self._safe_get(sos, "date"))
            if sos_date and lps_date and sos_date < lps_date:
                notes.append("SOS在前→LPS在后 ✓ 有效回调")
                valid = True
            elif sos_date and lps_date:
                notes.append("⚠️ SOS在LPS之后，顺序反常")
            else:
                notes.append("SOS已检测到（日期不可比）")
        else:
            notes.append("无SOS前置 — LPS定义为趋势回调，非吸筹LPS")

        return {
            "valid": valid,
            "has_sos_precursor": has_sos,
            "spring_low": spring_break,
            "lps_price": lps_price,
            "notes": notes,
        }

    # ── SOS context ────────────────────────────────────────
    def _validate_sos_context(self) -> Dict[str, Any]:
        sos = self.e.get("sos", {})
        if not sos.get("detected"):
            return {"valid": False, "reason": "no_sos"}

        spring = self.e.get("spring", {})
        lps = self.e.get("lps", {})

        notes = []

        # Check for Spring precursor
        if spring.get("detected"):
            notes.append("Spring前置存在 ✓")
        else:
            notes.append("无Spring前置 — SOS可能为趋势延续信号")

        # Check for LPS confirmation
        if lps.get("detected"):
            notes.append("LPS确认存在 ✓")
        else:
            notes.append("无LPS确认 — 突破后缺乏回调验证")

        # Check breakthrough_level vs TR high
        bt = self._safe_get(sos, "breakthrough_level", 0)
        bt_type = self._safe_get(sos, "breakout_type", "unknown")
        notes.append(f"突破类型: {bt_type}")

        return {
            "valid": True,
            "has_spring_precursor": spring.get("detected", False),
            "has_lps_confirmation": lps.get("detected", False),
            "notes": notes,
        }

    # ── JOC context ────────────────────────────────────────
    def _validate_joc_context(self) -> Dict[str, Any]:
        joc = self.e.get("joc", {})
        if not joc.get("detected"):
            return {"valid": False, "reason": "no_joc"}

        joc_date = self._to_ts(self._safe_get(joc, "date"))
        test_detected = self._safe_get(joc, "test_detected", False)
        test_date = self._to_ts(self._safe_get(joc, "test_date"))

        notes = []
        if test_detected:
            notes.append("Test of JOC 已检测到 ✓")
            if joc_date and test_date and test_date > joc_date:
                notes.append("回测在突破之后 ✓")
            if joc_date and test_date:
                days = (test_date - joc_date).days
                notes.append(f"回测距突破 {days} 天")
        else:
            notes.append("⚠️ 未检测到 Test of JOC — 突破缺乏回测确认")

        return {
            "valid": test_detected,
            "test_detected": test_detected,
            "notes": notes,
        }

    # ── overall sequence completeness ──────────────────────
    def _calculate_sequence_score(self) -> Dict[str, Any]:
        climax = self.e.get("climax", {})
        ar = self.e.get("automatic_reaction", {})
        st = self.e.get("secondary_test", {})
        spring = self.e.get("spring", {})
        sos = self.e.get("sos", {})
        lps = self.e.get("lps", {})
        joc = self.e.get("joc", {})

        checks = {
            "SC/BC": 1 if climax.get("detected") else 0,
            "AR": 1 if ar.get("detected") else 0,
            "ST": 1 if st.get("detected") else 0,
            "Spring/Upthrust": 1 if spring.get("detected") else 0,
            "SOS/SOW": 1 if sos.get("detected") else 0,
            "LPS/LPSY": 1 if lps.get("detected") else 0,
            "JOC/FTI": 1 if joc.get("detected") else 0,
        }
        total = len(checks)
        detected = sum(checks.values())
        completeness = round(detected / total * 100, 1)

        if completeness >= 85:
            rating = "A"
            adjustment = 1.0
        elif completeness >= 60:
            rating = "B"
            adjustment = 0.85
        elif completeness >= 30:
            rating = "C"
            adjustment = 0.7
        else:
            rating = "D"
            adjustment = 0.5

        missing = [k for k, v in checks.items() if v == 0]

        return {
            "completeness": completeness,
            "rating": rating,
            "adjustment_factor": adjustment,
            "detected_count": detected,
            "total_checks": total,
            "checks": checks,
            "missing": missing,
        }

    # ── logic conflicts ────────────────────────────────────
    def _detect_conflicts(self) -> List[str]:
        conflicts = []
        spring = self.e.get("spring", {})
        upthrust = self.e.get("upthrust", {})
        sos = self.e.get("sos", {})
        sow = self.e.get("sow", {})
        lps = self.e.get("lps", {})
        lpsy = self.e.get("lpsy", {})

        # Spring + SOW = contradictory
        if spring.get("detected") and sow.get("detected"):
            conflicts.append("Spring(做多信号)与SOW(做空信号)同时存在")

        # Upthrust + SOS = contradictory
        if upthrust.get("detected") and sos.get("detected"):
            conflicts.append("Upthrust(做空信号)与SOS(做多信号)同时存在")

        # LPS + LPSY = contradictory
        if lps.get("detected") and lpsy.get("detected"):
            if lps.get("signals") and lpsy.get("signals"):
                conflicts.append("LPS(做多支撑)与LPSY(做空阻力)同时存在")

        # LPS detected but phase is Distribution
        lps_sig_type = "unknown"
        if lps.get("signals"):
            sig = lps["signals"][-1]
            lps_sig_type = sig.get("signal_type", "unknown") if isinstance(sig, dict) else "unknown"
            if "pullback" in str(lps_sig_type):
                conflicts.append(f"LPS信号实际分类为'{lps_sig_type}'，非标准LPS")

        return conflicts
