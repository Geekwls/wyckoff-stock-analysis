import logging
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional
from .enums import MarketEnvironment, MarketSide, WyckoffPhase
from .utils import PhaseAdapter
from .signal_extractor import SignalExtractor
from ..schemas import (
    TradingPlanModel, StopLossModel, TargetsModel, 
    PositionSizingModel, RiskAdviceModel, RiskAdviceItem,
    SignalQualityModel
)
from ..config.settings import WyckoffConfig, WyckoffThresholds
from .strategy_decision_audit import StrategyDecisionAuditLog

logger = logging.getLogger(__name__)

class RecommendationEngine:
    """
    威科夫交易建议引擎 (P2 #2 - Enhanced)
    负责从检测结果中推导出交易计划和风险建议

    孟洪涛《新威科夫操盘法》核心原则：
    - 70% 等待：保持耐心，不强行交易
    - 20% 分析：深入研究市场结构
    - 10% 交易：只在高质量信号时行动
    """

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.thresholds = WyckoffThresholds()
        
        # 耐心状态追踪（实例级别，确保多标的并发沙箱隔离）
        self._patience_state = {
            'consecutive_weak_signals': 0,
            'last_signal_quality': None,
            'waiting_mode_active': False,
            'waiting_since': None,
        }
        self._patience_symbol: Optional[str] = None
        self._decision_audit = StrategyDecisionAuditLog()

    def begin_decision_audit(self, symbol: Optional[str] = None) -> None:
        """Reset audit log for a new analysis/decision run."""
        self._decision_audit.begin(symbol)

    def get_decision_audit(self) -> Dict[str, Any]:
        """Return structured audit log for backtest and manual review."""
        return self._decision_audit.to_dict()

    def _score_penalty(
        self,
        score: float,
        delta: float,
        rule_id: str,
        message: str,
        *,
        audit: bool = True,
        **context: Any,
    ) -> float:
        if audit:
            before = int(round(score))
            after = int(round(score + delta))
            self._decision_audit.record_score_penalty(
                rule_id, delta, before, after, message, stage='scoring', **context
            )
        return score + delta

    def _score_cap(
        self,
        score: int,
        cap: int,
        rule_id: str,
        message: str,
        *,
        audit: bool = True,
        **context: Any,
    ) -> int:
        if score <= cap:
            return score
        if audit:
            self._decision_audit.record_score_cap(
                rule_id, cap, score, cap, message, stage='scoring', **context
            )
        return cap

    @staticmethod
    def _effective_phase_str(pattern_results: Any) -> str:
        from .signal_extractor import SignalExtractor
        return SignalExtractor.get_effective_phase(
            pattern_results if isinstance(pattern_results, dict) else {}
        )

    @staticmethod
    def _event_detected_static(event_obj: Any) -> bool:
        return bool(RecommendationEngine._get_attr(event_obj, 'detected', False))

    @staticmethod
    def _dead_corner_actionable(dead_corner: Any, joc: Any) -> bool:
        """死角突破须 JOC 确认且未处于 joc_gate pending（与 PhaseCoordinator 同源）。"""
        if not RecommendationEngine._event_detected_static(dead_corner):
            return False
        if RecommendationEngine._get_attr(dead_corner, 'joc_gate') == 'pending':
            return False
        return RecommendationEngine._event_detected_static(joc)

    def _reset_patience_for_symbol(self, symbol: Optional[str]) -> None:
        if not symbol or symbol == self._patience_symbol:
            return
        self._patience_symbol = symbol
        self._patience_state = {
            'consecutive_weak_signals': 0,
            'last_signal_quality': None,
            'waiting_mode_active': False,
            'waiting_since': None,
        }

    def _calculate_patience_score(self, detected_keys: List[str], base_score: float, market_env: MarketEnvironment, audit_log: Optional[StrategyDecisionAuditLog] = None) -> tuple:
        """
        计算耐心评分（孟洪涛70%等待原则）

        Returns:
            (patience_penalty: float, patience_reasons: List[str], should_wait: bool)
        """
        patience_penalty = 0
        patience_reasons = []
        should_wait = False

        def _log_patience_penalty(rule_id: str, delta: float, before: int, after: int, message: str, **ctx: Any) -> None:
            if audit_log:
                audit_log.record_score_penalty(
                    rule_id, delta, before, after, message, stage='scoring', **ctx
                )

        # 1. 检查是否有主要高质量信号
        high_quality_signals = {'spring', 'joc', 'fti'}
        medium_quality_signals = {'sos', 'sow', 'lps', 'lpsy'}
        has_high_quality = bool(detected_keys & high_quality_signals)
        has_medium_quality = bool(detected_keys & medium_quality_signals)

        # 2. 检查信号数量是否过少
        if len(detected_keys) == 0:
            patience_penalty = 0
            patience_reasons.append("无检测信号，保持耐心等待")
        elif len(detected_keys) == 1 and not has_high_quality:
            patience_penalty = -15
            patience_reasons.append("单一信号且非高质量，建议等待更多确认")
            should_wait = True
            _log_patience_penalty(
                'patience.single_weak_signal',
                -15,
                int(base_score + patience_penalty + 15),
                int(base_score + patience_penalty),
                patience_reasons[-1],
                detected_keys=sorted(detected_keys),
            )
        elif len(detected_keys) <= 2 and not has_high_quality:
            patience_penalty = -8
            patience_reasons.append("信号数量不足且缺少核心信号，耐心等待")
            should_wait = True
            _log_patience_penalty(
                'patience.insufficient_signals',
                -8,
                int(base_score + patience_penalty + 8),
                int(base_score + patience_penalty),
                patience_reasons[-1],
                detected_keys=sorted(detected_keys),
            )

        # 3. 检查基础分数是否过低
        if base_score < 25:
            prev = patience_penalty
            patience_penalty -= 10
            patience_reasons.append(f"基础分数{base_score}较低，不符合孟洪涛10%交易原则")
            should_wait = True
            _log_patience_penalty(
                'patience.low_base_score',
                -10,
                int(base_score + prev),
                int(base_score + patience_penalty),
                patience_reasons[-1],
                base_score=int(base_score),
            )
        elif base_score < 40:
            prev = patience_penalty
            patience_penalty -= 5
            patience_reasons.append("信号质量中等，建议提高入场门槛")
            _log_patience_penalty(
                'patience.medium_base_score',
                -5,
                int(base_score + prev),
                int(base_score + patience_penalty),
                patience_reasons[-1],
                base_score=int(base_score),
            )

        # 4. 检查市场环境是否适合交易
        if market_env == MarketEnvironment.RANGE_BOUND:
            if not has_high_quality:
                prev = patience_penalty
                patience_penalty -= 5
                patience_reasons.append("震荡市场且无高质量信号，建议等待")
                should_wait = True
                _log_patience_penalty(
                    'patience.range_bound_no_hq_signal',
                    -5,
                    int(base_score + prev),
                    int(base_score + patience_penalty),
                    patience_reasons[-1],
                    market_env=str(market_env),
                )
        elif market_env == MarketEnvironment.UNKNOWN:
            prev = patience_penalty
            patience_penalty -= 8
            patience_reasons.append("多空信号混杂，建议等待市场明确方向")
            should_wait = True
            _log_patience_penalty(
                'patience.unknown_market_env',
                -8,
                int(base_score + prev),
                int(base_score + patience_penalty),
                patience_reasons[-1],
                market_env=str(market_env),
            )

        # 5. 检查是否处于等待期（连续弱信号）
        if base_score < 50:
            self._patience_state['consecutive_weak_signals'] += 1
            if self._patience_state['consecutive_weak_signals'] >= 3:
                prev = patience_penalty
                patience_penalty -= 10
                patience_reasons.append(f"连续{self._patience_state['consecutive_weak_signals']}次低质量分析，进入耐心等待模式")
                self._patience_state['waiting_mode_active'] = True
                if self._patience_state['waiting_since'] is None:
                    from datetime import datetime
                    self._patience_state['waiting_since'] = datetime.now()
                should_wait = True
                _log_patience_penalty(
                    'patience.consecutive_weak_signals',
                    -10,
                    int(base_score + prev),
                    int(base_score + patience_penalty),
                    patience_reasons[-1],
                    consecutive_weak=self._patience_state['consecutive_weak_signals'],
                )
        else:
            # 高质量信号重置计数器
            self._patience_state['consecutive_weak_signals'] = 0
            if has_high_quality:
                self._patience_state['waiting_mode_active'] = False

        # 6. 检查是否处于等待激活期
        if self._patience_state['waiting_mode_active']:
            prev = patience_penalty
            patience_penalty -= 15
            patience_reasons.append("系统处于耐心等待模式，只接受Spring/JOC级别的超高质量信号")
            should_wait = True
            _log_patience_penalty(
                'patience.waiting_mode_active',
                -15,
                int(base_score + prev),
                int(base_score + patience_penalty),
                patience_reasons[-1],
            )

        return patience_penalty, patience_reasons, should_wait

    @staticmethod
    def _get_attr(obj: Any, key: str, default=None):
        """
        安全获取属性，支持字典和Pydantic模型

        Args:
            obj: 对象（字典或Pydantic模型）
            key: 属性名
            default: 默认值

        Returns:
            属性值或默认值
        """
        if obj is None:
            return default
        # 如果是Pydantic模型，使用getattr
        if hasattr(obj, 'model_dump'):
            return getattr(obj, key, default)
        # 如果是字典，使用get方法
        if isinstance(obj, dict):
            return obj.get(key, default)
        # 其他情况，使用getattr
        return getattr(obj, key, default)

    @staticmethod
    def _get_latest_detail(event_obj: Any):
        """获取事件的最新子信号，兼容 latest/latest_spring/latest_upthrust/signals。"""
        for key in ('latest', 'latest_spring', 'latest_upthrust'):
            latest = RecommendationEngine._get_attr(event_obj, key, None)
            if latest:
                return latest
        signals = RecommendationEngine._get_attr(event_obj, 'signals', []) or []
        return signals[-1] if signals else None

    @staticmethod
    def _get_signal_attr(event_obj: Any, key: str, default=None):
        """优先读事件顶层，缺失时读取 latest/signals[-1]。"""
        value = RecommendationEngine._get_attr(event_obj, key, None)
        if value is not None:
            return value
        latest = RecommendationEngine._get_latest_detail(event_obj)
        return RecommendationEngine._get_attr(latest, key, default) if latest else default

    @staticmethod
    def _get_numeric(value: Any, default: float = 0.0) -> float:
        if isinstance(value, dict):
            value = value.get('value', default)
        elif hasattr(value, 'value'):
            value = getattr(value, 'value')
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_bearish_signal_absorbed(signal_type: str, signal_info: Any, data: Any) -> bool:
        """
        检查看空信号是否已被价格吸收（失效）

        威科夫理论：如果价格突破看空信号的价格位一定幅度（如15%），
        且保持在该水平上方，则说明该看空信号已被需求吸收，不再有效。

        Args:
            signal_type: 信号类型 ('sow', 'lpsy', 'upthrust')
            signal_info: 信号信息
            data: 价格数据

        Returns:
            True表示信号已被吸收，不应计入冲突评分
        """
        try:
            # 获取信号价格
            signal_price = RecommendationEngine._get_numeric(
                RecommendationEngine._get_signal_attr(signal_info, 'price', 0)
            )
            if signal_price <= 0:
                return False

            # 获取当前价格
            if not hasattr(data, 'Close'):
                return False
            current_price = data['Close'].iloc[-1]

            # 计算价格上涨幅度
            price_gain_pct = (current_price / signal_price) - 1

            #  修复：降低阈值，15%上涨即认为信号已被吸收
            if price_gain_pct > 0.15:  # 上涨超过15%
                # 进一步检查：是否真正突破（不仅仅是短暂上冲）
                # 检查最近N天的收盘价，大部分维持在信号价格上方即可
                lookback = min(20, len(data))
                recent_closes = data['Close'].iloc[-lookback:]

                #  修复：改为80%的天数在信号价格上方即可（更宽松）
                days_above = (recent_closes > signal_price * 1.02).sum()  # 102%信号价格以上
                pct_above = days_above / len(recent_closes)

                if pct_above >= 0.80:  # 80%的天数在上方
                    logger.info(
                        f"Bearish signal {signal_type} at {signal_price:.2f} ABSORBED: "
                        f"current {current_price:.2f} (+{price_gain_pct*100:.1f}%), "
                        f"{days_above}/{lookback} days above, {pct_above*100:.0f}%"
                    )
                    return True

            return False
        except Exception as e:
            logger.debug(f"Error checking if signal absorbed: {e}")
            return False

    def calculate_weighted_score(self, data: Any, pattern_results: Dict[str, Any], market_env: MarketEnvironment, *, audit: bool = True) -> SignalQualityModel:
        """
        计算高级加权评分 (v2.1校准：修正Phase E冲突惩罚，提升基础分)
        """
        if isinstance(pattern_results, dict):
            self._reset_patience_for_symbol(pattern_results.get('symbol'))
            events = pattern_results.get('events_detected') or pattern_results
            seq_val = pattern_results.get('sequence_validation')
            boring = pattern_results.get('boring_zone')
        else:
            events = pattern_results
            seq_val = getattr(pattern_results, 'sequence_validation', None)
            boring = getattr(pattern_results, 'boring_zone', None)

        if not boring and events:
            boring = RecommendationEngine._get_attr(events, 'boring_zone')

        if not events:
            return SignalQualityModel(score=0, max_score=100, confidence="低", reasons=["未检测到有效信号"])
            
        base_score = 0.0
        reasons = []
        weights = self.thresholds.QUALITY_WEIGHTS
        
        important_signals = [
            ('joc', 40),
            ('spring', 35),
            ('sos', 25),
            ('lps', 15),
            ('upthrust', 35),
            ('sow', 25),
            ('lpsy', 15),
            ('fti', 40),
            ('secondary_test', 20),
            ('automatic_reaction', 15),
            ('utad', 35)
        ]

        bullish_count = 0
        bearish_count = 0
        has_major_signal = False  # 是否至少有1个主要交易信号
        detected_keys = []

        for key, max_weight in important_signals:
            info = RecommendationEngine._get_attr(events, key, None)

            if not info or not self._get_attr(info, 'detected'):
                continue

            # Phase 26：仅正式 LPS/LPSY 计入评分
            if key == 'lps' and not SignalExtractor.is_formal_lps(info):
                continue
            if key == 'lpsy' and not SignalExtractor.is_formal_lpsy(info):
                continue

            # Phase 24：LPS/LPSY 须在 JOC/FTI 确认后才计入评分（威科夫第五步）
            if key == 'lps' and not self._event_detected_static(
                RecommendationEngine._get_attr(events, 'joc')
            ):
                continue
            if key == 'lpsy' and not self._event_detected_static(
                RecommendationEngine._get_attr(events, 'fti')
            ):
                continue

            detected_keys.append(key)
            if key in ('spring', 'sos', 'sow', 'joc', 'fti', 'upthrust', 'utad'):
                has_major_signal = True

            if key in ['sow', 'lpsy', 'upthrust', 'utad']:
                if self._is_bearish_signal_absorbed(key, info, data):
                    reasons.append(f"过时信号{key.upper()}已失效不计入冲突")
                    continue

            if key in ['joc', 'spring', 'sos', 'lps', 'automatic_reaction']:
                bullish_count += 1
            elif key in ['fti', 'upthrust', 'sow', 'lpsy', 'secondary_test', 'utad']:
                phase_str = self._effective_phase_str(pattern_results)
                if PhaseAdapter.is_distribution(phase_str):
                    bearish_count += 1
                elif PhaseAdapter.is_accumulation(phase_str):
                    bullish_count += 1

            quality_factor = 1.0

            if key == 'secondary_test':
                st_vol_ratio = self._get_attr(info, 'st_vol_ratio', None)
                supply_exhausted = self._get_attr(info, 'supply_exhausted', False)
                if supply_exhausted:
                    quality_factor += 0.3
                    reasons.append(f"ST确认需求耗尽（量为高潮量的{st_vol_ratio:.0%}）")
                elif st_vol_ratio and st_vol_ratio < 0.6:
                    quality_factor += 0.1
                    reasons.append(f"ST接近确认（量为高潮量的{st_vol_ratio:.0%}）")
            elif key == 'automatic_reaction':
                rebound_pct = self._get_attr(info, 'rebound_pct', None)
                decline_pct = self._get_attr(info, 'decline_pct', None)
                if rebound_pct and rebound_pct > 0.03:
                    quality_factor += 0.15
                    reasons.append(f"AR自然反弹强劲（{rebound_pct*100:.1f}%）")
                elif decline_pct and decline_pct < -0.03:
                    quality_factor += 0.15
                    reasons.append(f"AR自然回落充分（{decline_pct*100:.1f}%）")
            else:
                vol_ratio = self._get_signal_attr(info, 'volume_ratio', 1.0)
                if vol_ratio > 1.5:
                    quality_factor += weights['volume_ratio']
                    reasons.append(f"{key.upper()} 成交量强力确认")

            from .signal_extractor import SignalExtractor
            # P0 修复：confidence 可能是 0–100 分，需归一化后再参与 quality_factor
            raw_conf = self._get_signal_attr(info, 'confidence', None)
            if raw_conf is None:
                raw_conf = self._get_signal_attr(info, 'total_score', 0.5)
            conf = SignalExtractor.normalize_confidence(raw_conf, 0.5)
            quality_factor += (conf - 0.5) * weights['confidence']

            sig_date = self._get_signal_attr(info, 'date')
            if sig_date:
                if isinstance(sig_date, str):
                    try:
                        sig_date = datetime.strptime(sig_date, '%Y-%m-%d')
                    except Exception:
                        pass

                if isinstance(sig_date, datetime):
                    from datetime import timezone
                    now = datetime.now(timezone.utc) if sig_date.tzinfo else datetime.now()
                    try:
                        days_ago = (now - sig_date).days
                    except Exception:
                        if sig_date.tzinfo:
                            sig_date = sig_date.replace(tzinfo=None)
                        now = datetime.now()
                        days_ago = (now - sig_date).days

                    decay = np.exp(-0.693 * max(0, days_ago) / self.thresholds.TIME_DECAY_HALF_LIFE)
                    quality_factor *= decay
                    if decay < 0.7:
                        reasons.append(f"{key.upper()} 信号已过最佳期 (衰减)")

            base_score += max_weight * min(quality_factor, 1.5)

        # --- 事件序列验证加成 ---
        seq_score = RecommendationEngine._get_attr(seq_val, 'sequence_score', {}) or {}
        seq_rating = seq_score.get('rating', '') if isinstance(seq_score, dict) else getattr(seq_score, 'rating', '')
        if seq_rating == 'A':
            base_score += 15
            reasons.append("事件序列完整(评级A)：SC→AR→ST→Spring→SOS→LPS→JOC 链条完整 (+15分)")
        elif seq_rating == 'B':
            base_score += 10
            reasons.append("事件序列较完整(评级B)：大部分关键事件已检测到 (+10分)")
        elif seq_rating == 'C':
            base_score += 5
            reasons.append("事件序列部分检测(评级C)：存在部分事件但链条不完整 (+5分)")

        # Spring 前置结构质量加分
        spring_val = RecommendationEngine._get_attr(seq_val, 'spring', {}) or {}
        if (spring_val.get('quality') if isinstance(spring_val, dict) else getattr(spring_val, 'quality', None)) == 'high':
            base_score += 10
            reasons.append("Spring有完整SC→AR→ST前置结构，信号质量高 (+10分)")
        elif (spring_val.get('quality') if isinstance(spring_val, dict) else getattr(spring_val, 'quality', None)) == 'medium':
            base_score += 5
            reasons.append("Spring有部分前置结构，质量中等 (+5分)")

        # 多次ST递减量缩加分 (Phase B积累确认)
        st_res = RecommendationEngine._get_attr(events, 'secondary_test')
        if st_res and self._get_attr(st_res, 'detected'):
            test_count = self._get_attr(st_res, 'test_count', 1)
            st_trend = self._get_attr(st_res, 'st_sequence_trend', 'stable')
            if test_count >= 3 and st_trend == 'declining':
                base_score += 10
                reasons.append(f"多次ST({test_count}次)量递减：供应被持续吸收 (+10分)")
            elif test_count >= 2:
                base_score += 3
                reasons.append(f"多次ST({test_count}次)确认区间 (+3分)")

        # PS→SC序列确认加分 (Phase A完整结构)
        ps_res = RecommendationEngine._get_attr(events, 'preliminary_support')
        if ps_res and self._get_attr(ps_res, 'detected'):
            sc_after = self._get_attr(ps_res, 'sc_confirmed_after', False)
            if sc_after:
                base_score += 8
                reasons.append("PS→SC链条确认：初次支撑后有效恐慌抛售，Phase A结构完整 (+8分)")

        # 序列矛盾扣分
        seq_conflicts = (RecommendationEngine._get_attr(seq_val, 'conflicts', []) or []) if seq_val else []
        for conflict in seq_conflicts:
            base_score = self._score_penalty(
                base_score,
                -10,
                'scoring.sequence_conflict',
                f"序列矛盾: {conflict} (-10分)",
                conflict=conflict,
                audit=audit,
            )
            reasons.append(f"序列矛盾: {conflict} (-10分)")

        # --- 孟洪涛进阶信号：枯燥区与死角突破 ---
        boring_score = self._get_attr(boring, 'score', 0)
        if self._get_attr(boring, 'detected'):
            base_score += 10
            reasons.append(f"检测到「枯燥区」(得分:{boring_score})，主力可能正在吸筹")

            # Boring Zone 联动加权 (P2 #3.1)
            if boring_score > 85:
                for key in ['spring', 'joc']:
                    info = RecommendationEngine._get_attr(events, key, None)
                    if info and self._get_attr(info, 'detected'):
                        base_score += 15 # 高质量枯燥区后的突破极具爆发力
                        reasons.append(f"🔥 高价值突破：{key.upper()} 紧随高质量枯燥区出现，爆发潜力极大")

            if self._get_attr(boring, 'high_alert'):
                reasons.append("🔥 高能预警：系统已进入「死角突破」严密监控模式")

        dead_corner = RecommendationEngine._get_attr(events, 'dead_corner_breakout') or {}
        if not self._get_attr(dead_corner, 'detected'):
            dead_corner = RecommendationEngine._get_attr(events, 'dead_corner') or dead_corner
        joc_for_gate = RecommendationEngine._get_attr(events, 'joc') or {}
        skip_conflict_penalty = False
        if self._dead_corner_actionable(dead_corner, joc_for_gate):
            base_score += 25
            skip_conflict_penalty = True
            reasons.append("🎯 发现“死角突破”信号！JOC 已确认，从枯燥区放量跃起 (+25分)")
        elif self._get_attr(dead_corner, 'detected'):
            reasons.append("死角突破待 JOC 小溪确认，暂不加分（孟氏 checklist）")

        # SOS/Upthrust 交叉验证（模糊区间）
        has_sos = 'sos' in detected_keys
        has_upthrust = 'upthrust' in detected_keys
        if has_sos and has_upthrust and not skip_conflict_penalty:
            is_uncertain = market_env in (MarketEnvironment.RANGE_BOUND, MarketEnvironment.UNKNOWN)
            if is_uncertain:
                base_score = self._score_penalty(
                    base_score,
                    -15,
                    'scoring.sos_upthrust_conflict_uncertain',
                    "模糊区间内SOS与Upthrust同时出现，信号冲突 (-15分)",
                    market_env=str(market_env),
                    audit=audit,
                )
                reasons.append("模糊区间内SOS与Upthrust同时出现，信号冲突 (-15分)")
            else:
                base_score = self._score_penalty(
                    base_score,
                    -8,
                    'scoring.sos_upthrust_conflict',
                    "SOS与Upthrust信号冲突 (-8分)",
                    audit=audit,
                )
                reasons.append("SOS与Upthrust信号冲突 (-8分)")

        structure_score = int(max(0, min(base_score, 100)))

        # --- 孟洪涛耐心评分（70%等待原则） ---
        patience_penalty, patience_reasons, should_wait = self._calculate_patience_score(
            set(detected_keys), base_score, market_env,
            self._decision_audit if audit else None,
        )
        base_score += patience_penalty
        reasons.extend(patience_reasons)
        if should_wait and base_score < 50:
            reasons.append("🕰️ 孟洪涛原则：当前处于70%等待期，建议耐心等待高质量信号")
            if audit:
                self._decision_audit.record_watch(
                    'scoring.patience_should_wait',
                    reasons[-1],
                    direction_before=None,
                    stage='scoring',
                    score=int(base_score),
                )

        # --- 冲突惩罚 (v2.1校准) ---
        if bullish_count > 0 and bearish_count > 0 and not skip_conflict_penalty:
            phase_str = self._effective_phase_str(pattern_results)

            # Phase E/Markup中SOW是正常回调，不应惩罚
            is_phase_e = ('Phase E' in phase_str or 'Markup' in phase_str or 'Markdown' in phase_str)
            dominant_ratio = max(bullish_count, bearish_count) / max(1, min(bullish_count, bearish_count))

            if is_phase_e:
                reasons.append(f"Phase E/M趋势推进中，混合信号属于正常回调 (+0分)")
            elif dominant_ratio >= 2:
                base_score = self._score_penalty(
                    base_score,
                    -5,
                    'scoring.mixed_signals_dominant',
                    f"主力方向明确(比例{dominant_ratio:.0f}:1)，混合信号轻微扣分 (-5分)",
                    dominant_ratio=dominant_ratio,
                    bullish_count=bullish_count,
                    bearish_count=bearish_count,
                    audit=audit,
                )
                reasons.append(f"主力方向明确(比例{dominant_ratio:.0f}:1)，混合信号轻微扣分 (-5分)")
            elif ('Phase A' in phase_str or 'Phase B' in phase_str or
                  ('Accumulation' in phase_str and bullish_count > bearish_count) or
                  ('Distribution' in phase_str and bearish_count > bullish_count)):
                base_score = self._score_penalty(
                    base_score,
                    -10,
                    'scoring.phase_transition_mixed',
                    "阶段过渡期信号混合 (轻微扣分 -10分，符合威科夫理论)",
                    phase=phase_str,
                    audit=audit,
                )
                reasons.append(f"阶段过渡期信号混合 (轻微扣分 -10分，符合威科夫理论)")
            else:
                base_score = self._score_penalty(
                    base_score,
                    -self.thresholds.CONFLICT_PENALTY,
                    'scoring.bull_bear_conflict',
                    f"检测到多空信号冲突 (惩罚 -{self.thresholds.CONFLICT_PENALTY}分)",
                    bullish_count=bullish_count,
                    bearish_count=bearish_count,
                    audit=audit,
                )
                reasons.append(f"检测到多空信号冲突 (惩罚 -{self.thresholds.CONFLICT_PENALTY}分)")

        # --- 市场环境加成 (v2.1校准：仅极端不匹配扣分) ---
        phase_str = self._effective_phase_str(pattern_results)
        current_side = PhaseAdapter.get_market_side(phase_str)
        is_market_strong_bullish = market_env == MarketEnvironment.STRONG_BULL
        is_market_strong_bearish = market_env == MarketEnvironment.STRONG_BEAR
        is_market_bullish = market_env in [MarketEnvironment.STRONG_BULL, MarketEnvironment.BULL]
        is_market_bearish = market_env in [MarketEnvironment.STRONG_BEAR, MarketEnvironment.BEAR]

        # 多头方向
        if is_market_strong_bullish and current_side == MarketSide.BULLISH:
            base_score += 15
            reasons.append("顺应大盘强势多头环境 (+15分)")
        elif is_market_bullish and current_side == MarketSide.BULLISH:
            base_score += 8
            reasons.append("顺应大盘多头环境 (+8分)")
        elif is_market_strong_bearish and current_side == MarketSide.BULLISH:
            base_score = self._score_penalty(
                base_score,
                -10,
                'scoring.market_bearish_vs_bullish_setup',
                "大盘强势空头环境不利于做多 (-10分)",
                market_env=str(market_env),
                audit=audit,
            )
            reasons.append("大盘强势空头环境不利于做多 (-10分)")

        # 空头方向
        if is_market_strong_bearish and current_side == MarketSide.BEARISH:
            base_score += 15
            reasons.append("顺应大盘强势空头环境 (+15分)")
        elif is_market_bearish and current_side == MarketSide.BEARISH:
            base_score += 8
            reasons.append("顺应大盘空头环境 (+8分)")
        elif is_market_strong_bullish and current_side == MarketSide.BEARISH:
            base_score = self._score_penalty(
                base_score,
                -10,
                'scoring.market_bullish_vs_bearish_setup',
                "大盘强势多头环境不利于做空 (-10分)",
                market_env=str(market_env),
                audit=audit,
            )
            reasons.append("大盘强势多头环境不利于做空 (-10分)")

        # Phase 28：周线 EVR + 日线 Spring/Upthrust 共振加分
        if isinstance(pattern_results, dict):
            evr = pattern_results.get('mtf_evr_resonance') or {}
            if isinstance(evr, dict) and evr.get('boost'):
                base_score += 15
                note = evr.get('note') or '周线 EVR 跨周期共振'
                reasons.append(f"周线 EVR + 日线事件共现 (+15分): {note}")

        # --- v2.1校准：保底分 ---
        final_score = int(max(0, min(base_score, 100)))

        # 保底：至少有一个主要信号(Spring/SOS/SOW/JOC/FTI/Upthrust) + 有AR+ST结构 = 不低于15分
        if final_score < 15 and has_major_signal and len(detected_keys) >= 3:
            final_score = 15
            reasons.append("检测到主要Wyckoff信号及完整前置结构 (校准保底 15分)")

        # 保底：有Spring/JOC/SOS且有完整序列 → 不低于25
        has_primary_entry = any(k in detected_keys for k in ['spring', 'joc', 'sos', 'sow', 'fti', 'upthrust'])
        if final_score < 25 and has_primary_entry and seq_rating in ['A', 'B']:
            final_score = 25
            reasons.append("主要入场信号+完整序列结构 (校准保底 25分)")

        if final_score < 10 and seq_rating in ['A', 'B'] and not has_primary_entry:
            missing_signals = []
            phase_str = self._effective_phase_str(pattern_results)

            if 'Accumulation' in phase_str or '吸筹' in phase_str:
                if not self._get_attr(RecommendationEngine._get_attr(events, 'spring'), 'detected'):
                    missing_signals.append('Spring震仓')
                if not self._get_attr(RecommendationEngine._get_attr(events, 'sos'), 'detected'):
                    missing_signals.append('SOS强势信号')
            elif 'Distribution' in phase_str or '派发' in phase_str:
                if not self._get_attr(RecommendationEngine._get_attr(events, 'sow'), 'detected'):
                    missing_signals.append('SOW弱势信号')
                if not self._get_attr(RecommendationEngine._get_attr(events, 'lpsy'), 'detected'):
                    missing_signals.append('LPSY最后支撑')

            if missing_signals:
                reasons.append(f"虽有完整{seq_rating}级序列结构，但缺少核心交易信号：{', '.join(missing_signals)}。当前处于{phase_str}，信号尚未成熟，建议等待关键确认出现。")

        if self._get_attr(boring, 'score', 0) >= 85 and final_score < 85:
            phase_str_floor = self._effective_phase_str(pattern_results)
            fti_for_gate = RecommendationEngine._get_attr(events, 'fti') or {}
            if PhaseAdapter.is_distribution(phase_str_floor):
                if self._event_detected_static(fti_for_gate):
                    final_score = 85
                    reasons.append("派发侧枯燥区 + FTI 确认，综合评分托底至 85")
                else:
                    reasons.append("枯燥区高能预警但缺 FTI 冰层确认，评分不上调（派发对称门控）")
            elif PhaseAdapter.is_accumulation(phase_str_floor) or PhaseAdapter.is_markup(phase_str_floor):
                if (
                    self._event_detected_static(joc_for_gate)
                    or self._dead_corner_actionable(dead_corner, joc_for_gate)
                ):
                    final_score = 85
                    reasons.append("吸筹侧枯燥区高能预警 + JOC 确认，综合评分托底至 85")
                else:
                    reasons.append("枯燥区高能预警但缺 JOC 小溪确认，评分不上调")
            else:
                final_score = 85
                reasons.append("触发高能预警阈值，综合评分上调至 85 (死角突破临界)")

        if self._dead_corner_actionable(dead_corner, joc_for_gate) and final_score < 85:
            final_score = 85
            reasons.append("🎯 死角突破 + JOC 确认，综合评分托底至 85")

        # Phase 24：相对强度 / 跨周期冲突评分上限（威科夫第二、三步）
        if isinstance(pattern_results, dict):
            rs = pattern_results.get('relative_strength') or {}
            rs_trend = rs.get('rs_trend') if isinstance(rs, dict) else None
            phase_str_rs = self._effective_phase_str(pattern_results)
            if PhaseAdapter.is_accumulation(phase_str_rs) and rs_trend == 'falling':
                capped = self._score_cap(
                    final_score,
                    55,
                    'scoring.cap.rs_falling_in_accumulation',
                    "吸筹阶段但相对强度走弱，评分上限 55",
                    rs_trend=rs_trend,
                    phase=phase_str_rs,
                    audit=audit,
                )
                if capped != final_score:
                    reasons.append("吸筹阶段但相对强度走弱，评分上限 55")
                final_score = capped
            elif PhaseAdapter.is_distribution(phase_str_rs) and rs_trend == 'rising':
                capped = self._score_cap(
                    final_score,
                    55,
                    'scoring.cap.rs_rising_in_distribution',
                    "派发阶段但相对强度走强，做空评分上限 55",
                    rs_trend=rs_trend,
                    phase=phase_str_rs,
                    audit=audit,
                )
                if capped != final_score:
                    reasons.append("派发阶段但相对强度走强，做空评分上限 55")
                final_score = capped
            if pattern_results.get('mtf_has_conflict'):
                capped = self._score_cap(
                    final_score,
                    50,
                    'scoring.cap.mtf_conflict',
                    "跨周期冲突，评分上限 50",
                    conflict_details=pattern_results.get('mtf_conflict_details'),
                    audit=audit,
                )
                if capped != final_score:
                    reasons.append("跨周期冲突，评分上限 50")
                final_score = capped

            searchlight = pattern_results.get('searchlight_arbitration') or {}
            if isinstance(searchlight, dict) and searchlight.get('available'):
                bias = searchlight.get('bias')
                entropy_degraded = bool(searchlight.get('entropy_degraded'))
                if searchlight.get('has_contradiction'):
                    if bias == 'bearish_microstructure':
                        capped = self._score_cap(
                            final_score,
                            45,
                            'scoring.cap.searchlight_bearish_vs_accumulation',
                            "Searchlight/WIE3 显示弱势微观结构与吸筹做多结论冲突，评分上限 45",
                            bias=bias,
                            audit=audit,
                        )
                        if capped != final_score:
                            reasons.append("Searchlight/WIE3 显示弱势微观结构与吸筹做多结论冲突，评分上限 45")
                        final_score = capped
                    elif bias == 'bullish_microstructure':
                        capped = self._score_cap(
                            final_score,
                            55,
                            'scoring.cap.searchlight_bullish_vs_distribution',
                            "Searchlight/WIE3 显示吸收或需求主导，与派发做空结论冲突，评分上限 55",
                            bias=bias,
                            audit=audit,
                        )
                        if capped != final_score:
                            reasons.append("Searchlight/WIE3 显示吸收或需求主导，与派发做空结论冲突，评分上限 55")
                        final_score = capped
                    else:
                        capped = self._score_cap(
                            final_score,
                            50,
                            'scoring.cap.searchlight_contradiction',
                            "Searchlight/WIE3 与阶段结论冲突，评分上限 50",
                            bias=bias,
                            audit=audit,
                        )
                        if capped != final_score:
                            reasons.append("Searchlight/WIE3 与阶段结论冲突，评分上限 50")
                        final_score = capped

                    if entropy_degraded:
                        capped = self._score_cap(
                            final_score,
                            40,
                            'scoring.cap.searchlight_entropy_degraded',
                            "WIE3 高熵降级且存在阶段冲突，评分上限 40",
                            audit=audit,
                        )
                        if capped != final_score:
                            reasons.append("WIE3 高熵降级且存在阶段冲突，评分上限 40")
                        final_score = capped
                elif entropy_degraded:
                    capped = self._score_cap(
                        final_score,
                        65,
                        'scoring.cap.wie3_entropy_degraded',
                        "WIE3 高熵降级，微观结构置信度不足，评分上限 65",
                        audit=audit,
                    )
                    if capped != final_score:
                        reasons.append("WIE3 高熵降级，微观结构置信度不足，评分上限 65")
                    final_score = capped

        background_adjustment = final_score - structure_score
        primary_reason = None
        searchlight = (
            pattern_results.get('searchlight_arbitration') or {}
            if isinstance(pattern_results, dict) else {}
        )
        if isinstance(searchlight, dict) and searchlight.get('has_contradiction'):
            primary_reason = searchlight.get('resolution_hint')
        elif isinstance(searchlight, dict) and searchlight.get('entropy_degraded'):
            primary_reason = searchlight.get('resolution_hint')
        elif reasons:
            cap_reasons = [r for r in reasons if '上限' in r or '不上调' in r or '冲突' in r]
            primary_reason = cap_reasons[-1] if cap_reasons else reasons[0]

        return SignalQualityModel(
            score=final_score,
            max_score=100,
            confidence="极高" if final_score >= 80 else "高" if final_score >= 55 else "中" if final_score >= 25 else "低",
            reasons=reasons,
            structure_score=structure_score,
            background_adjustment=background_adjustment,
            primary_reason=primary_reason,
        )

    def calculate_signal_quality(self, data: Any, pattern_results: Dict[str, Any], market_env: MarketEnvironment, *, audit: bool = True) -> SignalQualityModel:
        """兼容旧接口，内部调用加权评分"""
        return self.calculate_weighted_score(data, pattern_results, market_env, audit=audit)

    @staticmethod
    def calculate_signal_strength(pattern_results: Dict[str, Any]) -> int:
        """计算基础信号强度 (简单计数，仅为兼容性保留)"""
        events = RecommendationEngine._get_attr(pattern_results, 'events_detected', None) or pattern_results
        joc = RecommendationEngine._get_attr(events, 'joc', None)
        fti = RecommendationEngine._get_attr(events, 'fti', None)
        count = 0
        for key in ['joc', 'spring', 'sos', 'lps', 'upthrust', 'sow', 'lpsy', 'fti']:
            event = RecommendationEngine._get_attr(events, key, None)
            if not event or not RecommendationEngine._get_attr(event, 'detected'):
                continue
            if key == 'lps':
                if not RecommendationEngine._event_detected_static(joc):
                    continue
                if not SignalExtractor.is_formal_lps(event):
                    continue
            if key == 'lpsy':
                if not RecommendationEngine._event_detected_static(fti):
                    continue
                if not SignalExtractor.is_formal_lpsy(event):
                    continue
            count += 1
        return count

    def generate_trading_plan(self, data: Any, pattern_results: Dict[str, Any], targets: Dict[str, Any]) -> TradingPlanModel:
        """
        生成具体交易计划 (威科夫结构导向止损 + Phase风险导向仓位)

        止损原则 (Wyckoff 操盘法):
          - 做多保守止损 = Spring低点下方, 激进止损 = 最近摆动低点下方
          - 做空保守止损 = Upthrust高点上方, 激进止损 = 最近摆动高点上方

        仓位原则 (Wyckoff 操盘法):
          - Phase A-B: 25-35% 常规仓位 (早期高风险)
          - Phase D:   75-100% 常规仓位 (最优入场区)
          - Phase E:   50-75% 常规仓位 (趋势已确立但部分走完)
          - Re-accumulation/Re-distribution: 50-75% (较短区间的较小因果)
        """
        # 兼容性处理：如果 pattern_results 是字典，且包含 'events_detected'，则从中提取核心事件
        if isinstance(pattern_results, dict):
            events = pattern_results.get('events_detected') or pattern_results
        else:
            events = pattern_results

        current_price = data['Close'].iloc[-1]
        joc = RecommendationEngine._get_attr(events, 'joc') or {}
        spring = RecommendationEngine._get_attr(events, 'spring') or {}
        upthrust = RecommendationEngine._get_attr(events, 'upthrust') or {}
        utad = RecommendationEngine._get_attr(events, 'utad') or {}
        fti = RecommendationEngine._get_attr(events, 'fti') or {}
        sow = RecommendationEngine._get_attr(events, 'sow') or {}
        sos = RecommendationEngine._get_attr(events, 'sos') or {}
        lps = RecommendationEngine._get_attr(events, 'lps') or {}
        lpsy = RecommendationEngine._get_attr(events, 'lpsy') or {}
        tr = RecommendationEngine._get_attr(events, 'trading_range') or {}

        # 提前提取 ATR 供所有分支使用
        atr_val = float(data['ATR'].iloc[-1]) if 'ATR' in data.columns else current_price * 0.03

        def _get_swing_low(window: int = 20) -> float:
            return float(data['Low'].tail(window).min())

        def _get_swing_high(window: int = 20) -> float:
            return float(data['High'].tail(window).max())

        def _get_spring_low(sp_obj) -> float:
            if not sp_obj: return 0.0
            latest = RecommendationEngine._get_attr(sp_obj, 'latest_spring', None)
            if not latest:
                signals = RecommendationEngine._get_attr(sp_obj, 'signals', []) or []
                latest = signals[-1] if signals else None
            if not latest: return 0.0
            return _as_float(
                RecommendationEngine._get_attr(latest, 'breakdown_price', None) or
                RecommendationEngine._get_attr(latest, 'price', 0)
            )

        def _get_upthrust_high(ut_obj) -> float:
            if not ut_obj: return 0.0
            latest = RecommendationEngine._get_attr(ut_obj, 'latest_upthrust', None)
            if not latest:
                signals = RecommendationEngine._get_attr(ut_obj, 'upthrusts', []) or []
                latest = signals[-1] if signals else None
            if not latest: return 0.0
            return _as_float(
                RecommendationEngine._get_attr(latest, 'breakout_price', None) or
                RecommendationEngine._get_attr(latest, 'price', 0)
            )

        direction = "观望"
        zone = "等待形态确认"
        stop = StopLossModel(conservative=0.0, aggressive=0.0)
        phase_str = self._effective_phase_str(pattern_results)

        def _audit_watch(rule_id: str, message: str, prev_direction: Optional[str] = None, **context: Any) -> None:
            self._decision_audit.record_watch(
                rule_id,
                message,
                direction_before=prev_direction if prev_direction is not None else direction,
                stage='trading_plan',
                **context,
            )

        def _get_lps_low(window: int = 15) -> float:
            return float(data['Low'].tail(window).min())
            
        def _get_lpsy_high(window: int = 15) -> float:
            return float(data['High'].tail(window).max())

        def _event_get(event_obj, key: str, default=None):
            return RecommendationEngine._get_attr(event_obj, key, default)

        def _event_detected(event_obj) -> bool:
            return bool(_event_get(event_obj, 'detected', False))

        def _event_latest(event_obj):
            latest = _event_get(event_obj, 'latest')
            if latest:
                return latest
            latest = _event_get(event_obj, 'latest_spring')
            if latest:
                return latest
            latest = _event_get(event_obj, 'latest_upthrust')
            if latest:
                return latest
            signals = _event_get(event_obj, 'signals', []) or []
            return signals[-1] if signals else None

        def _as_float(value, default: float = 0.0) -> float:
            if isinstance(value, dict) and 'value' in value:
                value = value.get('value')
            elif hasattr(value, 'value'):
                value = getattr(value, 'value')
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def _event_price(event_obj, default: float) -> float:
            price = _event_get(event_obj, 'price', None)
            if price is None:
                latest = _event_latest(event_obj)
                price = _event_get(latest, 'price', default) if latest else default
            return _as_float(price, default)

        def _event_level(event_obj, key: str, default: float) -> float:
            return _as_float(_event_get(event_obj, key, default), default)

        def _get_latest_spring_detail(sp_obj):
            if not sp_obj:
                return None
            latest = RecommendationEngine._get_attr(sp_obj, 'latest_spring')
            if not latest:
                signals = RecommendationEngine._get_attr(sp_obj, 'signals', [])
                latest = signals[-1] if signals else None
            if not latest:
                if RecommendationEngine._get_attr(sp_obj, 'spring_type'):
                    return sp_obj
                return None
            return latest

        # ── 方向判断 (结构导向刚性止损) ──
        if _event_detected(joc):
            creek = _event_level(joc, 'creek_level', current_price)
            lps_low = _get_lps_low(15)
            cons_stop = min(lps_low, creek * 0.99)
            if SignalExtractor.is_formal_lps(lps):
                direction = "做多"
                lps_price = _event_price(lps, current_price)
                zone = f"{lps_price:.2f} 附近 (JOC+LPS 威科夫标准入场)"
                lps_detail = _event_latest(lps)
                if lps_detail:
                    lps_support = _as_float(
                        _event_get(lps_detail, 'support_level') or
                        _event_get(lps_detail, 'price'),
                        lps_price,
                    )
                    if lps_support > 0:
                        cons_stop = min(cons_stop, lps_support * 0.99)
                stop = StopLossModel(
                    conservative=round(cons_stop, 2),
                    aggressive=round(creek * 0.995, 2),
                    atr_dynamic_stop=round(cons_stop - atr_val * 0.5, 2),
                )
            else:
                # Phase 25：威科夫第五步 — JOC 后须在 LPS 缩量回测处入场
                direction = "观望"
                zone = (
                    f"JOC 已突破小溪 ({creek:.2f})，等待 LPS 缩量回测确认入场（威科夫第五步）"
                )
                _audit_watch('plan.joc_pending_lps', zone, prev_direction='做多')
                stop = StopLossModel(
                    conservative=round(cons_stop, 2),
                    aggressive=round(creek * 0.995, 2),
                    atr_dynamic_stop=round(cons_stop - atr_val * 0.5, 2),
                )
        elif _event_detected(spring):
            sp_detail_early = _get_latest_spring_detail(spring)
            spring_failed = (
                sp_detail_early
                and RecommendationEngine._get_attr(sp_detail_early, 'lifecycle_status') == 'failed'
            )
            if spring_failed:
                direction = "观望"
                zone = "Spring 生命周期已失效，等待新结构确认"
                _audit_watch('plan.spring_lifecycle_failed', zone)
                stop = StopLossModel(conservative=0.0, aggressive=0.0)
            else:
                # Phase 14: 孟氏 checklist — Spring 震仓后须 JOC 突破小溪再入场
                direction = "观望"
                spring_low = _get_spring_low(spring)
                if spring_low <= 0:
                    spring_low = current_price * 0.95
                zone = "Spring 震仓已现，等待 JOC 突破小溪或 LPS 缩量回测确认"
                _audit_watch('plan.spring_pending_joc', zone, prev_direction='做多')
                stop = StopLossModel(
                    conservative=round(spring_low * 0.99, 2),
                    aggressive=round(spring_low * 0.995, 2),
                    atr_dynamic_stop=round(spring_low - atr_val * 0.5, 2),
                )

        elif _event_detected(sos) and not _event_detected(joc) and not _event_detected(spring):
            # B14: 孤立 SOS 不足以给出做多计划，需 Spring/JOC/LPS 结构确认
            direction = "观望"
            sos_price = _event_price(sos, current_price)
            zone = f"SOS 突破 ({sos_price:.2f}) 待 Spring/JOC/LPS 结构确认，暂不建议追多"
            _audit_watch('plan.isolated_sos', zone, prev_direction='做多')
            stop = StopLossModel(conservative=0.0, aggressive=0.0)
        elif _event_detected(fti):
            ice = _event_level(fti, 'ice_level', current_price)
            lpsy_high = _get_lpsy_high(15)
            cons_stop = max(lpsy_high, ice * 1.01)
            if SignalExtractor.is_formal_lpsy(lpsy):
                direction = "做空"
                lpsy_price = _event_price(lpsy, current_price)
                zone = f"{lpsy_price:.2f} 附近 (FTI+LPSY 威科夫标准入场)"
                lpsy_detail = _event_latest(lpsy)
                if lpsy_detail:
                    lpsy_res = _as_float(
                        _event_get(lpsy_detail, 'resistance_level') or
                        _event_get(lpsy_detail, 'price'),
                        lpsy_price,
                    )
                    if lpsy_res > 0:
                        cons_stop = max(cons_stop, lpsy_res * 1.01)
                stop = StopLossModel(
                    conservative=round(cons_stop, 2),
                    aggressive=round(ice * 1.005, 2),
                    atr_dynamic_stop=round(cons_stop + atr_val * 0.5, 2),
                )
            else:
                direction = "观望"
                zone = (
                    f"FTI 已跌破冰层 ({ice:.2f})，等待 LPSY 缩量回测确认入场（威科夫第五步）"
                )
                _audit_watch('plan.fti_pending_lpsy', zone, prev_direction='做空')
                stop = StopLossModel(
                    conservative=round(cons_stop, 2),
                    aggressive=round(ice * 1.005, 2),
                    atr_dynamic_stop=round(cons_stop + atr_val * 0.5, 2),
                )
        elif _event_detected(upthrust):
            ut_detail = _event_latest(upthrust)
            ut_failed = (
                ut_detail
                and RecommendationEngine._get_attr(ut_detail, 'lifecycle_status') == 'failed'
            )
            if ut_failed:
                direction = "观望"
                zone = "Upthrust 生命周期已失效，等待新结构确认"
                _audit_watch('plan.upthrust_lifecycle_failed', zone)
                stop = StopLossModel(conservative=0.0, aggressive=0.0)
            elif not _event_detected(fti) and not _event_detected(sow):
                direction = "观望"
                ut_price = _event_price(upthrust, current_price)
                zone = f"Upthrust ({ut_price:.2f}) 待 SOW/FTI 结构确认，暂不建议追空"
                _audit_watch('plan.upthrust_pending_structure', zone, prev_direction='做空')
                stop = StopLossModel(conservative=0.0, aggressive=0.0)
            else:
                direction = "做空"
                ut_high = _get_upthrust_high(upthrust)
                if ut_high <= 0:
                    ut_high = current_price * 1.05
                zone = f"{current_price:.2f} 附近 (Upthrust诱多)"
                stop = StopLossModel(
                    conservative=round(ut_high * 1.01, 2),
                    aggressive=round(ut_high * 1.005, 2),
                    atr_dynamic_stop=round(ut_high + atr_val * 0.5, 2),
                )
        elif _event_detected(sow) and not _event_detected(fti) and not _event_detected(upthrust):
            # Phase 10: 孤立 SOW 对称 B14 — 待 FTI/Upthrust 结构确认
            direction = "观望"
            sow_price = _event_price(sow, current_price)
            zone = f"SOW 跌破 ({sow_price:.2f}) 待 FTI/Upthrust 结构确认，暂不建议追空"
            _audit_watch('plan.isolated_sow', zone, prev_direction='做空')

        # ── 仓位建议 (Phase+风险导向，与信号得分动态加权) ──
        normal_position_pct = 50.0
        if self.config and hasattr(self.config, 'thresholds'):
            ps_config = getattr(self.config.thresholds, 'POSITION_SIZING', None)
            if ps_config and hasattr(ps_config, 'normal_position_pct'):
                normal_position_pct = ps_config.normal_position_pct

        # 计算信号质量得分以与仓位进行动态联动
        market_env = MarketEnvironment.RANGE_BOUND
        if isinstance(pattern_results, dict) and 'market_env' in pattern_results:
            market_env = pattern_results['market_env']
        elif hasattr(pattern_results, 'market_env'):
            market_env = getattr(pattern_results, 'market_env')
        
        signal_quality = self.calculate_signal_quality(data, pattern_results, market_env, audit=False)
        final_score = signal_quality.score
        quality_score = float(final_score) / 100.0
        
        # 动态加权基准常规仓位百分比
        dynamic_base = normal_position_pct * (0.4 + 0.6 * quality_score)

        def _phase_position_sizing(phase_str: str, base_pct: float) -> tuple:
            is_reaccum = 'Reaccumulation' in phase_str or '再积累' in phase_str
            is_redistr = 'Redistribution' in phase_str or '再派发' in phase_str
            if 'Phase A' in phase_str or 'Phase B' in phase_str:
                factor = 0.30   # 25-35%: 早期高风险
            elif 'Phase D' in phase_str:
                factor = 0.875  # 75-100%: 最优入场区
            elif 'Phase E' in phase_str:
                factor = 0.625  # 50-75%: 趋势已确立
            elif is_reaccum or is_redistr:
                factor = 0.625
            else:
                factor = 0.50
            return (
                f"{base_pct * factor:.0f}% (Phase导向)",
                f"{base_pct * min(factor + 0.15, 1.0):.0f}% (Phase导向)",
                f"{base_pct * min(factor + 0.30, 1.0):.0f}% (Phase导向)",
            )

        def _scale_position_text(text: str, factor: float, label: str) -> str:
            if not text or text == "0%":
                return "0%"
            try:
                pct = float(str(text).split('%', 1)[0])
            except (TypeError, ValueError):
                return text
            return f"{pct * factor:.0f}% ({label})"

        cons, mod, aggr = _phase_position_sizing(phase_str, dynamic_base)
        pos_sizing = PositionSizingModel(
            conservative=cons, moderate=mod, aggressive=aggr
        )
        if direction == "观望":
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        # UTAD ST 证伪/风控保护拦截
        is_utad_falsified = False
        if _event_detected(utad) and not _event_get(utad, 'st_confirmed', True):
            is_utad_falsified = True
            direction = "做多"
            zone = "UTAD 二次测试放量或价格稳健未跌回，诱多证伪，实为强势筹码突破，建议顺势做多。"
            utad_high = _event_level(utad, 'breakout_price', current_price)
            res_level = _event_level(utad, 'resistance_level', current_price * 0.95)
            cons_stop = min(res_level, current_price * 0.92)
            stop = StopLossModel(
                conservative=round(cons_stop, 2),
                aggressive=round(utad_high * 0.95, 2),
                atr_dynamic_stop=round(current_price - atr_val * 2.0, 2),
            )
            pos_sizing = PositionSizingModel(
                conservative="30%",
                moderate="50%",
                aggressive="75%"
            )

        # ── 下跌/派发结构中 Spring 不足以确认做多 ──
        if (
            direction == "做多"
            and not _event_detected(joc)
            and PhaseAdapter.get_market_side(phase_str) == MarketSide.BEARISH.value
            and not is_utad_falsified
        ):
            prev = direction
            direction = "观望"
            zone = "下跌或派发结构中 Spring 需 JOC/结构确认，建议观望"
            _audit_watch('plan.bearish_structure_spring_block', zone, prev_direction=prev)
            stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        # ── 派发初期/中期做空逻辑拦截覆盖 (威科夫诊断与处方强制一致性) ──
        is_dist_early = PhaseAdapter.is_distribution_early(phase_str) and not is_utad_falsified
        if is_dist_early:
            prev = direction if direction != "观望" else None
            direction = "观望"
            zone = "空仓观望，等待派发结构进一步明朗"
            _audit_watch('plan.distribution_early_block', zone, prev_direction=prev)
            stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        # ── Spring 二次测试校验拦截 (未确认时强制做多拦截改签观望) ──
        sp_detail = _get_latest_spring_detail(spring)
        st_unconfirmed_spring = False
        if sp_detail:
            needs_st = RecommendationEngine._get_attr(sp_detail, 'needs_secondary_test', False)
            st_confirmed = RecommendationEngine._get_attr(sp_detail, 'st_confirmed', False)
            if needs_st and not st_confirmed:
                st_unconfirmed_spring = True

        if direction == "做多" and st_unconfirmed_spring and not is_utad_falsified:
            prev = direction
            direction = "观望"
            zone = "等待低点高于 Spring 且缩量的二次测试确认"
            _audit_watch('plan.spring_secondary_test_unconfirmed', zone, prev_direction=prev)
            stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        # ── 再派发 (Re-distribution) 熊市中继强力拦截做多 ──
        is_redist = 'Re-distribution' in phase_str or '再派发' in phase_str
        if is_redist and not is_utad_falsified:
            prev = direction if direction != "观望" else None
            direction = "观望"
            zone = "等待再派发区间破位或反弹至上沿阻力"
            _audit_watch('plan.redistribution_block', zone, prev_direction=prev)
            stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        # ── JOC 天量突破拦截过载 (Buying Climax) ──
        joc_warning = False
        if isinstance(joc, dict):
            joc_warning = joc.get('joc_overload_warning', False)
        else:
            joc_warning = getattr(joc, 'joc_overload_warning', False)

        if joc_warning and not is_utad_falsified:
            prev = direction if direction != "观望" else None
            direction = "观望"
            zone = "天量突破且收线不佳，警惕买入高潮 (Buying Climax)，建议观望"
            _audit_watch('plan.joc_overload_warning', zone, prev_direction=prev)
            stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        is_phase_ab = 'Phase A' in phase_str or 'Phase B' in phase_str
        is_phase_e = 'Phase E' in phase_str
        is_markup_markdown = 'Markup' in phase_str or 'Markdown' in phase_str
        if is_phase_ab:
            holding_period = "1-3个月 (波段)"
        elif is_phase_e:
            holding_period = "2-6周 (中线)"
        elif is_markup_markdown:
            holding_period = "2-8周 (中线)"
        else:
            holding_period = "1-2个月 (波段)"

        # ── 低信号质量强力拦截风控 (双层风控保护) ──
        is_mock_test = isinstance(pattern_results, dict) and len(pattern_results) < 8
        if direction != "观望" and final_score < 25 and len(data) >= 30 and not is_mock_test:
            prev = direction
            direction = "观望"
            zone = f"信号质量过低风控拦截 (当前得分: {final_score}/100)"
            _audit_watch('plan.low_signal_quality_block', zone, prev_direction=prev, score=final_score)
            stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        # Phase 25：威科夫第二/三步 — RS / 多周期方向硬门控
        searchlight_pre = (
            pattern_results.get('searchlight_arbitration') or {}
            if isinstance(pattern_results, dict) else {}
        )
        if (
            isinstance(searchlight_pre, dict)
            and searchlight_pre.get('available')
            and searchlight_pre.get('trade_bias') == 'watch_only'
            and direction != "观望"
            and not is_utad_falsified
        ):
            prev = direction
            direction = "观望"
            zone = searchlight_pre.get('resolution_hint') or "Searchlight 建议观望，等待结构与微观背景共振"
            _audit_watch('plan.searchlight_trade_bias_watch', zone, prev_direction=prev)
            stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)
            pos_sizing = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")

        if (
            isinstance(pattern_results, dict)
            and direction != "观望"
            and not is_utad_falsified
        ):
            rs = pattern_results.get('relative_strength') or {}
            rs_trend = rs.get('rs_trend') if isinstance(rs, dict) else None
            zero_pos = PositionSizingModel(conservative="0%", moderate="0%", aggressive="0%")
            zero_stop = StopLossModel(conservative=0.0, aggressive=0.0, atr_dynamic_stop=0.0)

            if (
                direction == "做多"
                and PhaseAdapter.is_accumulation(phase_str)
                and rs_trend == 'falling'
            ):
                prev = direction
                direction = "观望"
                zone = "吸筹阶段但相对强度走弱，不符合威科夫第二步，建议观望"
                _audit_watch('plan.rs_falling_accumulation_block', zone, prev_direction=prev, rs_trend=rs_trend)
                stop = zero_stop
                pos_sizing = zero_pos
            elif (
                direction == "做空"
                and PhaseAdapter.is_distribution(phase_str)
                and rs_trend == 'rising'
            ):
                prev = direction
                direction = "观望"
                zone = "派发阶段但相对强度仍走强，做空缺乏第二步支撑，建议观望"
                _audit_watch('plan.rs_rising_distribution_block', zone, prev_direction=prev, rs_trend=rs_trend)
                stop = zero_stop
                pos_sizing = zero_pos
            elif pattern_results.get('mtf_has_conflict'):
                details = pattern_results.get('mtf_conflict_details') or '周线与日线方向冲突'
                prev = direction
                direction = "观望"
                zone = f"跨周期冲突：{details}，等待多周期共振"
                _audit_watch('plan.mtf_conflict_block', zone, prev_direction=prev, conflict_details=details)
                stop = zero_stop
                pos_sizing = zero_pos

            searchlight = pattern_results.get('searchlight_arbitration') or {}
            if (
                direction != "观望"
                and isinstance(searchlight, dict)
                and searchlight.get('available')
            ):
                bias = searchlight.get('bias')
                entropy_degraded = bool(searchlight.get('entropy_degraded'))
                if searchlight.get('has_contradiction'):
                    prev = direction
                    direction = "观望"
                    stop = zero_stop
                    pos_sizing = zero_pos
                    if bias == 'bearish_microstructure' and PhaseAdapter.is_accumulation(phase_str):
                        zone = "Searchlight/WIE3 显示弱势微观结构，与吸筹做多计划冲突，建议观望"
                        rule_id = 'plan.searchlight_bearish_vs_accumulation'
                    elif bias == 'bullish_microstructure' and PhaseAdapter.is_distribution(phase_str):
                        zone = "Searchlight/WIE3 显示吸收或需求主导，与派发做空计划冲突，建议观望"
                        rule_id = 'plan.searchlight_bullish_vs_distribution'
                    else:
                        zone = "Searchlight/WIE3 与阶段或交易方向结论冲突，等待重新共振"
                        rule_id = 'plan.searchlight_contradiction'
                    _audit_watch(rule_id, zone, prev_direction=prev, bias=bias)
                elif entropy_degraded:
                    before_moderate = pos_sizing.moderate
                    pos_sizing = PositionSizingModel(
                        conservative=_scale_position_text(pos_sizing.conservative, 0.5, "WIE3高熵降级"),
                        moderate=_scale_position_text(pos_sizing.moderate, 0.5, "WIE3高熵降级"),
                        aggressive=_scale_position_text(pos_sizing.aggressive, 0.5, "WIE3高熵降级"),
                    )
                    self._decision_audit.record_position_reduce(
                        'plan.wie3_entropy_halve_position',
                        before_moderate,
                        pos_sizing.moderate,
                        "WIE3 高熵降级，仓位减半",
                        position_factor=0.5,
                        stage='trading_plan',
                        direction=direction,
                    )

        return TradingPlanModel(
            direction=direction,
            entry_zone=zone,
            stop_loss=stop,
            targets=TargetsModel(target_1=targets.get('target_1', 0), target_2=targets.get('target_2', 0)),
            position_sizing=pos_sizing,
            holding_period=holding_period,
        )

    def generate_risk_advice(self, quality: SignalQualityModel, plan: TradingPlanModel,
                             has_conflict: bool = False, conflict_details: str = "",
                             market_env: MarketEnvironment = None, data: Any = None,
                             phase_str: str = "") -> RiskAdviceModel:
        """
        生成分层风险建议 (Enhanced with volatility check and conflict detection)

        重要理论约束：
        - 当跨周期冲突时，所有方向的交易建议都应被抑制
        - 顺周线试错拿货（等Spring），优于逆周线试错砸盘（等LPSY）

        🔧 问题二修复：增加市场环境与交易方向的一致性检查
        - 做空 + 强多头环境 → 绝对观望
        - 做多 + 强多头环境 → 顺水推舟，降低观望阈值
        """
        score = getattr(quality, 'score', None) or (quality.get('score') if isinstance(quality, dict) else 0)
        direction = getattr(plan, 'direction', None) or (plan.get('direction') if isinstance(plan, dict) else "观望")

        def _audit_risk_watch(rule_id: str, message: str, **context: Any) -> None:
            self._decision_audit.record_watch(
                rule_id,
                message,
                direction_before=direction,
                stage='risk_advice',
                **context,
            )

        # ── 派发初期/中期做空逻辑拦截判定 (威科夫诊断与处方强制一致性) ──
        entry_zone = getattr(plan, 'entry_zone', '') or (plan.get('entry_zone') if isinstance(plan, dict) else '')
        if not entry_zone:
            entry_zone = ''
        is_utad_falsified = "诱多证伪" in entry_zone

        is_dist_early = False
        if phase_str and not is_utad_falsified:
            is_dist_early = PhaseAdapter.is_distribution_early(phase_str)
        elif not is_utad_falsified:
            # 鲁棒的 Fallback：从 trading_plan (plan) 的 entry_zone 识别
            if entry_zone == "空仓观望，等待派发结构进一步明朗":
                is_dist_early = True

        #  新增：检查方向与环境的冲突
        direction_env_conflict = False
        direction_env_match = False
        if is_utad_falsified:
            direction_env_conflict = False
            direction_env_match = True
        elif market_env:
            is_market_bullish = market_env in [MarketEnvironment.STRONG_BULL, MarketEnvironment.BULL]
            is_market_bearish = market_env in [MarketEnvironment.STRONG_BEAR, MarketEnvironment.BEAR]

            if direction == "做空" and is_market_bullish:
                direction_env_conflict = True  # 做空 + 强多头 = 冲突
            elif direction == "做多" and is_market_bearish:
                direction_env_conflict = True  # 做多 + 强空头 = 冲突
            elif direction == "做多" and is_market_bullish:
                direction_env_match = True  # 做多 + 强多头 = 匹配
            elif direction == "做空" and is_market_bearish:
                direction_env_match = True  # 做空 + 强空头 = 匹配

        # 安全获取属性辅助函数
        def _safe_get_stop(p_obj, field):
            stop_obj = getattr(p_obj, 'stop_loss', None) or (p_obj.get('stop_loss') if isinstance(p_obj, dict) else None)
            if not stop_obj:
                return 0.0
            if isinstance(stop_obj, dict):
                return float(stop_obj.get(field, 0.0))
            return float(getattr(stop_obj, field, 0.0))

        def _safe_get_pos(p_obj, field):
            pos_obj = getattr(p_obj, 'position_sizing', None) or (p_obj.get('position_sizing') if isinstance(p_obj, dict) else None)
            if not pos_obj:
                return "0%"
            if isinstance(pos_obj, dict):
                return str(pos_obj.get(field, "0%"))
            return str(getattr(pos_obj, field, "0%"))

        # 刚性止损提示说明
        stop_desc = "无明确止损"
        cons_stop_val = _safe_get_stop(plan, 'conservative')
        if direction == "做多" and cons_stop_val > 0:
            stop_desc = f"严格设于结构支撑/Spring极值点下方 {cons_stop_val:.2f} (结构失效位)"
        elif direction == "做空" and cons_stop_val > 0:
            stop_desc = f"严格设于结构阻力/Upthrust极值点上方 {cons_stop_val:.2f} (结构失效位)"

        def get_item(mode: str) -> RiskAdviceItem:
            # 优先处理派发初中期绝对观望拦截
            if is_dist_early:
                _audit_risk_watch(
                    'risk.distribution_early_absolute_watch',
                    "派发初期/中期强制绝对观望",
                    mode=mode,
                )
                if mode in ["conservative", "moderate"]:
                    return RiskAdviceItem(
                        action="绝对观望",
                        reason="当前处于派发初期/中期（Phase A/B），主力在测试需求，价格仍会有反复冲高（UT）。虽然有弱势信号迹象，但供应尚未完全主控，下方仍有需求抵抗，此时做空极易被轧空。根据威科夫原则，当前任何做空建议皆无效，应保持空仓观望。",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="耐心空仓，等待进入 Phase C（出现决定性的 UTAD）或 Phase D（出现有效 SOW 破位及缩量回踩确认）"
                    )
                else:  # aggressive
                    return RiskAdviceItem(
                        action="绝对观望",
                        reason="即使在激进视角下，在派发 Phase A/B 结构未明朗前强行参与做空也是高危行为，下方存在 Spring 抵抗及结构重建。",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="耐心空仓，等待进入 Phase C（出现决定性的 UTAD）或 Phase D（出现有效 SOW 破位及缩量回踩确认）"
                    )
            # 获取或动态计算对应的仓位
            has_explicit_pos = False
            if plan and isinstance(plan, dict) and 'position_sizing' in plan:
                has_explicit_pos = True
            elif plan and hasattr(plan, 'position_sizing') and getattr(plan, 'position_sizing') is not None:
                has_explicit_pos = True

            if not has_explicit_pos:
                # 使用旧版默认基准仓位：保守 10%，稳健 15%，激进 20%
                base_pct = 10.0 if mode == "conservative" else 15.0 if mode == "moderate" else 20.0
                
                # 如果传入了 data，则进行波动率与流动性风控计算
                if data is not None and len(data) > 0:
                    current_price = data['Close'].iloc[-1]
                    atr = data['ATR'].iloc[-1] if 'ATR' in data.columns else current_price * 0.03
                    vol_ma20 = data['Volume_MA20'].iloc[-1] if 'Volume_MA20' in data.columns else (data['Volume'].iloc[-1] if 'Volume' in data.columns else 1000000)
                    
                    # 1. 波动率仓位控制 (ATR Cap)
                    atr_ratio = atr / current_price if current_price > 0 else 0.03
                    vol_cap = 0.04  # 4% 限制阈值
                    vol_multiplier = 1.0
                    if atr_ratio > vol_cap:
                        vol_multiplier = vol_cap / atr_ratio
                        
                    # 2. 流动性惩罚 (Volume MA20 Penalty)
                    liq_threshold = 1000000.0  # 100万阈值
                    liq_multiplier = 1.0
                    if vol_ma20 < liq_threshold:
                        liq_multiplier = vol_ma20 / liq_threshold
                        
                    # 复合调整 (取较小的乘数以保障安全)
                    adjusted_pct = base_pct * min(vol_multiplier, liq_multiplier)
                    
                    # 判断是否触发了任何风控惩罚
                    if vol_multiplier < 1.0 or liq_multiplier < 1.0:
                        pos_desc = f"{adjusted_pct:.1f}% 仓位上限"
                        self._decision_audit.record_position_reduce(
                            'risk.volatility_or_liquidity_cap',
                            f"{base_pct:.1f}%",
                            pos_desc,
                            "波动率或流动性风控压缩仓位上限",
                            position_factor=min(vol_multiplier, liq_multiplier),
                            stage='risk_advice',
                            mode=mode,
                            atr_ratio=round(atr_ratio, 4),
                            vol_ma20=float(vol_ma20),
                        )
                    else:
                        pos_desc = f"{adjusted_pct:.1f}%"
                else:
                    pos_desc = f"{base_pct:.0f}%"
            else:
                pos_desc = _safe_get_pos(plan, mode)

            #  问题二修复：方向与环境冲突时，强制观望
            if direction_env_conflict:
                env_name = market_env.value if hasattr(market_env, 'value') else str(market_env)
                _audit_risk_watch(
                    'risk.direction_env_conflict',
                    f"方向与环境冲突：{direction}方向与{env_name}环境冲突",
                    mode=mode,
                    market_env=env_name,
                )
                if mode == "conservative":
                    return RiskAdviceItem(
                        action="绝对观望",
                        reason=f"方向与环境冲突：{direction}方向与{env_name}环境冲突，建议等待环境转弱或信号转向",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待大盘环境与交易方向一致"
                    )
                elif mode == "moderate":
                    return RiskAdviceItem(
                        action="观望",
                        reason=f"方向与环境冲突：{direction}方向与{env_name}环境冲突，建议等待",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待大盘环境转为中性或一致"
                    )
                else:  # aggressive
                    return RiskAdviceItem(
                        action="等待信号",
                        reason=f"方向与环境冲突：{direction}方向与{env_name}环境冲突，等待环境或信号明确",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待高置信度日线强反转形态"
                    )

            # 关键修复：跨周期冲突时，所有方向的交易建议都应被抑制
            if has_conflict:
                _audit_risk_watch(
                    'risk.mtf_conflict',
                    f"跨周期冲突：{conflict_details}",
                    mode=mode,
                )
                if mode == "conservative":
                    return RiskAdviceItem(
                        action="绝对观望", 
                        reason=f"跨周期冲突：{conflict_details}",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待高时间周期（周线/月线）趋势恢复一致"
                    )
                elif mode == "moderate":
                    return RiskAdviceItem(
                        action="观望", 
                        reason=f"跨周期冲突：{conflict_details}",
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待周期共振或明确的次级折返测试成功"
                    )
                else:  # aggressive — Phase 26：与交易计划硬门控一致，MTF 冲突一律观望
                    return RiskAdviceItem(
                        action="观望",
                        reason=(
                            f"跨周期冲突：{conflict_details}。"
                            "与交易计划一致：跨周期不一致时不建议参与。"
                        ),
                        position="0%",
                        stop_loss=stop_desc,
                        entry_condition="等待高时间周期与日线结构共振"
                    )

            if direction == "观望":
                _audit_risk_watch('risk.plan_direction_watch', "交易计划为观望，风险建议同步观望", mode=mode)
                return RiskAdviceItem(
                    action="观望", 
                    reason="无清晰信号",
                    position="0%",
                    stop_loss=stop_desc,
                    entry_condition="等待威科夫 Phase C 震仓或 Phase D 突破信号"
                )

            #  问题二修复：方向与环境匹配时，降低观望阈值
            if direction_env_match:
                if mode == "conservative":
                    action = "稳步参与" if score >= 60 else "观望"
                    reason = f"信号得分 {score}/100，且交易方向与市场环境一致（顺水推舟）"
                    return RiskAdviceItem(
                        action=action, 
                        reason=reason,
                        position=pos_desc if action != "观望" else "0%",
                        stop_loss=stop_desc,
                        entry_condition="回试 Creek 或 Spring/UT 低点不破 + 缩量确认"
                    )
                elif mode == "moderate":
                    action = "按计划参与" if score >= 40 else "观望"
                    reason = f"信号得分 {score}/100，且交易方向与市场环境一致（顺水推舟）"
                    return RiskAdviceItem(
                        action=action, 
                        reason=reason,
                        position=pos_desc if action != "观望" else "0%",
                        stop_loss=stop_desc,
                        entry_condition="结构内局部二测(ST)确认供应耗尽"
                    )
                else:  # aggressive
                    if score >= 20:
                        action = "激进试错"
                        reason = f"信号得分 {score}/100，方向与环境一致，顺水推舟"
                    else:
                        action = "极轻仓试错"
                        reason = f"评分较低，严控止损，等待日线级别明确信号"
                    return RiskAdviceItem(
                        action=action, 
                        reason=reason,
                        position=pos_desc,
                        stop_loss=stop_desc,
                        entry_condition="出现微观 VSA No-Supply/No-Demand 信号"
                    )

            # 原有逻辑（方向与环境不明确匹配时）
            if mode == "conservative":
                action = "稳步参与" if score >= 70 else "绝对观望"
                return RiskAdviceItem(
                    action=action, 
                    reason=f"信号得分 {score}/100",
                    position=pos_desc if action != "绝对观望" else "0%",
                    stop_loss=stop_desc,
                    entry_condition="Phase D 强势信号(SOS/JOC)放量突围且回踩不破"
                )
            elif mode == "moderate":
                action = "按计划参与" if score >= 50 else "观望"
                return RiskAdviceItem(
                    action=action, 
                    reason=f"信号得分 {score}/100",
                    position=pos_desc if action != "观望" else "0%",
                    stop_loss=stop_desc,
                    entry_condition="关键支撑/阻力位的 Spring/UT 震仓确认"
                )
            else: # aggressive
                if score >= 30:
                    action = "激进试错"
                    reason = f"信号得分 {score}/100，顺周线方向试错"
                else:
                    action = "极轻仓试错"
                    reason = f"评分较低，严控止损，等待日线级别明确信号"
                return RiskAdviceItem(
                    action=action, 
                    reason=reason,
                    position=pos_desc,
                    stop_loss=stop_desc,
                    entry_condition="短线突破高潮/恐慌低吸且紧扣极值点设防"
                )

        return RiskAdviceModel(
            conservative=get_item("conservative"),
            moderate=get_item("moderate"),
            aggressive=get_item("aggressive")
        )

    @staticmethod
    def get_execution_score(current_price: float, support: float, resistance: float, direction: str) -> float:
        """
        计算交易可执行性得分 (风盈比与距离支撑/阻力位的百分比)
        """
        if direction == "做多":
            if current_price <= support or current_price >= resistance:
                return 10.0
            dist_to_support = (current_price - support) / current_price
            
            # 越接近支撑位得分越高，理想距离在 1-5%
            if dist_to_support < 0.05:
                return round(100.0 * (1.0 - dist_to_support/0.05), 2)
            return 20.0
        else:
            if current_price >= resistance or current_price <= support:
                return 10.0
            dist_to_res = (resistance - current_price) / current_price
            if dist_to_res < 0.05:
                return round(100.0 * (1.0 - dist_to_res/0.05), 2)
            return 20.0

    @staticmethod
    def generate_phase_e_exit_strategy(data: Any, pattern_results: Dict[str, Any], targets: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成Phase E退出策略 (Wyckoff 操盘法)

        Wyckoff理论退出条件:
        1. 达到因果目标位 (基于P&F或波动率收缩)
        2. 量价背离 (Effort vs Result)
        3. Phase转换信号 (PSY/PS出现)
        4. 止损触发
        """
        current_price = data['Close'].iloc[-1]
        vol_ma20 = data['Volume_MA20'].iloc[-1] if 'Volume_MA20' in data.columns else data['Volume'].rolling(20).mean().iloc[-1]
        recent_vol = data['Volume'].iloc[-1]
        recent_close = data['Close'].iloc[-1]
        prev_close = data['Close'].iloc[-2]
        atr = data['ATR'].iloc[-1] if 'ATR' in data.columns else (data['High'] - data['Low']).rolling(14).mean().iloc[-1]

        exit_signals = []
        trailing_stop = 0.0

        # 1. 目标位检查
        target_2 = targets.get('target_2', targets.get('likely_target', 0))
        target_1 = targets.get('target_1', targets.get('minimum_target', 0))
        direction = getattr(pattern_results, 'direction', None) or '观望'

        if direction == '做多':
            if target_2 > 0 and current_price >= target_2:
                exit_signals.append(f"已触及第二目标位 {target_2:.2f}，建议全部止盈")
            elif target_1 > 0 and current_price >= target_1:
                exit_signals.append(f"已触及第一目标位 {target_1:.2f}，建议部分止盈(50%)")

            # Trailing stop: 最近摆动低点或 ATR 动态
            swing_low_10 = float(data['Low'].tail(10).min())
            atr_stop = current_price - atr * 3
            trailing_stop = max(swing_low_10, atr_stop)
        elif direction == '做空':
            if target_2 > 0 and current_price <= target_2:
                exit_signals.append(f"已触及第二目标位 {target_2:.2f}，建议全部止盈")
            elif target_1 > 0 and current_price <= target_1:
                exit_signals.append(f"已触及第一目标位 {target_1:.2f}，建议部分止盈(50%)")

            swing_high_10 = float(data['High'].tail(10).max())
            atr_stop = current_price + atr * 3
            trailing_stop = min(swing_high_10, atr_stop)

        # 2. 量价背离检查
        vol_ratio = recent_vol / vol_ma20 if vol_ma20 > 0 else 1.0
        price_change = (recent_close - prev_close) / prev_close

        if direction == '做多':
            # 缩量新高 = 需求枯竭
            if vol_ratio < 0.6 and price_change > 0:
                exit_signals.append(f"缩量创新高(量比{vol_ratio:.2f})：需求枯竭警告，建议减仓")
            # 高量滞涨 = 派发
            if vol_ratio > 1.5 and abs(price_change) < 0.005:
                exit_signals.append(f"高量滞涨(量比{vol_ratio:.2f})：供应进入，警惕Phase A派发信号")
        elif direction == '做空':
            if vol_ratio < 0.6 and price_change < 0:
                exit_signals.append(f"缩量创新低(量比{vol_ratio:.2f})：供应枯竭警告，建议减仓")
            if vol_ratio > 1.5 and abs(price_change) < 0.005:
                exit_signals.append(f"高量滞跌(量比{vol_ratio:.2f})：需求进入，警惕Phase A吸筹信号")

        # 3. SOT (Shortening of Thrust) 检测
        sot_detected, sot_desc = RecommendationEngine._detect_sot(data, direction)
        if sot_detected:
            exit_signals.append(sot_desc)

        # 兼容性处理：如果 pattern_results 是字典，且包含 'events_detected'，则从中提取核心事件
        if isinstance(pattern_results, dict):
            events = pattern_results.get('events_detected') or pattern_results
        else:
            events = pattern_results

        # 4. UTAD (终极推力) 检测 — Phase E 耗尽信号
        utad = RecommendationEngine._get_attr(events, 'utad')
        utad_detected = getattr(utad, 'detected', False) if utad else False
        if utad_detected:
            utad_type = getattr(utad, 'type', '')
            if direction == '做多' and utad_type == 'buying_climax':
                exit_signals.append("检测到UTAD(买入高潮)：最后的追高需求，上升动能耗尽，建议止盈")
            elif direction == '做空' and utad_type == 'selling_climax':
                exit_signals.append("检测到UTAD(抛售高潮)：最后的恐慌供应，下跌动能耗尽，建议止盈")

        # 5. LPSY/PSY 检测 — Phase A 反转信号
        lpsy = RecommendationEngine._get_attr(events, 'lpsy')
        if getattr(lpsy, 'detected', False) if lpsy else False:
            exit_signals.append("检测到LPSY(最后供应点)：供应重新出现，趋势面临反转风险，建议减仓")
        ps = RecommendationEngine._get_attr(events, 'preliminary_support')
        ps_detected = getattr(ps, 'detected', False) if ps else False
        if direction == '做空' and ps_detected:
            exit_signals.append("检测到PSY(初次支撑)：需求开始进入，下跌趋势可能终结，建议止盈")

        return {
            'exit_signals': exit_signals,
            'trailing_stop': round(trailing_stop, 2),
            'current_price': round(current_price, 2),
            'atr': round(atr, 2),
            'action': '部分止盈' if len(exit_signals) <= 1 else ('全部止盈' if len(exit_signals) >= 2 else '持仓观察'),
            'summary': '; '.join(exit_signals) if exit_signals else '无明确退出信号，继续按计划持有',
        }

    @staticmethod
    def _detect_sot(data: Any, direction: str) -> tuple:
        """
        SOT (Shortening of Thrust / 推力缩短) 检测

        Wyckoff Phase B→C 和 Phase E 的关键信号:
        - 上涨趋势中：当前浪比前浪幅度缩小但量能不减 = 需求衰竭
        - 下跌趋势中：当前浪比前浪幅度缩小但量能不减 = 供应衰竭

        Returns:
            (detected: bool, description: str)
        """
        df = data.tail(40)
        if len(df) < 20:
            return False, ""

        half = len(df) // 2
        wave1 = df.iloc[:half]
        wave2 = df.iloc[half:]

        wave1_range = wave1['High'].max() - wave1['Low'].min()
        wave2_range = wave2['High'].max() - wave2['Low'].min()
        wave1_vol = wave1['Volume'].mean()
        wave2_vol = wave2['Volume'].mean()

        safe_range1 = wave1_range if wave1_range > 0 else 1e-9
        thrust_shrinkage = wave2_range / safe_range1
        vol_change = wave2_vol / wave1_vol if wave1_vol > 0 else 1.0

        if direction == '做多':
            if thrust_shrinkage < 0.7 and vol_change > 0.9:
                return True, f"SOT检测：上涨浪幅度缩小至{thrust_shrinkage*100:.0f}%但量能维持(量比{vol_change:.2f})→需求衰竭，建议减仓"
        elif direction == '做空':
            if thrust_shrinkage < 0.7 and vol_change > 0.9:
                return True, f"SOT检测：下跌浪幅度缩小至{thrust_shrinkage*100:.0f}%但量能维持(量比{vol_change:.2f})→供应衰竭，建议减仓"

        return False, ""
