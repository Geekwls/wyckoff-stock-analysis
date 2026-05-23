"""
信号提取工具类
用于从事件检测结果中提取和验证信号
"""
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import numpy as np
from ..config.settings import WyckoffThresholds
from .enums import WyckoffPhase
from .utils import PhaseAdapter

logger = logging.getLogger(__name__)


# ── 单一事实源（Single Source of Truth）辅助函数 ─────────────────────
# 报告 / 三大定律 / 轻量 JSON / 批量筛选 均通过以下工具读取
# PhaseCoordinator.collect_all_events() → identify_phase()['events_detected']，
# 禁止在下游重复调用 detect_spring / detect_sos 等独立检测路径。


def event_to_dict(obj: Any, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """将 Pydantic 模型或 dict 统一转为 dict，供报告/定律层读取。"""
    if obj is None:
        return default if default is not None else {'detected': False}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, 'dict'):
        return obj.dict()
    return default if default is not None else {'detected': False}


def get_events_from_phase(phase_result: Any) -> Any:
    """从 identify_phase() 结果中提取 EventsModel（或兼容 dict）。"""
    if phase_result is None:
        return None
    if isinstance(phase_result, dict):
        return phase_result.get('events_detected')
    return getattr(phase_result, 'events_detected', None)


def get_cached_phase_result(pattern_detector: Any) -> Any:
    """读取 pattern_detector 上缓存的 identify_phase 结果，避免定律/报告重复检测。"""
    if pattern_detector is None:
        return None
    cached = getattr(pattern_detector, '_cached_phase_result', None)
    if cached is not None:
        return cached
    result = pattern_detector.identify_phase()
    pattern_detector._cached_phase_result = result
    return result


def set_cached_phase_result(pattern_detector: Any, phase_result: Any) -> None:
    """报告主链写入 phase 缓存，供三大定律等下游复用。"""
    if pattern_detector is not None:
        pattern_detector._cached_phase_result = phase_result


class SignalExtractor:
    """从威科夫事件检测结果中提取信号的工具类"""

    @staticmethod
    def _get(obj: Any, key: str, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @classmethod
    def _detected(cls, obj: Any) -> bool:
        return bool(cls._get(obj, 'detected', False))

    @classmethod
    def is_formal_lps(cls, event: Any) -> bool:
        """
        正式 LPS：signal_type=='lps'（或 legacy 无 type 时 trust detected）。
        support_test / pullback 等观察信号不计入交易/阶段升级。
        """
        if not cls._detected(event):
            return False
        latest = cls._latest(event)
        signal_type = cls._get(latest, 'signal_type') if latest else cls._get(event, 'signal_type')
        if signal_type is None:
            phase_ctx = cls._get(event, 'phase_context') or {}
            if isinstance(phase_ctx, dict) and phase_ctx.get('has_lps_qualification'):
                return True
            return True  # legacy/test payloads without signal_type
        return signal_type == 'lps'

    @classmethod
    def has_lps_observation(cls, event: Any) -> bool:
        """任意 LPS 形态（含 support_test），供报告展示观察项。"""
        if cls.is_formal_lps(event):
            return True
        if cls._get(event, 'observation_detected'):
            return True
        signals = cls._get(event, 'signals') or []
        return len(signals) > 0

    @classmethod
    def is_formal_lpsy(cls, event: Any) -> bool:
        """正式 LPSY：与 detect_lpsy 出口一致（detected 即 formal）。"""
        if not cls._detected(event):
            return False
        latest = cls._latest(event)
        signal_type = cls._get(latest, 'signal_type') if latest else cls._get(event, 'signal_type')
        if signal_type is None:
            return True
        return signal_type == 'lpsy'

    @classmethod
    def _latest(cls, obj: Any):
        for key in ('latest', 'latest_spring', 'latest_upthrust'):
            latest = cls._get(obj, key)
            if latest:
                return latest
        signals = cls._get(obj, 'signals', []) or []
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
    def extract_signals(phase_result: Dict[str, Any]) -> Dict[str, bool]:
        """
        从阶段识别结果中提取所有信号状态

        Args:
            phase_result: identify_phase() 或 identify_phase_with_rs() 的返回结果

        Returns:
            包含各信号检测状态的字典
        """
        events = phase_result.get('events_detected') if isinstance(phase_result, dict) else getattr(phase_result, 'events_detected', None)
        if not events:
            events = phase_result

        spring_upthrust = SignalExtractor._get(events, 'spring_upthrust') or {}
        sos_sow = SignalExtractor._get(events, 'sos_sow') or {}
        lps_lpsy = SignalExtractor._get(events, 'lps_lpsy') or {}

        lps_data = SignalExtractor._get(events, 'lps')
        lpsy_data = SignalExtractor._get(events, 'lpsy')
        if not lps_data and isinstance(lps_lpsy, dict):
            lps_data = lps_lpsy.get('lps')
        if not lpsy_data and isinstance(lps_lpsy, dict):
            lpsy_data = lps_lpsy.get('lpsy')

        has_spring = (SignalExtractor._get(spring_upthrust, '_type') or SignalExtractor._get(spring_upthrust, 'type_')) == 'spring'
        has_upthrust = (SignalExtractor._get(spring_upthrust, '_type') or SignalExtractor._get(spring_upthrust, 'type_')) == 'upthrust'
        has_sos = (SignalExtractor._get(sos_sow, '_type') or SignalExtractor._get(sos_sow, 'type_')) == 'sos'
        has_sow = (SignalExtractor._get(sos_sow, '_type') or SignalExtractor._get(sos_sow, 'type_')) == 'sow'
        has_lps = SignalExtractor.is_formal_lps(lps_data)
        has_lpsy = SignalExtractor.is_formal_lpsy(lpsy_data)

        return {
            'has_spring': has_spring,
            'has_upthrust': has_upthrust,
            'has_sos': has_sos,
            'has_sow': has_sow,
            'has_lps': has_lps,
            'has_lpsy': has_lpsy,
        }

    @staticmethod
    def extract_accumulation_signals(phase_result: Dict[str, Any]) -> Dict[str, bool]:
        """
        提取积累期相关信号（Spring, SOS, LPS）

        Args:
            phase_result: 阶段识别结果

        Returns:
            包含积累期信号的字典
        """
        signals = SignalExtractor.extract_signals(phase_result)
        return {
            'has_spring': signals['has_spring'],
            'has_sos': signals['has_sos'],
            'has_lps': signals['has_lps'],
        }

    @staticmethod
    def extract_distribution_signals(phase_result: Dict[str, Any]) -> Dict[str, bool]:
        """
        提取派发期相关信号（Upthrust, SOW, LPSY）

        Args:
            phase_result: 阶段识别结果

        Returns:
            包含派发期信号的字典
        """
        signals = SignalExtractor.extract_signals(phase_result)
        return {
            'has_upthrust': signals['has_upthrust'],
            'has_sow': signals['has_sow'],
            'has_lpsy': signals['has_lpsy'],
        }

    @staticmethod
    def calculate_weighted_score(phase_result: Dict[str, Any], thresholds: WyckoffThresholds = None) -> float:
        """
        计算加权信号强度得分 (0-100)
        包含：信号质量分、时间衰减、多空冲突惩罚
        """
        if thresholds is None:
            thresholds = WyckoffThresholds()

        events = phase_result.get('events_detected') if isinstance(phase_result, dict) else getattr(phase_result, 'events_detected', None)
        if not events:
            events = phase_result

        if not events:
            return 0.0

        base_score = 0.0
        latest_date = None

        # 1. 计算信号质量分
        weights = thresholds.QUALITY_WEIGHTS

        # 处理主要信号
        important_signals = [
            ('spring_upthrust', 40),
            ('sos_sow', 35),
            ('lps_lpsy', 25)
        ]

        bullish_count = 0
        bearish_count = 0

        for key, max_weight in important_signals:
            info = SignalExtractor._get(events, key)

            if not info:
                # 兼容：新 EventsModel 已废弃 lps_lpsy，lps/lpsy 单独存放。
                if key == 'lps_lpsy':
                    lps = SignalExtractor._get(events, 'lps')
                    lpsy = SignalExtractor._get(events, 'lpsy')
                    if SignalExtractor.is_formal_lps(lps):
                        info = lps
                    elif SignalExtractor.is_formal_lpsy(lpsy):
                        info = lpsy
                if not info:
                    continue

            # 统一提取具体的事件实体和类型
            if isinstance(info, dict):
                data = info.get('data') or info
                sig_type = info.get('_type') or info.get('type', '')
            else:
                # 强类型，可能是 DualEventModel 或具体的 LpsModel/LpsyModel
                if SignalExtractor._get(info, 'type_'):
                    sig_type = SignalExtractor._get(info, 'type_')
                    data = SignalExtractor._get(info, 'data')
                else:
                    sig_type = 'lps' if key == 'lps_lpsy' else key
                    data = info

            if not data or not SignalExtractor._detected(data): continue

            # 判断方向供冲突检测
            if sig_type in ['spring', 'sos', 'lps']:
                bullish_count += 1
            elif sig_type in ['upthrust', 'sow', 'lpsy']:
                bearish_count += 1

            # 计算该信号的质量因子 (0.5 - 1.2)
            quality_factor = 0.8 # 默认基础分

            # 考虑成交量比 (Volume Ratio)
            latest = SignalExtractor._latest(data) or data
            vol_ratio = SignalExtractor._num(
                SignalExtractor._get(data, 'volume_ratio', SignalExtractor._get(latest, 'volume_ratio', 1.0)),
                1.0
            )
            if vol_ratio > 2.0: quality_factor += weights['volume_ratio']
            elif vol_ratio > 1.5: quality_factor += weights['volume_ratio'] * 0.5

            # 考虑置信度 (Confidence)
            conf = SignalExtractor._num(
                SignalExtractor._get(data, 'confidence', SignalExtractor._get(latest, 'confidence', 0.5)),
                0.5
            )
            quality_factor += (conf - 0.5) * weights['confidence']

            # 考虑日期 (时间衰减)
            sig_date = SignalExtractor._get(data, 'date', SignalExtractor._get(latest, 'date'))
            if sig_date:
                if isinstance(sig_date, str):
                    try:
                        sig_date = datetime.strptime(sig_date, '%Y-%m-%d')
                    except Exception:
                        pass

                if isinstance(sig_date, datetime):
                    if latest_date is None or sig_date > latest_date:
                        latest_date = sig_date

                    # 时间衰减因子
                    days_ago = (datetime.now() - sig_date).days
                    decay = np.exp(-0.693 * max(0, days_ago) / thresholds.TIME_DECAY_HALF_LIFE)
                    quality_factor *= decay

            base_score += max_weight * min(quality_factor, 1.5)

        # 2. 冲突惩罚
        if bullish_count > 0 and bearish_count > 0:
            base_score -= thresholds.CONFLICT_PENALTY

        # 3. 基础置信度加成
        phase_conf = phase_result.get('confidence') if isinstance(phase_result, dict) else getattr(phase_result, 'confidence', 0.0)
        phase_conf = phase_conf or 0.0
        base_score += phase_conf * 10

        return round(max(0.0, min(base_score, 100.0)), 2)

    @staticmethod
    def calculate_signal_strength(signals: Dict[str, bool]) -> int:
        """保持兼容性的旧方法"""
        return sum(1 for v in signals.values() if v)

    @staticmethod
    def get_effective_phase(phase_result: Any) -> str:
        """
        用户可见权威阶段（Phase 21）。
        优先 effective_phase → 已合并 phase → coordinator_phase。
        """
        if not isinstance(phase_result, dict):
            return str(phase_result) if phase_result else 'Unknown'
        for key in ('effective_phase', 'phase', 'coordinator_phase'):
            val = phase_result.get(key)
            if val:
                return str(val)
        return 'Unknown'

    @staticmethod
    def get_phase_string(phase_result: Dict[str, Any]) -> str:
        """
        从阶段识别结果中获取阶段字符串

        Args:
            phase_result: 阶段识别结果

        Returns:
            阶段字符串
        """
        return SignalExtractor.get_effective_phase(phase_result)

    @staticmethod
    def is_accumulation_phase(phase_str: str) -> bool:
        """判断是否为积累期"""
        return PhaseAdapter.is_accumulation(phase_str)

    @staticmethod
    def is_distribution_phase(phase_str: str) -> bool:
        """判断是否为派发期"""
        return PhaseAdapter.is_distribution(phase_str)

    @staticmethod
    def is_markup_phase(phase_str: str) -> bool:
        """判断是否为上涨期"""
        return PhaseAdapter.is_markup(phase_str)

    @staticmethod
    def is_markdown_phase(phase_str: str) -> bool:
        """判断是否为下跌期"""
        return PhaseAdapter.is_markdown(phase_str)

    @staticmethod
    def is_late_stage(phase_enum: WyckoffPhase) -> bool:
        """判断是否为后期阶段 (C/D)"""
        return PhaseAdapter.is_late_stage(phase_enum)

    @classmethod
    def get_event(cls, events: Any, key: str, default: Any = None) -> Any:
        """从 EventsModel 或 dict 读取单个事件字段。"""
        if events is None:
            return default
        return cls._get(events, key, default)

    @classmethod
    def get_event_dict(cls, events: Any, key: str) -> Dict[str, Any]:
        """读取事件并转为 dict 视图；将 latest/latest_spring 字段提升到顶层供报告/评分读取。"""
        event_dict = event_to_dict(cls.get_event(events, key))
        # P0 契约修复：SOS/SOW/Spring 模型化后核心字段在 latest 内，需扁平化避免评分/报告读空
        latest = cls._latest(event_dict)
        if isinstance(latest, dict):
            for field, value in latest.items():
                event_dict.setdefault(field, value)
        return event_dict

    @classmethod
    def build_report_context(cls, phase_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 identify_phase() 一次性构建报告/JSON 所需事件上下文。
        所有核心威科夫事件均来自 events_detected，避免重复 detect。
        """
        events = get_events_from_phase(phase_result)
        trading_range = cls.get_event_dict(events, 'trading_range')

        ctx = {
            'phase_result': phase_result,
            'events': events,
            'trading_range': trading_range,
            'spring': cls.get_event_dict(events, 'spring'),
            'upthrust': cls.get_event_dict(events, 'upthrust'),
            'sos': cls.get_event_dict(events, 'sos'),
            'sow': cls.get_event_dict(events, 'sow'),
            'lps': cls.get_event_dict(events, 'lps'),
            'lpsy': cls.get_event_dict(events, 'lpsy'),
            'joc': cls.get_event_dict(events, 'joc'),
            'fti': cls.get_event_dict(events, 'fti'),
            'ps': cls.get_event_dict(events, 'preliminary_support'),
            'psy': cls.get_event_dict(events, 'preliminary_supply'),
            'boring_res': cls.get_event_dict(events, 'boring_zone'),
            'vsa_menhongtao': cls.get_event_dict(events, 'vsa_menhongtao'),
            'dead_corner': cls.get_event_dict(events, 'dead_corner_breakout'),
            'arbitration_result': event_to_dict(cls.get_event(events, 'arbitration_result'), default=None),
            'breakout_analysis': event_to_dict(cls.get_event(events, 'breakout_analysis'), default=None),
        }
        if ctx['arbitration_result'] is None:
            ctx['arbitration_result'] = None
        if ctx['breakout_analysis'] is None:
            ctx['breakout_analysis'] = None
        return ctx

    @classmethod
    def suppress_bullish_signals(cls, ctx: Dict[str, Any]) -> None:
        """派发阶段屏蔽做多信号（就地修改 ctx 中的 dict 视图）。"""
        for key in ('joc', 'lps', 'spring'):
            obj = ctx.get(key)
            if isinstance(obj, dict):
                obj['detected'] = False

    @classmethod
    def apply_distribution_suppression(
        cls,
        ctx: Dict[str, Any],
        phase_result: Optional[Dict[str, Any]] = None,
        *,
        symbol: Optional[str] = None,
    ) -> bool:
        """
        派发阶段屏蔽做多信号；若已有效向上突破（非 UT）则保留 override。
        返回 True 表示已执行 suppression。
        """
        phase_result = phase_result or ctx.get('phase_result') or {}
        phase_str = cls.get_effective_phase(phase_result)
        from .utils import PhaseAdapter
        is_distribution = PhaseAdapter.is_distribution(phase_str)
        ctx['should_suppress_bullish'] = is_distribution

        breakout_analysis = ctx.get('breakout_analysis')
        trading_range = ctx.get('trading_range') or {}
        if is_distribution and breakout_analysis:
            ba = breakout_analysis if isinstance(breakout_analysis, dict) else event_to_dict(breakout_analysis)
            is_broken = trading_range.get('is_broken', False)
            direction = ba.get('direction', '')
            is_upthrust = ba.get('is_upthrust', False)
            if is_broken and direction == 'up' and not is_upthrust:
                ctx['should_suppress_bullish'] = False
                if symbol:
                    logger.info(
                        "Breakout override: upward breakout detected, NOT suppressing bullish signals "
                        "despite Distribution phase for %s",
                        symbol,
                    )

        if ctx['should_suppress_bullish']:
            cls.suppress_bullish_signals(ctx)
            if symbol:
                logger.warning(
                    "Detection contradiction: Distribution phase detected. "
                    "Bullish signals (JOC/LPS/Spring) suppressed for %s.",
                    symbol,
                )
            return True
        return False

    @classmethod
    def build_scoring_payload(cls, phase_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建报告 / orchestrator 共用的评分与交易计划输入。
        events_detected 经派发 suppression 后与报告展示一致。
        """
        ctx = cls.build_report_context(phase_result)
        cls.apply_distribution_suppression(ctx, phase_result)
        payload = cls.build_patterns_payload(ctx)

        result: Dict[str, Any] = dict(phase_result)
        result.update(payload)
        result['phase'] = cls.get_effective_phase(result)
        result['effective_phase'] = result['phase']
        result['should_suppress_bullish'] = ctx.get('should_suppress_bullish', False)
        for key in (
            'joc', 'fti', 'spring', 'upthrust', 'sos', 'sow', 'lps', 'lpsy', 'trading_range',
        ):
            if key in ctx:
                result[key] = ctx[key]
        return result

    @staticmethod
    def normalize_confidence(value: Any, default: float = 0.5) -> float:
        """统一置信度到 0–1（检测器可能返回 0–100 或 total_score）。"""
        num = SignalExtractor._num(value, default)
        if num > 1.0:
            num = num / 100.0
        return max(0.0, min(1.0, num))

    @classmethod
    def normalize_event_confidence(cls, event: Any, default: float = 0.5) -> float:
        """从事件 dict/model 读取并归一化 confidence（含 total_score 回退）。"""
        if event is None:
            return default
        for source in (event, cls._latest(event)):
            if not source:
                continue
            for key in ('confidence', 'total_score'):
                raw = cls._get(source, key)
                if raw is not None:
                    return cls.normalize_confidence(raw, default)
        return default

    @classmethod
    def _spring_lifecycle_failed(cls, spring_event: Any) -> bool:
        latest = cls._latest(spring_event)
        target = latest if latest else spring_event
        status = cls._get(target, 'lifecycle_status')
        return status == 'failed'

    @classmethod
    def _upthrust_lifecycle_failed(cls, upthrust_event: Any) -> bool:
        latest = cls._latest(upthrust_event)
        target = latest if latest else upthrust_event
        status = cls._get(target, 'lifecycle_status')
        return status == 'failed'

    @classmethod
    def build_patterns_payload(cls, ctx: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构建与报告展示一致的 patterns_payload。
        将 ctx 中经 suppression 修改后的事件 dict 覆盖回 events_detected，供评分/交易计划使用。
        """
        phase_result = ctx.get('phase_result') or {}
        events = ctx.get('events')
        if events is not None and hasattr(events, 'model_dump'):
            events_dict = events.model_dump()
        elif isinstance(events, dict):
            events_dict = dict(events)
        else:
            events_dict = {}

        overlay_map = {
            'spring': 'spring',
            'upthrust': 'upthrust',
            'sos': 'sos',
            'sow': 'sow',
            'lps': 'lps',
            'lpsy': 'lpsy',
            'joc': 'joc',
            'fti': 'fti',
            'trading_range': 'trading_range',
            'boring_res': 'boring_zone',
        }
        for ctx_key, events_key in overlay_map.items():
            val = ctx.get(ctx_key)
            if isinstance(val, dict):
                events_dict[events_key] = val

        eff_phase = cls.get_effective_phase(phase_result) if isinstance(phase_result, dict) else 'Unknown'
        payload: Dict[str, Any] = {
            'events_detected': events_dict,
            'phase': eff_phase,
            'effective_phase': eff_phase,
            'identifier_phase': phase_result.get('identifier_phase') if isinstance(phase_result, dict) else None,
            'coordinator_phase': phase_result.get('coordinator_phase') if isinstance(phase_result, dict) else None,
            'phase_source': phase_result.get('phase_source') if isinstance(phase_result, dict) else None,
            'sequence_validation': phase_result.get('sequence_validation'),
            'boring_zone': ctx.get('boring_res'),
            'dead_corner_breakout': ctx.get('dead_corner'),
        }
        if extra:
            payload.update(extra)
        return payload

    @classmethod
    def resolve_primary_signal(cls, pattern_results: Any) -> Tuple[str, str]:
        """从 patterns_payload / phase_info 解析主信号类型与方向。"""
        events = None
        if isinstance(pattern_results, dict):
            events = pattern_results.get('events_detected') or pattern_results
        else:
            events = pattern_results

        long_chain = ('joc', 'spring', 'sos', 'lps')
        short_chain = ('fti', 'upthrust', 'sow', 'lpsy')

        for key in long_chain:
            event = cls.get_event_dict(events, key) if events else {}
            if not event and isinstance(pattern_results, dict):
                event = pattern_results.get(key) or {}
            if cls._detected(event):
                if key == 'lps' and not cls.is_formal_lps(event):
                    continue
                if key == 'spring' and cls._spring_lifecycle_failed(event):
                    continue
                if key == 'spring':
                    joc_ev = cls.get_event_dict(events, 'joc') if events else {}
                    if not cls._detected(joc_ev):
                        if isinstance(pattern_results, dict):
                            joc_ev = pattern_results.get('joc') or {}
                        if not cls._detected(joc_ev):
                            continue
                return key, 'long'

        for key in short_chain:
            event = cls.get_event_dict(events, key) if events else {}
            if not event and isinstance(pattern_results, dict):
                event = pattern_results.get(key) or {}
            if cls._detected(event):
                if key == 'lpsy' and not cls.is_formal_lpsy(event):
                    continue
                if key == 'upthrust' and cls._upthrust_lifecycle_failed(event):
                    continue
                if key == 'upthrust':
                    fti_ev = cls.get_event_dict(events, 'fti') if events else {}
                    sow_ev = cls.get_event_dict(events, 'sow') if events else {}
                    if not cls._detected(fti_ev):
                        if isinstance(pattern_results, dict):
                            fti_ev = pattern_results.get('fti') or {}
                            sow_ev = pattern_results.get('sow') or sow_ev
                        if not cls._detected(fti_ev) and not cls._detected(sow_ev):
                            continue
                if key == 'lpsy':
                    fti_ev = cls.get_event_dict(events, 'fti') if events else {}
                    if not cls._detected(fti_ev):
                        if isinstance(pattern_results, dict):
                            fti_ev = pattern_results.get('fti') or {}
                        if not cls._detected(fti_ev):
                            continue
                return key, 'short'

        return 'none', 'neutral'

    @classmethod
    def extract_entry_anchor(cls, pattern_results: Any, direction: str) -> Dict[str, Any]:
        """
        从 events_detected 提取小时线/入场锚点（LPS/Creek/LPSY/Ice）。
        孟氏原则：做多锚定 LPS/JOC Creek，做空锚定 LPSY/FTI 冰层。
        """
        events = get_events_from_phase(pattern_results) if isinstance(pattern_results, dict) else pattern_results
        if events is None and isinstance(pattern_results, dict):
            events = pattern_results.get('events_detected') or pattern_results

        long_chain = (
            ('lps', ('support_level', 'price')),
            ('joc', ('creek_level',)),
            ('sos', ('breakthrough_level',)),
        )
        short_chain = (
            ('lpsy', ('resistance_level', 'price')),
            ('fti', ('ice_level',)),
            ('sow', ('breakdown_level',)),
        )
        chain = long_chain if direction == 'long' else short_chain

        for key, fields in chain:
            event = cls.get_event_dict(events, key) if events else {}
            if not event and isinstance(pattern_results, dict):
                event = pattern_results.get(key) or {}
            if not cls._detected(event):
                continue
            if key == 'lps' and not cls.is_formal_lps(event):
                continue
            if key == 'lpsy' and not cls.is_formal_lpsy(event):
                continue
            latest = cls._latest(event) or event
            for field in fields:
                raw = cls._get(latest, field) or cls._get(event, field)
                level = cls._num(raw, 0.0)
                if level > 0:
                    return {
                        'level': level,
                        'source': key.upper(),
                        'field': field,
                    }
        return {}
