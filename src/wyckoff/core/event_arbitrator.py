"""
事件仲裁器 - 处理威科夫信号冲突和逻辑矛盾

当检测到相互矛盾的信号时（如Spring做多 vs LPSY做空），仲裁器负责：
1. 分析信号的时间顺序（新信号通常优先于旧信号）
2. 评估信号的强度和置信度
3. 基于威科夫理论判断市场真实意图
4. 提供明确的阶段判定建议
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd

from ..schemas import (
    ArbitrationResult,
    ArbitrationSignal,
    SpringModel,
    LpsyModel,
    SosModel,
    SowModel
)

logger = logging.getLogger(__name__)


class EventArbitrator:
    """事件仲裁器 - 解决威科夫信号冲突"""

    # 定义信号方向
    BULLISH_SIGNALS = {'spring', 'sos', 'joc', 'lps'}
    BEARISH_SIGNALS = {'upthrust', 'sow', 'lpsy', 'fti'}

    # 定义信号优先级（数字越大优先级越高）
    SIGNAL_PRIORITY = {
        'spring': 8,
        'lpsy': 9,
        'sos': 7,
        'sow': 7,
        'joc': 8,
        'fti': 8,
        'upthrust': 6,
        'lps': 6
    }

    def __init__(self, data: pd.DataFrame):
        """
        初始化仲裁器

        Args:
            data: 价格数据，用于验证信号
        """
        self.data = data

    def arbitrate(self, events: Dict[str, Any]) -> ArbitrationResult:
        """
        对事件进行仲裁，解决信号冲突

        Args:
            events: 包含所有威科夫事件的字典

        Returns:
            ArbitrationResult: 仲裁结果
        """
        # 提取所有有效信号
        all_signals = self._extract_all_signals(events)

        if not all_signals:
            return ArbitrationResult(
                has_conflict=False,
                arbitration_reason="无有效信号需要仲裁"
            )

        # 检测冲突信号
        conflicts = self._detect_conflicts(all_signals)

        if not conflicts:
            return ArbitrationResult(
                has_conflict=False,
                arbitration_reason="无信号冲突",
                dominant_signal=all_signals[0] if all_signals else None
            )

        # 执行仲裁
        return self._resolve_conflicts(all_signals, conflicts, events)

    def _extract_all_signals(self, events: Dict[str, Any]) -> List[ArbitrationSignal]:
        """从事件字典中提取所有有效信号"""
        signals = []

        # 提取Spring信号
        spring = events.get('spring')
        if spring and self._is_signal_detected(spring):
            spring_signals = self._extract_spring_signals(spring)
            signals.extend(spring_signals)

        # 提取LPSY信号
        lpsy = events.get('lpsy')
        if lpsy and self._is_signal_detected(lpsy):
            lpsy_signals = self._extract_lpsy_signals(lpsy)
            signals.extend(lpsy_signals)

        # 提取SOS信号
        sos = events.get('sos')
        if sos and self._is_signal_detected(sos):
            sos_signals = self._extract_sos_signals(sos)
            signals.extend(sos_signals)

        # 提取SOW信号
        sow = events.get('sow')
        if sow and self._is_signal_detected(sow):
            sow_signals = self._extract_sow_signals(sow)
            signals.extend(sow_signals)

        # B6: Upthrust / JOC / FTI
        upthrust = events.get('upthrust')
        if upthrust and self._is_signal_detected(upthrust):
            signals.extend(self._extract_upthrust_signals(upthrust))

        joc = events.get('joc')
        if joc and self._is_signal_detected(joc):
            signals.extend(self._extract_joc_signals(joc))

        fti = events.get('fti')
        if fti and self._is_signal_detected(fti):
            signals.extend(self._extract_fti_signals(fti))

        # 按日期排序（最新的在前）
        signals.sort(key=lambda x: self._parse_date(x.date), reverse=True)

        return signals

    def _is_signal_detected(self, signal_obj: Any) -> bool:
        """检查信号是否被检测到"""
        if hasattr(signal_obj, 'detected'):
            return signal_obj.detected
        if isinstance(signal_obj, dict):
            return signal_obj.get('detected', False)
        return False

    def _get_signal_field(self, signal_obj: Any, key: str, default=None):
        if isinstance(signal_obj, dict):
            return signal_obj.get(key, default)
        return getattr(signal_obj, key, default)

    def _dump_signal(self, signal_obj: Any) -> Dict[str, Any]:
        if hasattr(signal_obj, 'model_dump'):
            return signal_obj.model_dump()
        if isinstance(signal_obj, dict):
            return signal_obj
        return {}

    def _iter_signal_details(self, event_obj: Any, latest_key: str = 'latest') -> List[Any]:
        if isinstance(event_obj, dict):
            signals = list(event_obj.get('signals') or [])
            latest = event_obj.get(latest_key)
            if latest and latest not in signals:
                signals.append(latest)
            return signals

        signals = list(getattr(event_obj, 'signals', None) or [])
        latest = getattr(event_obj, latest_key, None)
        if latest and latest not in signals:
            signals.append(latest)
        return signals

    def _extract_spring_signals(self, spring: SpringModel) -> List[ArbitrationSignal]:
        """提取Spring信号（B13: 去重 latest_spring 与 signals）"""
        signals = []
        seen_dates = set()

        if hasattr(spring, 'signals') and spring.signals:
            for sig in spring.signals:
                date_key = str(getattr(sig, 'date', None))
                if date_key in seen_dates:
                    continue
                seen_dates.add(date_key)
                signals.append(ArbitrationSignal(
                    signal_type='spring',
                    date=sig.date,
                    direction='bullish',
                    confidence=self._calculate_spring_confidence(sig),
                    strength=getattr(sig, 'total_score', None) or getattr(sig, 'confidence', 0),
                    raw_data={'spring': sig.model_dump() if hasattr(sig, 'model_dump') else sig}
                ))

        if hasattr(spring, 'latest_spring') and spring.latest_spring:
            sig = spring.latest_spring
            date_key = str(getattr(sig, 'date', None))
            if date_key not in seen_dates:
                signals.append(ArbitrationSignal(
                    signal_type='spring',
                    date=sig.date,
                    direction='bullish',
                    confidence=self._calculate_spring_confidence(sig),
                    strength=getattr(sig, 'total_score', None) or getattr(sig, 'confidence', 0),
                    raw_data={'spring': sig.model_dump() if hasattr(sig, 'model_dump') else sig}
                ))

        return signals

    def _extract_lpsy_signals(self, lpsy: LpsyModel) -> List[ArbitrationSignal]:
        """提取LPSY信号"""
        signals = []

        # 处理所有LPSY信号
        if hasattr(lpsy, 'signals') and lpsy.signals:
            for sig in lpsy.signals:
                signals.append(ArbitrationSignal(
                    signal_type='lpsy',
                    date=sig.date,
                    direction='bearish',
                    confidence=min(sig.volume_ratio / 2.0, 1.0),  # 基于量比估算置信度
                    strength=sig.volume_ratio,
                    raw_data={'lpsy': sig.model_dump() if hasattr(sig, 'model_dump') else sig}
                ))

        # 处理最新LPSY
        if hasattr(lpsy, 'latest') and lpsy.latest:
            sig = lpsy.latest
            signals.append(ArbitrationSignal(
                signal_type='lpsy',
                date=sig.date,
                direction='bearish',
                confidence=min(sig.volume_ratio / 2.0, 1.0),
                strength=sig.volume_ratio,
                raw_data={'lpsy': sig.model_dump() if hasattr(sig, 'model_dump') else sig}
            ))

        return signals

    def _signal_confidence(self, sig: Any, default: float = 0.7) -> float:
        """统一 SOS/SOW 置信度量纲：检测器可能返回 0–100 分或仅给 volume_ratio。"""
        from .signal_extractor import SignalExtractor
        raw = self._get_signal_field(sig, 'confidence')
        if raw is not None:
            return SignalExtractor.normalize_confidence(raw, default)
        vol = self._get_signal_field(sig, 'volume_ratio')
        if vol is not None:
            # 孟氏 SOS 阈值 1.5x；无量化 confidence 时用 1.5x 作为满分参考
            return min(float(vol) / 1.5, 1.0)
        score = self._get_signal_field(sig, 'total_score')
        if score is not None:
            return SignalExtractor.normalize_confidence(score, default)
        return default

    def _extract_sos_signals(self, sos: SosModel) -> List[ArbitrationSignal]:
        """提取SOS信号"""
        signals = []

        for sig in self._iter_signal_details(sos):
            signals.append(ArbitrationSignal(
                signal_type='sos',
                date=self._get_signal_field(sig, 'date'),
                direction='bullish',
                confidence=self._signal_confidence(sig, 0.7),
                strength=self._get_signal_field(sig, 'volume_ratio'),
                raw_data={'sos': self._dump_signal(sig)}
            ))

        return signals

    def _extract_sow_signals(self, sow: SowModel) -> List[ArbitrationSignal]:
        """提取SOW信号"""
        signals = []

        for sig in self._iter_signal_details(sow):
            signals.append(ArbitrationSignal(
                signal_type='sow',
                date=self._get_signal_field(sig, 'date'),
                direction='bearish',
                confidence=self._signal_confidence(sig, 0.7),
                strength=self._get_signal_field(sig, 'volume_ratio'),
                raw_data={'sow': self._dump_signal(sig)}
            ))

        return signals

    def _extract_upthrust_signals(self, upthrust: Any) -> List[ArbitrationSignal]:
        """提取 Upthrust 信号"""
        signals = []
        seen_dates = set()
        for sig in self._iter_signal_details(upthrust, latest_key='latest_upthrust'):
            date_key = str(self._get_signal_field(sig, 'date'))
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)
            conf_raw = self._get_signal_field(sig, 'confidence', 50)
            conf = conf_raw / 100.0 if conf_raw and conf_raw > 1 else (conf_raw or 0.5)
            signals.append(ArbitrationSignal(
                signal_type='upthrust',
                date=self._get_signal_field(sig, 'date'),
                direction='bearish',
                confidence=min(float(conf), 1.0),
                strength=self._get_signal_field(sig, 'vol_ratio'),
                raw_data={'upthrust': self._dump_signal(sig)}
            ))
        return signals

    def _extract_joc_signals(self, joc: Any) -> List[ArbitrationSignal]:
        """提取 JOC 信号"""
        signals = []
        for sig in self._iter_signal_details(joc, latest_key='latest'):
            signals.append(ArbitrationSignal(
                signal_type='joc',
                date=self._get_signal_field(sig, 'date'),
                direction='bullish',
                confidence=self._signal_confidence(sig, 0.75),
                strength=self._get_signal_field(sig, 'volume_ratio'),
                raw_data={'joc': self._dump_signal(sig)}
            ))
        return signals

    def _extract_fti_signals(self, fti: Any) -> List[ArbitrationSignal]:
        """提取 FTI 信号"""
        signals = []
        for sig in self._iter_signal_details(fti, latest_key='latest'):
            signals.append(ArbitrationSignal(
                signal_type='fti',
                date=self._get_signal_field(sig, 'date'),
                direction='bearish',
                confidence=self._signal_confidence(sig, 0.75),
                strength=self._get_signal_field(sig, 'volume_ratio'),
                raw_data={'fti': self._dump_signal(sig)}
            ))
        return signals

    def _calculate_spring_confidence(self, spring_signal: Any) -> float:
        """计算Spring信号的置信度"""
        confidence = 0.5  # 基础置信度

        # 根据收回天数调整
        if hasattr(spring_signal, 'recovery_days'):
            days = spring_signal.recovery_days
            if days <= 3:
                confidence += 0.3
            elif days <= 7:
                confidence += 0.15
            else:
                confidence -= 0.1

        # 根据量比调整
        if hasattr(spring_signal, 'volume_ratio'):
            vol_ratio = spring_signal.volume_ratio
            if vol_ratio > 2.0:
                confidence += 0.15
            elif vol_ratio > 1.5:
                confidence += 0.05

        # 根据强度调整
        if hasattr(spring_signal, 'strength'):
            if spring_signal.strength == 'strong':
                confidence += 0.1
            elif spring_signal.strength == 'weak':
                confidence -= 0.15

        return min(max(confidence, 0.0), 1.0)

    def _detect_conflicts(self, signals: List[ArbitrationSignal]) -> List[Tuple[ArbitrationSignal, ArbitrationSignal]]:
        """检测冲突的信号对"""
        conflicts = []

        for i, sig1 in enumerate(signals):
            for sig2 in signals[i+1:]:
                # 检查是否为相反方向的信号
                if sig1.direction != sig2.direction:
                    conflicts.append((sig1, sig2))

        return conflicts

    def _resolve_conflicts(
        self,
        all_signals: List[ArbitrationSignal],
        conflicts: List[Tuple[ArbitrationSignal, ArbitrationSignal]],
        events: Dict[str, Any]
    ) -> ArbitrationResult:
        """
        解决信号冲突

        核心逻辑：
        1. 时间优先：新信号通常优于旧信号（反映市场最新变化）
        2. 优先级：某些信号类型在特定上下文中更可靠
        3. 强度：信号强度（置信度、量能等）越高越可靠
        4. 市场结构：结合整体市场结构判断
        """

        if not conflicts:
            return ArbitrationResult(
                has_conflict=False,
                arbitration_reason="无冲突需要解决"
            )

        # 收集所有冲突信号（使用列表而非set，因为ArbitrationSignal不可哈希）
        conflicting_signals_set = []
        seen_ids = set()
        for sig1, sig2 in conflicts:
            # 使用id来避免重复
            if id(sig1) not in seen_ids:
                conflicting_signals_set.append(sig1)
                seen_ids.add(id(sig1))
            if id(sig2) not in seen_ids:
                conflicting_signals_set.append(sig2)
                seen_ids.add(id(sig2))

        conflicting_signals = conflicting_signals_set

        # 仲裁逻辑
        dominant_signal, rejected_signals, reason, suggested_phase = self._apply_arbitration_rules(
            conflicting_signals, events
        )

        # 计算置信度调整系数
        confidence_adjustment = self._calculate_confidence_adjustment(
            dominant_signal, rejected_signals
        )

        return ArbitrationResult(
            has_conflict=True,
            conflicting_signals=conflicting_signals,
            dominant_signal=dominant_signal,
            rejected_signals=rejected_signals,
            arbitration_reason=reason,
            suggested_phase=suggested_phase,
            phase_adjustment=f"基于信号仲裁，阶段调整为{suggested_phase}",
            confidence_adjustment=confidence_adjustment
        )

    def _apply_arbitration_rules(
        self,
        signals: List[ArbitrationSignal],
        events: Dict[str, Any]
    ) -> Tuple[Optional[ArbitrationSignal], List[ArbitrationSignal], str, Optional[str]]:
        """
        应用仲裁规则

        规则优先级：
        1. 时间规则：最新信号优先
        2. 结构规则：符合当前市场结构的信号优先
        3. 强度规则：高置信度、高强度的信号优先
        """

        if len(signals) < 2:
            return signals[0] if signals else None, [], "只有一个信号，无需仲裁", None

        # 按日期排序（最新的在前）
        sorted_by_date = sorted(signals, key=lambda x: self._parse_date(x.date), reverse=True)

        # 获取最新和最旧的信号
        newest = sorted_by_date[0]
        oldest = sorted_by_date[-1]

        # 计算时间差
        newest_date = self._parse_date(newest.date)
        oldest_date = self._parse_date(oldest.date)
        time_diff = (newest_date - oldest_date).days if newest_date and oldest_date else 0

        # === 规则1: Spring vs LPSY 特殊处理 ===
        spring_signals = [s for s in signals if s.signal_type == 'spring']
        lpsy_signals = [s for s in signals if s.signal_type == 'lpsy']

        if spring_signals and lpsy_signals:
            s_sig = spring_signals[0]
            l_sig = lpsy_signals[0]
            s_date = self._parse_date(s_sig.date)
            l_date = self._parse_date(l_sig.date)
            pair_diff = abs((l_date - s_date).days) if s_date and l_date else 0
            return self._arbitrate_spring_lpsy(s_sig, l_sig, pair_diff)

        # === 规则1b: Spring vs Upthrust 特殊处理 ===
        upthrust_signals = [s for s in signals if s.signal_type == 'upthrust']
        if spring_signals and upthrust_signals:
            s_sig = spring_signals[0]
            u_sig = upthrust_signals[0]
            s_date = self._parse_date(s_sig.date)
            u_date = self._parse_date(u_sig.date)
            pair_diff = abs((u_date - s_date).days) if s_date and u_date else 0
            return self._arbitrate_spring_upthrust(s_sig, u_sig, pair_diff)

        # === 规则1c: JOC vs SOW（派发语境 SOW 优先）===
        joc_signals = [s for s in signals if s.signal_type == 'joc']
        sow_signals = [s for s in signals if s.signal_type == 'sow']
        if joc_signals and sow_signals:
            j_sig = joc_signals[0]
            s_sig = sow_signals[0]
            j_date = self._parse_date(j_sig.date)
            s_date = self._parse_date(s_sig.date)
            pair_diff = abs((s_date - j_date).days) if j_date and s_date else 0
            return self._arbitrate_joc_sow(j_sig, s_sig, pair_diff, events)

        # === 规则1d: JOC vs FTI（突破方向互斥）===
        fti_signals = [s for s in signals if s.signal_type == 'fti']
        if joc_signals and fti_signals:
            j_sig = joc_signals[0]
            f_sig = fti_signals[0]
            j_date = self._parse_date(j_sig.date)
            f_date = self._parse_date(f_sig.date)
            pair_diff = abs((f_date - j_date).days) if j_date and f_date else 0
            return self._arbitrate_joc_fti(j_sig, f_sig, pair_diff, events)

        # === 规则1e: SOW vs FTI（派发 C→D：FTI 优先）===
        if sow_signals and fti_signals:
            s_sig = sow_signals[0]
            f_sig = fti_signals[0]
            s_date = self._parse_date(s_sig.date)
            f_date = self._parse_date(f_sig.date)
            pair_diff = abs((f_date - s_date).days) if s_date and f_date else 0
            return self._arbitrate_sow_fti(s_sig, f_sig, pair_diff, events)

        # === 规则1f: SOS vs JOC（吸筹 C→D：JOC 优先）===
        sos_signals = [s for s in signals if s.signal_type == 'sos']
        if sos_signals and joc_signals:
            o_sig = sos_signals[0]
            j_sig = joc_signals[0]
            o_date = self._parse_date(o_sig.date)
            j_date = self._parse_date(j_sig.date)
            pair_diff = abs((j_date - o_date).days) if o_date and j_date else 0
            return self._arbitrate_sos_joc(o_sig, j_sig, pair_diff, events)

        # === 规则2: 时间优先规则 ===
        # 如果时间差超过30天，最新信号优先
        if time_diff > 30:
            rejected = [s for s in signals if s != newest]
            return newest, rejected, f"时间优先：{newest.signal_type}信号更新（{time_diff}天前），旧信号失效", None

        # === 规则3: 信号优先级规则 ===
        # 按优先级排序
        sorted_by_priority = sorted(
            signals,
            key=lambda x: self.SIGNAL_PRIORITY.get(x.signal_type, 5),
            reverse=True
        )

        highest_priority = sorted_by_priority[0]
        if len(sorted_by_priority) > 1 and \
           self.SIGNAL_PRIORITY.get(highest_priority.signal_type, 5) > \
           self.SIGNAL_PRIORITY.get(sorted_by_priority[1].signal_type, 5):
            rejected = [s for s in signals if s != highest_priority]
            return highest_priority, rejected, \
                f"优先级：{highest_priority.signal_type}信号优先级更高", None

        # === 规则4: 强度规则 ===
        # 按置信度排序
        sorted_by_confidence = sorted(signals, key=lambda x: x.confidence, reverse=True)
        highest_conf = sorted_by_confidence[0]

        if len(sorted_by_confidence) > 1 and \
           highest_conf.confidence > sorted_by_confidence[1].confidence * 1.3:
            rejected = [s for s in signals if s != highest_conf]
            return highest_conf, rejected, \
                f"强度：{highest_conf.signal_type}信号置信度显著更高（{highest_conf.confidence:.2f} vs {sorted_by_confidence[1].confidence:.2f}）", None

        # === 默认规则：最新信号优先 ===
        rejected = [s for s in signals if s != newest]
        return newest, rejected, \
            f"默认：{newest.signal_type}信号最新，市场可能已转向", None

    def _arbitrate_spring_lpsy(
        self,
        spring: ArbitrationSignal,
        lpsy: ArbitrationSignal,
        time_diff: int
    ) -> Tuple[ArbitrationSignal, List[ArbitrationSignal], str, str]:
        """
        Spring vs LPSY 仲裁逻辑

        这是威科夫分析中最关键的冲突：
        - Spring：看涨信号，通常出现在吸筹区
        - LPSY：看跌信号，通常出现在派发区

        仲裁原则：
        1. 如果LPSY在Spring之后出现，说明Spring可能失效
        2. 如果时间差很短（<7天），可能是市场震荡，需要谨慎
        3. 如果时间差很长（>30天），市场可能已完成吸筹并进入派发
        """
        spring_date = self._parse_date(spring.date)
        lpsy_date = self._parse_date(lpsy.date)

        if not spring_date or not lpsy_date:
            # 无法比较日期，使用置信度
            if lpsy.confidence > spring.confidence:
                rejected = [spring]
                return lpsy, rejected, \
                    f"LPSY置信度更高（{lpsy.confidence:.2f} > {spring.confidence:.2f}）", \
                    "Distribution Phase C/D"
            else:
                rejected = [lpsy]
                return spring, rejected, \
                    f"Spring置信度更高（{spring.confidence:.2f} > {lpsy.confidence:.2f}）", \
                    "Accumulation Phase C"

        # 判断时间顺序
        if time_diff == 0:
            # 同一天出现，使用优先级规则
            # LPSY优先级(9) > Spring优先级(8)
            rejected = [spring]
            return lpsy, rejected, \
                f"信号同日出现，LPSY优先级更高（{self.SIGNAL_PRIORITY['lpsy']} > {self.SIGNAL_PRIORITY['spring']}）", \
                "Distribution Phase C"
        elif lpsy_date > spring_date:
            # LPSY更新
            if time_diff <= 7:
                # 时间差很短，可能是假突破
                rejected = [lpsy]
                return spring, rejected, \
                    f"时间间隔短（{time_diff}天），LPSY可能是假信号，维持Spring判断", \
                    "Accumulation Phase C（需观察）"
            elif time_diff <= 30:
                # 时间中等，降低置信度
                rejected = [spring]
                return lpsy, rejected, \
                    f"LPSY出现在Spring后{time_diff}天，反弹无力，市场可能转向派发", \
                    "Distribution Phase C"
            else:
                # 时间很长，市场确实转向
                rejected = [spring]
                return lpsy, rejected, \
                    f"LPSY出现在Spring后{time_diff}天，Spring已失效，市场进入派发", \
                    "Distribution Phase D"
        else:
            # Spring更新
            if time_diff <= 7:
                rejected = [lpsy]
                return spring, rejected, \
                    f"时间间隔短（{time_diff}天），LPSY可能是之前的信号，Spring更新", \
                    "Accumulation Phase C"
            else:
                rejected = [lpsy]
                return spring, rejected, \
                    f"Spring出现在LPSY后{time_diff}天，市场可能重新进入吸筹", \
                    "Accumulation Phase C"

    def _phase_context(self, events: Dict[str, Any]) -> str:
        ctx = events.get('_phase_context') or events.get('phase_context') or ''
        return str(ctx)

    def _is_distribution_context(self, events: Dict[str, Any]) -> bool:
        ctx = self._phase_context(events)
        if 'Distribution' in ctx:
            return True
        climax = events.get('_climax_type')
        return climax in ('buying_climax', 'bc')

    def _is_accumulation_context(self, events: Dict[str, Any]) -> bool:
        ctx = self._phase_context(events)
        if 'Accumulation' in ctx:
            return True
        climax = events.get('_climax_type')
        return climax in ('selling_climax', 'sc')

    def _arbitrate_joc_sow(
        self,
        joc: ArbitrationSignal,
        sow: ArbitrationSignal,
        time_diff: int,
        events: Dict[str, Any],
    ) -> Tuple[ArbitrationSignal, List[ArbitrationSignal], str, Optional[str]]:
        """
        JOC vs SOW：派发语境下 SOW 优先（JOC 可能是 BC 过载或假突破）。
        """
        if self._is_distribution_context(events):
            return sow, [joc], \
                "派发语境：SOW 优先于 JOC（JOC 可能是 BC 过载或假突破）", \
                "Distribution Phase C/D"
        if self._is_accumulation_context(events):
            return joc, [sow], \
                "吸筹语境：JOC 优先于 SOW（SOW 可能是 TR 内正常回调）", \
                "Accumulation Phase D"

        joc_date = self._parse_date(joc.date)
        sow_date = self._parse_date(sow.date)
        if joc_date and sow_date:
            if sow_date > joc_date and time_diff <= 14:
                return sow, [joc], \
                    f"SOW 在 JOC 后 {time_diff} 天内出现，突破可能失败", \
                    "Distribution Phase C"
            if joc_date > sow_date and time_diff <= 14:
                return joc, [sow], \
                    f"JOC 在 SOW 后 {time_diff} 天内出现，需求可能重新主导", \
                    "Accumulation Phase D"

        if sow.confidence > joc.confidence * 1.1:
            return sow, [joc], \
                f"SOW 置信度更高（{sow.confidence:.2f} vs {joc.confidence:.2f}）", \
                "Distribution Phase C"
        return joc, [sow], \
            f"JOC 置信度更高（{joc.confidence:.2f} vs {sow.confidence:.2f}）", \
            "Accumulation Phase D"

    def _arbitrate_joc_fti(
        self,
        joc: ArbitrationSignal,
        fti: ArbitrationSignal,
        time_diff: int,
        events: Dict[str, Any],
    ) -> Tuple[ArbitrationSignal, List[ArbitrationSignal], str, Optional[str]]:
        """
        JOC vs FTI：突破方向互斥，按阶段语境裁决。
        """
        if self._is_distribution_context(events):
            return fti, [joc], \
                "派发语境：FTI 优先于 JOC（方向性突破应看冰层）", \
                "Distribution Phase D"
        if self._is_accumulation_context(events):
            return joc, [fti], \
                "吸筹语境：JOC 优先于 FTI（方向性突破应看小溪）", \
                "Accumulation Phase D"

        joc_date = self._parse_date(joc.date)
        fti_date = self._parse_date(fti.date)
        if joc_date and fti_date:
            if fti_date > joc_date:
                return fti, [joc], \
                    f"FTI 在 JOC 后 {time_diff} 天出现，派发突破可能更可靠", \
                    "Distribution Phase D"
            return joc, [fti], \
                f"JOC 在 FTI 后 {time_diff} 天出现，吸筹突破可能更可靠", \
                "Accumulation Phase D"

        if fti.confidence > joc.confidence:
            return fti, [joc], "FTI 置信度更高", "Distribution Phase D"
        return joc, [fti], "JOC 置信度更高", "Accumulation Phase D"

    def _arbitrate_sow_fti(
        self,
        sow: ArbitrationSignal,
        fti: ArbitrationSignal,
        time_diff: int,
        events: Dict[str, Any],
    ) -> Tuple[ArbitrationSignal, List[ArbitrationSignal], str, Optional[str]]:
        """
        SOW vs FTI：派发侧 C→D 硬约束，FTI 优先于 SOW（对称 JOC > SOS）。
        """
        if self._is_distribution_context(events):
            sow_date = self._parse_date(sow.date)
            fti_date = self._parse_date(fti.date)
            if sow_date and fti_date and sow_date > fti_date and time_diff <= 14:
                return sow, [fti], \
                    f"SOW 在 FTI 后 {time_diff} 天内再现，冰层突破可能失败", \
                    "Distribution Phase C"
            return fti, [sow], \
                "派发语境：FTI 为 Phase D 确认，优先于 SOW", \
                "Distribution Phase D"

        sow_date = self._parse_date(sow.date)
        fti_date = self._parse_date(fti.date)
        if sow_date and fti_date and fti_date > sow_date:
            return fti, [sow], \
                f"FTI 在 SOW 后 {time_diff} 天出现，派发突破确认", \
                "Distribution Phase D"
        if sow_date and fti_date and sow_date > fti_date and time_diff <= 7:
            return sow, [fti], \
                f"SOW 更新（{time_diff} 天），弱势可能重新主导", \
                "Distribution Phase C"

        if fti.confidence >= sow.confidence:
            return fti, [sow], \
                f"FTI 优先级更高（{fti.confidence:.2f} vs {sow.confidence:.2f}）", \
                "Distribution Phase D"
        return sow, [fti], \
            f"SOW 置信度更高（{sow.confidence:.2f} vs {fti.confidence:.2f}）", \
            "Distribution Phase C"

    def _arbitrate_sos_joc(
        self,
        sos: ArbitrationSignal,
        joc: ArbitrationSignal,
        time_diff: int,
        events: Dict[str, Any],
    ) -> Tuple[ArbitrationSignal, List[ArbitrationSignal], str, Optional[str]]:
        """
        SOS vs JOC：吸筹侧 C→D 硬约束，JOC 优先于 SOS（对称 FTI > SOW）。
        """
        if self._is_accumulation_context(events):
            sos_date = self._parse_date(sos.date)
            joc_date = self._parse_date(joc.date)
            if sos_date and joc_date and sos_date > joc_date and time_diff <= 14:
                return sos, [joc], \
                    f"SOS 在 JOC 后 {time_diff} 天内再现，小溪突破可能失败", \
                    "Accumulation Phase C"
            return joc, [sos], \
                "吸筹语境：JOC 为 Phase D 确认，优先于 SOS", \
                "Accumulation Phase D"

        sos_date = self._parse_date(sos.date)
        joc_date = self._parse_date(joc.date)
        if sos_date and joc_date and joc_date > sos_date:
            return joc, [sos], \
                f"JOC 在 SOS 后 {time_diff} 天出现，吸筹突破确认", \
                "Accumulation Phase D"
        if sos_date and joc_date and sos_date > joc_date and time_diff <= 7:
            return sos, [joc], \
                f"SOS 更新（{time_diff} 天），强势可能重新主导", \
                "Accumulation Phase C"

        if joc.confidence >= sos.confidence:
            return joc, [sos], \
                f"JOC 优先级更高（{joc.confidence:.2f} vs {sos.confidence:.2f}）", \
                "Accumulation Phase D"
        return sos, [joc], \
            f"SOS 置信度更高（{sos.confidence:.2f} vs {joc.confidence:.2f}）", \
            "Accumulation Phase C"

    def _arbitrate_spring_upthrust(
        self,
        spring: ArbitrationSignal,
        upthrust: ArbitrationSignal,
        time_diff: int
    ) -> Tuple[ArbitrationSignal, List[ArbitrationSignal], str, Optional[str]]:
        """
        Spring vs Upthrust 仲裁：同区间内的方向性测试冲突。
        """
        spring_date = self._parse_date(spring.date)
        upthrust_date = self._parse_date(upthrust.date)

        if not spring_date or not upthrust_date:
            if upthrust.confidence > spring.confidence:
                return upthrust, [spring], "Upthrust 置信度更高", "Distribution Phase C"
            return spring, [upthrust], "Spring 置信度更高", "Accumulation Phase C"

        if upthrust_date > spring_date:
            if time_diff <= 7:
                return spring, [upthrust], f"间隔{time_diff}天，Upthrust 可能是假信号，维持 Spring", "Accumulation Phase C（需观察）"
            return upthrust, [spring], f"Upthrust 在 Spring 后 {time_diff} 天，供应可能主控", "Distribution Phase C"
        if time_diff <= 7:
            return upthrust, [spring], f"间隔{time_diff}天，Spring 可能是假信号，维持 Upthrust", "Distribution Phase C（需观察）"
        return spring, [upthrust], f"Spring 在 Upthrust 后 {time_diff} 天，需求可能重新主导", "Accumulation Phase C"

    def _calculate_confidence_adjustment(
        self,
        dominant: ArbitrationSignal,
        rejected: List[ArbitrationSignal]
    ) -> float:
        """
        计算置信度调整系数

        如果存在信号冲突，即使进行了仲裁，也应该降低整体置信度
        """
        if not rejected:
            return 1.0

        # 基础调整系数
        adjustment = 0.85

        # 如果被拒绝的信号置信度也很高，进一步降低
        high_conf_rejected = [r for r in rejected if r.confidence > 0.7]
        if high_conf_rejected:
            adjustment *= 0.8

        # 如果冲突信号数量多，进一步降低
        if len(rejected) > 2:
            adjustment *= 0.9

        return max(adjustment, 0.5)  # 最低不低于0.5

    def _parse_date(self, date_val: Any) -> Optional[datetime]:
        """统一日期解析 — 委托至共享 TypeConverter"""
        from .utils import TypeConverter
        ts = TypeConverter.parse_date_naive(date_val)
        if ts is not None:
            return ts.to_pydatetime()
        return None

    def get_arbitration_summary(self, result: ArbitrationResult) -> str:
        """生成仲裁结果的文字摘要"""
        if not result.has_conflict:
            return "无信号冲突"

        lines = [
            "⚠️ 信号冲突仲裁结果：",
            f"主导信号: {result.dominant_signal.signal_type if result.dominant_signal else '无'}",
            f"仲裁理由: {result.arbitration_reason}"
        ]

        if result.suggested_phase:
            lines.append(f"建议阶段: {result.suggested_phase}")

        if result.rejected_signals:
            rejected_names = [s.signal_type for s in result.rejected_signals]
            lines.append(f"被拒绝信号: {', '.join(rejected_names)}")

        if result.confidence_adjustment < 1.0:
            lines.append(f"置信度调整: ×{result.confidence_adjustment:.2f}")

        return "\n".join(lines)
