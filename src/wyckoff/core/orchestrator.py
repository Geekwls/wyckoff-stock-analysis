import logging
import pandas as pd
from typing import Dict, Any, Optional
from .data_fetcher import WyckoffDataFetcher
from .pattern_detector import WyckoffPatternDetector
from .recommendation_engine import RecommendationEngine
from .point_and_figure import calculate_cause_effect_from_pnf
from .signal_extractor import SignalExtractor, set_cached_phase_result
from .searchlight_enrichment import enrich_patterns_with_searchlight
from .wie3_market_state_service import WIE3MarketStateService
from ..config.settings import WyckoffConfig, WyckoffThresholds
from ..exceptions import WyckoffError, DataError, CalculationError
from .enums import MarketEnvironment
from .cache_service import CacheService

logger = logging.getLogger(__name__)

class WyckoffOrchestrator:
    """
    威科夫分析编排器 (P2 #1)
    负责驱动整个分析生命周期
    """

    def __init__(self, config: WyckoffConfig = None, wie3_service: Optional[WIE3MarketStateService] = None):
        self.config = config or WyckoffConfig()
        self.data_fetcher = WyckoffDataFetcher(self.config)
        self.rec_engine = RecommendationEngine(self.config)
        self._analysis_cache = CacheService.get_instance().get_legacy_lru_adapter(
            namespace="orchestrator_analysis",
            max_size=256,
            ttl_seconds=3600,
        )
        self.thresholds = getattr(self.config, 'thresholds', None) or WyckoffThresholds()
        if wie3_service is not None:
            self._wie3_service = wie3_service
        else:
            self._wie3_service = WIE3MarketStateService(self.thresholds)

    def run_analysis(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """
        运行完整分析流程

        将分析流程拆分为清晰的步骤，提高可读性和可测试性。
        """
        try:
            resolved_symbol, data = self._fetch_and_prepare_data(symbol, period)

            from .multi_timeframe_coordinator import MultiTimeframeCoordinator
            weekly_data = None
            hourly_data = None
            try:
                _, weekly_data = self.data_fetcher.fetch_data(symbol, period, frequency="1wk")
            except Exception as e:
                logger.info(f"无法获取周线数据，将尝试日线重采样: {e}")
            try:
                _, hourly_data = self.data_fetcher.fetch_data(symbol, "1m", frequency="1h")
            except Exception as e:
                logger.info(f"无法获取小时线数据，忽略小时线共振: {e}")

            mtf_coordinator = MultiTimeframeCoordinator.build_from_daily(
                data,
                weekly_data=weekly_data,
                hourly_data=hourly_data,
            )

            patterns, detector = self._detect_patterns_and_phase(data)
            benchmark_df = self._fetch_benchmark_data(resolved_symbol, period)
            patterns = self._enrich_patterns_with_rs(resolved_symbol, period, data, patterns, benchmark_df)
            patterns = self._enrich_patterns_with_searchlight(resolved_symbol, period, data, patterns, benchmark_df)
            patterns['symbol'] = resolved_symbol
            market_env = self._analyze_market_env(resolved_symbol, period)
            if isinstance(market_env, dict):
                patterns['market_env'] = market_env.get('environment', MarketEnvironment.UNKNOWN)
            else:
                patterns['market_env'] = market_env

            quality, trading_plan, risk_advice, resonance_result = self._generate_recommendations(
                data, patterns, market_env, detector, mtf_coordinator
            )

            return self._assemble_result(
                resolved_symbol, data, patterns, market_env,
                quality, trading_plan, risk_advice, resonance_result
            )

        except (DataError, CalculationError):
            raise
        except WyckoffError:
            raise
        except Exception as e:
            logger.exception(f"分析执行异常: {symbol}")
            raise CalculationError("Orchestrator", str(e)) from e

    def _fetch_and_prepare_data(self, symbol: str, period: str) -> tuple:
        resolved_symbol, data = self.data_fetcher.fetch_data(symbol, period)
        return resolved_symbol, data

    def _detect_patterns_and_phase(self, data: pd.DataFrame) -> tuple:
        detector = WyckoffPatternDetector(data, self.config, self._analysis_cache)

        phase_info = detector.identify_phase()
        set_cached_phase_result(detector, phase_info)
        phase_str = SignalExtractor.get_effective_phase(phase_info)

        if hasattr(detector, 'sw_detector') and hasattr(detector.sw_detector, 'set_current_phase'):
            detector.sw_detector.set_current_phase(phase_str)

        # 与报告同源：events_detected 含派发 suppression
        patterns = SignalExtractor.build_scoring_payload(phase_info)
        return patterns, detector

    def _enrich_patterns_with_rs(
        self,
        symbol: str,
        period: str,
        data: pd.DataFrame,
        patterns: Dict[str, Any],
        benchmark_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Phase 25：为 orchestrator 分析链附加相对强度（威科夫第二步）。"""
        if patterns.get('relative_strength'):
            return patterns
        try:
            from .relative_strength_analyzer import RelativeStrengthAnalyzer
            if benchmark_df is None:
                from .symbol_resolver import SymbolResolver
                index_symbol = SymbolResolver().resolve_benchmark_index(symbol)
                if not index_symbol:
                    return patterns
                _, benchmark_df = self.data_fetcher.fetch_data(index_symbol, period)
            
            patterns['relative_strength'] = RelativeStrengthAnalyzer(
                data, symbol
            ).calculate_rs(benchmark_df)
        except Exception as exc:
            logger.debug(f"RS enrichment skipped for {symbol}: {exc}")
        return patterns

    def _enrich_patterns_with_searchlight(
        self,
        symbol: str,
        period: str,
        data: pd.DataFrame,
        patterns: Dict[str, Any],
        index_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Attach Searchlight/WIE arbitration to the orchestrator decision path."""
        if index_df is None:
            index_df = self._fetch_benchmark_data(symbol, period)
        return enrich_patterns_with_searchlight(
            patterns,
            data,
            self._wie3_service,
            self.thresholds,
            index_df=index_df,
            resolve_index_df=lambda: index_df if index_df is not None else self._fetch_benchmark_data(symbol, period),
        )

    def _fetch_benchmark_data(self, symbol: str, period: str) -> Optional[pd.DataFrame]:
        try:
            from .symbol_resolver import SymbolResolver

            index_symbol = SymbolResolver().resolve_benchmark_index(symbol)
            if not index_symbol:
                return None
            _, index_df = self.data_fetcher.fetch_data(index_symbol, period)
            return index_df
        except Exception as exc:
            logger.debug(f"Benchmark fetch skipped for Searchlight ({symbol}): {exc}")
            return None

    def _generate_recommendations(
        self, data: pd.DataFrame, patterns: Dict, market_env: Any, detector,
        mtf_coordinator: Optional[Any] = None
    ) -> tuple:
        resonance_result = None
        has_conflict = False
        conflict_details = ""

        if mtf_coordinator:
            signal_type, detected_direction = SignalExtractor.resolve_primary_signal(patterns)
            if signal_type == 'none' or detected_direction == 'neutral':
                resonance_result = mtf_coordinator.no_signal_resonance()
            else:
                resonance_result = mtf_coordinator.verify_signal_resonance(
                    signal_type, detected_direction, patterns
                )
                weekly_dir = resonance_result.get('weekly_trend', {}).get('direction', 'neutral')
                if weekly_dir != 'neutral' and weekly_dir != detected_direction:
                    has_conflict = True
                    conflict_details = (
                        f"周线趋势方向为 {weekly_dir}，但日线威科夫信号 {signal_type.upper()} "
                        f"方向为 {detected_direction}，二者冲突。"
                    )

        if resonance_result:
            evr = resonance_result.get('evr_resonance') or {}
            if isinstance(evr, dict):
                patterns['mtf_evr_resonance'] = evr
            hourly = resonance_result.get('hourly_entry') or {}
            intraday = hourly.get('intraday_vsa')
            if isinstance(intraday, dict) and intraday.get('available'):
                patterns['intraday_vsa'] = intraday

        patterns['mtf_has_conflict'] = has_conflict
        patterns['mtf_conflict_details'] = conflict_details

        symbol = patterns.get('symbol') if isinstance(patterns, dict) else None
        self.rec_engine.begin_decision_audit(symbol)

        quality = self.rec_engine.calculate_signal_quality(data, patterns, market_env)
        targets = self._calculate_targets(detector, patterns)
        trading_plan = self.rec_engine.generate_trading_plan(data, patterns, targets, precomputed_score=quality.score)
        risk_advice = self.rec_engine.generate_risk_advice(
            quality, trading_plan,
            has_conflict=has_conflict,
            conflict_details=conflict_details,
            market_env=market_env,
            data=data,
            phase_str=patterns.get('phase', '')
        )

        return quality, trading_plan, risk_advice, resonance_result

    def get_decision_audit(self) -> Dict[str, Any]:
        """Return strategy decision audit log from the recommendation engine."""
        return self.rec_engine.get_decision_audit()

    def _assemble_result(
        self, symbol: str, data: pd.DataFrame, patterns: Dict,
        market_env: Any, quality: Dict, trading_plan: Dict, risk_advice: Dict,
        resonance_result: Optional[Dict] = None
    ) -> Dict[str, Any]:
        res = {
            "symbol": symbol,
            "data": data,
            "patterns": patterns,
            "market_env": market_env,
            "quality": quality,
            "trading_plan": trading_plan,
            "risk_advice": risk_advice,
            "strategy_decision_audit": self.rec_engine.get_decision_audit(),
        }
        if resonance_result:
            res["resonance"] = resonance_result
        return res

    def _analyze_market_env(self, symbol: str, period: str) -> Any:
        try:
            from .market_context_analyzer import MarketContextAnalyzer
            from .symbol_resolver import SymbolResolver

            index_symbol = SymbolResolver().resolve_benchmark_index(symbol)
            if not index_symbol:
                return MarketEnvironment.UNKNOWN

            _, index_data = self.data_fetcher.fetch_data(index_symbol, period)
            context = MarketContextAnalyzer(index_data, index_symbol).analyze()
            return context.get('environment', MarketEnvironment.UNKNOWN)
        except Exception as e:
            logger.info(f"市场环境分析失败 ({symbol}): {e}")
            return MarketEnvironment.UNKNOWN

    def _calculate_targets(
        self,
        detector: WyckoffPatternDetector,
        patterns: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """基于 P&F 因果测算目标位，派发/吸筹阶段决定投射方向。"""
        if detector.data is None or len(detector.data) < 20:
            return {}

        patterns = patterns or {}
        events = patterns.get('events_detected')
        tr = SignalExtractor.get_event_dict(events, 'trading_range') if events else {}
        if not tr.get('high') or not tr.get('low'):
            tr = detector.detect_trading_range()

        tr_high, tr_low = tr.get('high'), tr.get('low')
        if not tr_high or not tr_low:
            return {}

        if (
            tr.get('invalidated_tr')
            or tr.get('transition_period')
            or tr.get('invalidation_severity') in {'warning', 'invalidated', 'distribution_risk', 'markup_breakout'}
        ):
            direction = tr.get('breakout_direction') or 'unknown'
            return {
                'method': 'transition_period' if tr.get('transition_period') else 'invalidated_tr',
                'direction': direction,
                'target_1': 0.0,
                'target_2': 0.0,
                'target_3': 0.0,
                'full_target': 0.0,
                'horizontal_count': 0,
                'base_effect': 0.0,
                'description': (
                    f"原TR({float(tr_low):.2f}-{float(tr_high):.2f})已被价格{direction}突破，"
                    "旧因果目标暂停使用，需等待新交易区间重新形成。"
                ),
            }

        phase = patterns.get('phase', '')
        scoped = detector.data
        start_idx = tr.get('range_start_idx')
        if start_idx is not None:
            scoped = detector.data.iloc[int(start_idx):].copy()

        if len(scoped) < 20:
            return {}

        cause_effect = calculate_cause_effect_from_pnf(
            scoped,
            phase=phase,
            known_tr_high=float(tr_high),
            known_tr_low=float(tr_low),
            tr_col_start_idx=0,
        )
        pnf_targets = cause_effect.get('targets') or {}
        if not pnf_targets:
            return {}

        direction = cause_effect.get('breakout_direction', 'up')
        return {
            'target_1': pnf_targets.get('target_1'),
            'target_2': pnf_targets.get('target_2'),
            'target_3': pnf_targets.get('target_3'),
            'full_target': pnf_targets.get('full_target'),
            'direction': direction,
            'method': cause_effect.get('method'),
            'horizontal_count': cause_effect.get('horizontal_count'),
            'base_effect': cause_effect.get('base_effect'),
            'description': cause_effect.get('description'),
        }
