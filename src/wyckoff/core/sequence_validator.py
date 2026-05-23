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
    def __init__(self, raw_events: 'EventsModel', data: pd.DataFrame):
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
    def _get_date(obj: Any, *keys: str) -> Any:
        if not obj: return None
        for k in keys:
            v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
            if v is not None:
                return v
        return None

    @staticmethod
    def _get_attr(obj: Any, key: str, default=None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @classmethod
    def _latest_detail(cls, obj: Any, latest_key: str = 'latest') -> Any:
        latest = cls._get_attr(obj, latest_key)
        if latest:
            return latest
        signals = cls._get_attr(obj, 'signals', []) or []
        return signals[-1] if signals else None

    @staticmethod
    def _num(value: Any, default: float = 0.0) -> float:
        if isinstance(value, dict):
            value = value.get('value', default)
        elif hasattr(value, 'value'):
            value = getattr(value, 'value')
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_ts(v: Any) -> Any:
        """统一日期解析 — 委托至共享 TypeConverter"""
        from .utils import TypeConverter
        return TypeConverter.parse_date_naive(v)



    # ── Spring context ─────────────────────────────────────
    def _validate_spring_context(self) -> Dict[str, Any]:
        spring = self.e.spring
        if not getattr(spring, 'detected', False):
            return {"valid": False, "reason": "no_spring", "quality": "none"}

        climax = self.e.climax
        ar = self.e.automatic_reaction
        st = self.e.secondary_test

        has_sc = getattr(climax, 'detected', False) and getattr(climax, 'type', '') == "selling_climax"
        has_ar = getattr(ar, 'detected', False)
        has_st = getattr(st, 'detected', False)
        pc = sum([has_sc, has_ar, has_st])

        spring_date = self._get_date(getattr(spring, 'latest_spring', None), "date", "breakdown_date")
        if spring_date is None:
            signals = getattr(spring, 'signals', [])
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

        high_quality_causal_chain = False
        high_quality_shakeout = False

        # --- Wave 3: SOW & Spring时序解耦与量能深度验证 ---
        sow = self.e.sow
        if getattr(sow, 'detected', False):
            sow_date = self._get_date(getattr(sow, 'latest', None), "date")
            if sow_date is None:
                sow_signals = getattr(sow, 'signals', [])
                sow_date = self._get_date(sow_signals[-1], "date") if sow_signals else None
            
            sow_ts = self._to_ts(sow_date)
            if sow_ts and spring_ts:
                if sow_ts < spring_ts:
                    high_quality_causal_chain = True
                    notes.append("[经典吸筹模型确认] 检测到 Phase B 弱势出现后接 Phase C 终极震仓，因果链高度吻合，吸筹置信度极高！")
                else:
                    # SOW 发生在 Spring 之后，进行无量测试与位置破位校验
                    sow_latest = self._latest_detail(sow)
                    sow_low = self._num(self._get_attr(sow_latest, 'price', 0))
                    
                    sl = self._latest_detail(spring, 'latest_spring')
                    spring_low = self._num(self._get_attr(sl, 'breakdown_price', 0)) if sl else 0
                    
                    # 缩量校验
                    sow_vol_ratio = self._num(self._get_attr(sow_latest, 'volume_ratio', 1.0), 1.0)
                        
                    if spring_low > 0 and sow_low > 0:
                        if sow_low >= spring_low * 0.98:
                            if sow_vol_ratio < 0.8:
                                high_quality_shakeout = True
                                notes.append("Spring 后的 SOW 回调呈显著缩量且守稳前低，确认为高质量无量震仓测试。")
                            else:
                                notes.append("Spring 后的 SOW 回调未破位但未显著缩量。")
                        else:
                            notes.append("Spring 后的 SOW 放量深跌破位，吸筹结构失效。")

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
            "high_quality_causal_chain": high_quality_causal_chain,
            "high_quality_shakeout": high_quality_shakeout,
        }

    # ── Upthrust context (distribution mirror of Spring) ───
    def _validate_upthrust_context(self) -> Dict[str, Any]:
        upthrust = self.e.upthrust
        if not getattr(upthrust, 'detected', False):
            return {"valid": False, "reason": "no_upthrust", "quality": "none"}

        climax = self.e.climax
        ar = self.e.automatic_reaction
        st = self.e.secondary_test

        has_bc = getattr(climax, 'detected', False) and getattr(climax, 'type', '') == "buying_climax"
        has_ar = getattr(ar, 'detected', False)
        has_st = getattr(st, 'detected', False)
        pc = sum([has_bc, has_ar, has_st])

        upthrust_date = self._get_date(getattr(upthrust, 'latest_upthrust', None), "date")
        if upthrust_date is None:
            signals = getattr(upthrust, 'signals', [])
            upthrust_date = self._get_date(signals[-1], "date") if signals else None
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
        lps = self.e.lps
        if not getattr(lps, 'detected', False):
            return {"valid": False, "reason": "no_lps"}

        latest = self._latest_detail(lps)
        lps_price = self._num(self._get_attr(latest, "price", 0)) if latest else 0
        lps_date = self._to_ts(self._get_attr(latest, "date", None)) if latest else None

        spring = self.e.spring
        sos = self.e.sos

        notes = []
        valid = False

        # Rule 1: LPS low > Spring low
        spring_break = None
        if getattr(spring, 'detected', False):
            sl = self._latest_detail(spring, 'latest_spring')
            spring_low = self._num(self._get_attr(sl, "breakdown_price", 0)) if sl else 0
            spring_date = self._to_ts(self._get_attr(sl, "date", self._get_attr(sl, "breakdown_date", None))) if sl else None
            spring_break = spring_low

            if spring_low > 0 and lps_price > spring_low:
                notes.append(f"LPS({lps_price}) > Spring低点({spring_low}) ✓ 更高低点")
                valid = True
            elif spring_low > 0:
                notes.append(f"⚠️ LPS({lps_price}) <= Spring低点({spring_low}) 更低低点，吸筹可能失败")
            else:
                notes.append("Spring 低点数据不可用")

            if spring_date and lps_date and lps_date > spring_date:
                notes.append("LPS在Spring之后 ✓")
                valid = True
            elif spring_date and lps_date:
                notes.append("⚠️ LPS在Spring之前，时序异常")

        has_sos = getattr(sos, 'detected', False)
        if has_sos:
            sos_date = self._to_ts(getattr(sos, "date", None))
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
        sos = self.e.sos
        if not getattr(sos, 'detected', False):
            return {"valid": False, "reason": "no_sos"}

        spring = self.e.spring
        lps = self.e.lps

        notes = []

        if getattr(spring, 'detected', False):
            notes.append("Spring前置存在 ✓")
        else:
            notes.append("无Spring前置 — SOS可能为趋势延续信号")

        if getattr(lps, 'detected', False):
            notes.append("LPS确认存在 ✓")
        else:
            notes.append("无LPS确认 — 突破后缺乏回调验证")

        bt = getattr(sos, "breakthrough_level", 0)
        bt_type = getattr(sos, "breakout_type", "unknown")
        notes.append(f"突破类型: {bt_type}")

        return {
            "valid": True,
            "has_spring_precursor": getattr(spring, 'detected', False),
            "has_lps_confirmation": getattr(lps, 'detected', False),
            "notes": notes,
        }

    # ── JOC context ────────────────────────────────────────
    def _validate_joc_context(self) -> Dict[str, Any]:
        joc = self.e.joc
        if not getattr(joc, 'detected', False):
            return {"valid": False, "reason": "no_joc"}

        joc_date = self._to_ts(getattr(joc, "date", None))
        test_detected = getattr(joc, "test_detected", False)
        test_date = self._to_ts(getattr(joc, "test_date", None))

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
        climax = self.e.climax
        ar = self.e.automatic_reaction
        st = self.e.secondary_test
        spring = self.e.spring
        sos = self.e.sos
        lps = self.e.lps
        joc = self.e.joc

        checks = {
            "SC/BC": 1 if getattr(climax, 'detected', False) else 0,
            "AR": 1 if getattr(ar, 'detected', False) else 0,
            "ST": 1 if getattr(st, 'detected', False) else 0,
            "Spring/Upthrust": 1 if getattr(spring, 'detected', False) else 0,
            "SOS/SOW": 1 if getattr(sos, 'detected', False) else 0,
            "LPS/LPSY": 1 if getattr(lps, 'detected', False) else 0,
            "JOC/FTI": 1 if getattr(joc, 'detected', False) else 0,
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
        spring = self.e.spring
        upthrust = self.e.upthrust
        sos = self.e.sos
        sow = self.e.sow
        lps = self.e.lps
        lpsy = self.e.lpsy

        if getattr(spring, 'detected', False) and getattr(sow, 'detected', False):
            spring_date = self._get_date(getattr(spring, 'latest_spring', None), "date", "breakdown_date")
            if spring_date is None:
                signals = getattr(spring, 'signals', [])
                spring_date = self._get_date(signals[-1], "date") if signals else None
            spring_ts = self._to_ts(spring_date)

            sow_date = self._get_date(getattr(sow, 'latest', None), "date")
            if sow_date is None:
                sow_signals = getattr(sow, 'signals', [])
                sow_date = self._get_date(sow_signals[-1], "date") if sow_signals else None
            sow_ts = self._to_ts(sow_date)

            if spring_ts and sow_ts:
                if sow_ts < spring_ts:
                    # SOW in Phase B, Spring in Phase C - Perfect Accumulation Causal Chain
                    pass
                else:
                    # SOW after Spring - Check breakdown and volume
                    sow_latest = self._latest_detail(sow)
                    sow_low = self._num(self._get_attr(sow_latest, 'price', 0))
                    
                    sl = self._latest_detail(spring, 'latest_spring')
                    spring_low = self._num(self._get_attr(sl, 'breakdown_price', 0)) if sl else 0

                    sow_vol_ratio = self._num(self._get_attr(sow_latest, 'volume_ratio', 1.0), 1.0)

                    if spring_low > 0 and sow_low > 0:
                        if sow_low < spring_low * 0.98:
                            # SOW effectively broke the Spring low - Fail!
                            conflicts.append("Spring后发生放量深跌破位(SOW)，突破支撑失败，吸筹结构已失效")
                        else:
                            # sow_low >= spring_low * 0.98
                            if sow_vol_ratio >= 0.8:
                                # Not shrunken enough, soft warning
                                conflicts.append("Spring后发生SOW回调，但量能未显著萎缩，结构存在疑虑")
                            else:
                                # High-quality shakeout confirmation - No conflict!
                                pass
                    else:
                        conflicts.append("Spring(做多信号)与SOW(做空信号)同时存在且无足够价格数据对比")
            else:
                conflicts.append("Spring(做多信号)与SOW(做空信号)同时存在且日期不可比")

        if getattr(upthrust, 'detected', False) and getattr(sos, 'detected', False):
            conflicts.append("Upthrust(做空信号)与SOS(做多信号)同时存在")

        if getattr(lps, 'detected', False) and getattr(lpsy, 'detected', False):
            if getattr(lps, 'signals', None) and getattr(lpsy, 'signals', None):
                conflicts.append("LPS(做多支撑)与LPSY(做空阻力)同时存在")

        lps_sig_type = "unknown"
        signals = getattr(lps, 'signals', [])
        if signals:
            sig = signals[-1]
            lps_sig_type = getattr(sig, "signal_type", "unknown")
            if "pullback" in str(lps_sig_type):
                conflicts.append(f"LPS信号实际分类为'{lps_sig_type}'，非标准LPS")

        return conflicts
