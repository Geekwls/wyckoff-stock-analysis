#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析器 - Facade (库层)
Wyckoff Analyzer - Facade for Orchestrator and Detectors

这是纯库层代码，不依赖任何应用层代码。
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any, TYPE_CHECKING, Union
from datetime import datetime

# WIE 3.0 MVP 类型导入 (用于类型提示)
if TYPE_CHECKING:
    from .core.market_state import MarketState

# 库层内部导入
from .config.settings import WyckoffConfig, WyckoffThresholds
from .core.enums import MarketEnvironment, WyckoffPhase
from .core.cache_service import CacheService, IndexDataCache
from .core.orchestrator import WyckoffOrchestrator
from .core.pattern_detector import WyckoffPatternDetector
from .core.law_analyzer import WyckoffLawAnalyzer
from .core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from .core.relative_strength_analyzer import RelativeStrengthAnalyzer
from .core.report_generator import WyckoffReportGenerator
from .core.signal_extractor import SignalExtractor, get_events_from_phase
from .core.point_and_figure import PointAndFigureCalculator, calculate_cause_effect_from_pnf
from .core.sos_sow_analyzer import SOSSOWAnalyzer
from .core.market_context_analyzer import MarketContextAnalyzer
from .core.wie3_market_state_service import WIE3MarketStateService
from .exceptions import (
    WyckoffError, DataError, CalculationError, PatternNotFoundError,
    DataFetchError, InsufficientDataError
)

logger = logging.getLogger(__name__)


class _IndexDataWrapper:
    """
    轻量级指数数据包装器 (P1.1)

    当使用共享 IndexDataCache 时，不需要创建完整的 WyckoffAnalyzer 实例，
    只需要一个提供 .data 属性的对象即可。
    """
    def __init__(self, data: pd.DataFrame):
        self.data = data


class WyckoffAnalyzer:
    """
    威科夫分析器 (Facade)

    在 P2 重构中，我们将控制流和决策逻辑移交给了 WyckoffOrchestrator 和 RecommendationEngine。
    此类作为统一入口保持向下兼容。

    这是纯库层代码，可以安全地从任何应用层导入使用。
    """

    def __init__(
        self,
        symbol: str,
        period: str = "1y",
        config: WyckoffConfig = None,
        cache_service: Optional[CacheService] = None,
        index_data_cache: Optional['IndexDataCache'] = None,
    ):
        self.symbol = symbol
        self.period = period
        self.config = config or WyckoffConfig()
        self.index_data_cache = index_data_cache
        
        # 提取市场类型并注入动态阈值系统
        from .core.symbol_resolver import SymbolResolver
        try:
            market_info = SymbolResolver().resolve(self.symbol)
            self.thresholds = WyckoffThresholds(market_type=market_info.market.value)
        except Exception:
            self.thresholds = WyckoffThresholds()
            
        self.cache_service = cache_service or CacheService.get_instance()
        self._analysis_cache = self.cache_service.get_legacy_lru_adapter(
            namespace="analysis",
            max_size=256,
            ttl_seconds=3600,
        )

        # 核心编排器（共享 WIE3 服务实例以复用 memoized 结果）
        self._wie3_service = WIE3MarketStateService(self.thresholds)
        self.orchestrator = WyckoffOrchestrator(self.config, wie3_service=self._wie3_service)
        self.wie3_last_result = None
        self.wie3_market_state = None  # 存储最新的市场状态

        # 运行时数据与探测器 (fetch_data 后初始化)
        self.data = None
        self.pattern_detector = None
        self.law_analyzer = None
        self.mtf_analyzer = None
        self.rs_analyzer = None

        self._index_analyzer_cache: Optional[Union['WyckoffAnalyzer', '_IndexDataWrapper']] = None

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """清理资源"""
        self._analysis_cache.invalidate()
        if hasattr(self.orchestrator.data_fetcher, 'logout_baostock'):
            self.orchestrator.data_fetcher.logout_baostock()

    def fetch_data(self, frequency: str = "1d") -> pd.DataFrame:
        """获取数据并初始化所有探测器"""
        self._wie3_service.clear_cache()
        self.wie3_last_result = None
        self.wie3_market_state = None
        self.symbol, self.data = self.orchestrator.data_fetcher.fetch_data(self.symbol, self.period, frequency=frequency)
        if self.data is not None:
            self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)
            self.law_analyzer = WyckoffLawAnalyzer(self.data, self.config, self.pattern_detector)
            self.mtf_analyzer = MultiTimeframeAnalyzer(self.data, self.pattern_detector)
            self.rs_analyzer = RelativeStrengthAnalyzer(self.data, self.symbol)

        return self.data

    @property
    def wie3_vsa_analyzer(self):
        """Backward-compatible accessor for report VSA summary extraction."""
        return self._wie3_service.vsa_analyzer

    def _resolve_wie3_index_df(self) -> Optional[pd.DataFrame]:
        auto_idx = self._get_cached_index_analyzer()
        if auto_idx is not None and hasattr(auto_idx, 'data') and auto_idx.data is not None:
            return auto_idx.data
        return None

    def analyze_wie3_mvp(self, index_df: pd.DataFrame = None) -> Optional['MarketState']:
        """
        执行 WIE 3.0 MVP 微观结构分析

        Args:
            index_df: 大盘数据 (用于相对强度分析),可选

        Returns:
            MarketState: 最新的市场状态对象
        """
        if self.data is None or self.data.empty:
            logger.warning("[WIE 3.0 MVP] 数据未就绪,跳过微观结构分析")
            return None

        try:
            result = self._wie3_service.analyze(
                self.data,
                index_df=index_df,
                resolve_index_df=self._resolve_wie3_index_df,
            )
            self.wie3_last_result = result
            self.wie3_market_state = result.market_state if result else None
            return self.wie3_market_state
        except (DataError, CalculationError) as e:
            logger.error(f"[WIE 3.0 MVP] 微观结构分析失败: {e}", exc_info=True)
            if not self.config.silent_fail:
                raise
            return None
        except Exception as e:
            logger.error(f"[WIE 3.0 MVP] 未知异常: {e}", exc_info=True)
            if not self.config.silent_fail:
                raise CalculationError("WIE3_MVP", str(e)) from e
            return None

    def get_wie3_summary(self) -> Dict[str, Any]:
        """
        获取 WIE 3.0 MVP 分析摘要

        Returns:
            包含所有模块摘要的字典
        """
        if self.wie3_market_state is None:
            return {}

        return {
            'market_state': self.wie3_market_state.to_dict() if self.wie3_market_state else None,
            'timestamp': str(self.data.index[-1]) if self.data is not None else None,
            'symbol': self.symbol,
        }

    def get_intraday_data(self, frequency: str = "60m") -> pd.DataFrame:
        """获取日内数据（不更新主数据状态）"""
        _, data = self.orchestrator.data_fetcher.fetch_data(self.symbol, "1mo", frequency=frequency)
        return data

    def generate_report(self) -> str:
        """生成文本报告"""
        return WyckoffReportGenerator(self).generate_report()

    def generate_json(self) -> str:
        """生成 JSON 报告"""
        return WyckoffReportGenerator(self).generate_json()

    def generate_phase_json(self) -> str:
        """
        原子化工具：仅返回威科夫阶段和置信度 (Token 高效版)

        跳过 RS分析、多时间框架、市场情绪、交易计划生成等重型步骤。
        适用于用户仅询问"当前处于什么阶段"时的轻量响应。

        Returns:
            JSON string: { symbol, phase, phase_confidence, sequence_score,
                          current_price, key_events_summary, phase_advice,
                          background_regime, background_entropy }
        """
        if not self.pattern_detector:
            self.fetch_data()

        try:
            phase_res = self.identify_phase()
            phase_str = SignalExtractor.get_effective_phase(phase_res)
            confidence  = phase_res.get('confidence', 0.0)

            # 序列评分
            seq = phase_res.get('sequence_score', {})
            seq_completeness = seq.get('completeness', 0.0) if isinstance(seq, dict) else 0.0

            # 关键事件摘要（轻量版）— 与主链 events_detected 同源
            events_summary = {}
            try:
                events = get_events_from_phase(phase_res)
                tr = SignalExtractor.get_event_dict(events, 'trading_range')
                events_summary['trading_range'] = {
                    'high': tr.get('high'),
                    'low': tr.get('low'),
                    'duration_days': tr.get('duration_days') or tr.get('consolidation_duration_days'),
                }
                events_summary['sos_detected'] = SignalExtractor._detected(
                    SignalExtractor.get_event(events, 'sos')
                )
                events_summary['sow_detected'] = SignalExtractor._detected(
                    SignalExtractor.get_event(events, 'sow')
                )
                events_summary['spring_detected'] = SignalExtractor._detected(
                    SignalExtractor.get_event(events, 'spring')
                )
                events_summary['joc_detected'] = SignalExtractor._detected(
                    SignalExtractor.get_event(events, 'joc')
                )
            except Exception:
                pass

            # 阶段挂钩建议（孟氏 checklist 对齐）
            phase_upper = phase_str.upper()
            joc_det = events_summary.get('joc_detected', False)
            spring_det = events_summary.get('spring_detected', False)
            if 'PHASE_A' in phase_upper or 'PHASE_B' in phase_upper or \
               'PHASE A' in phase_upper or 'PHASE B' in phase_upper:
                phase_advice = "Observation / Very light position try-out only (Phase A/B)"
            elif 'PHASE_C' in phase_upper or 'PHASE C' in phase_upper:
                if spring_det and not joc_det:
                    phase_advice = "Wait for JOC breakout or LPS retest (Phase C — Spring only)"
                else:
                    phase_advice = "Observation — await Spring/JOC checklist (Phase C)"
            elif 'PHASE_D' in phase_upper or 'PHASE_E' in phase_upper or \
                 'PHASE D' in phase_upper or 'PHASE E' in phase_upper:
                phase_advice = "Hold / Add on LPS after JOC (Phase D/E)" if joc_det else \
                    "Hold / Add to position (Phase D/E)"
            else:
                phase_advice = "Assess full analysis for specific advice"

            current_price = float(self.data['Close'].iloc[-1]) if self.data is not None else None

            # 融入 WIE 3.0 MVP 微观结构背景 (Microstructure Context)
            bg_regime = "Unknown"
            bg_entropy = 0.0
            try:
                market_idx_analyzer = getattr(self, '_get_cached_index_analyzer', lambda: None)()
                index_df = market_idx_analyzer.data if market_idx_analyzer else None
                wie3_state = self.analyze_wie3_mvp(index_df=index_df)
                if wie3_state:
                    bg_regime = wie3_state.regime
                    bg_entropy = round(float(wie3_state.state_entropy), 4)
            except (DataError, CalculationError):
                logger.warning("[WIE 3.0 MVP] 微观结构分析辅助失败 (数据/计算错误)")
            except Exception as e:
                logger.warning(f"[WIE 3.0 MVP] 微观结构分析辅助失败: {e}")

            import json as _json
            return _json.dumps({
                'symbol': self.symbol,
                'phase': phase_str,
                'phase_confidence': round(float(confidence), 3),
                'sequence_completeness': round(float(seq_completeness), 3),
                'current_price': current_price,
                'key_events_summary': events_summary,
                'phase_advice': phase_advice,
                'background_regime': bg_regime,
                'background_entropy': bg_entropy,
            }, ensure_ascii=False, indent=2)

        except (DataError, CalculationError, PatternNotFoundError) as e:
            import json as _json
            return _json.dumps({'error': str(e), 'symbol': self.symbol, 'error_type': type(e).__name__}, ensure_ascii=False)
        except Exception as e:
            import json as _json
            logger.exception(f"generate_phase_json 未知异常: {e}")
            if not self.config.silent_fail:
                raise
            return _json.dumps({'error': f"Unexpected: {e}", 'symbol': self.symbol}, ensure_ascii=False)

    def generate_levels_json(self) -> str:
        """
        原子化工具：仅返回关键价格位 (Token 高效版)

        跳过阶段评分、RS分析、多时间框架、历史表现等重型步骤。
        适用于用户询问"支撑/阻力/止损/目标位"时的轻量响应。

        Returns:
            JSON string: { symbol, current_price, trading_range,
                          stop_loss, targets, key_confirmation_level }
        """
        if not self.pattern_detector:
            self.fetch_data()

        try:
            import json as _json
            if self.data is None or self.data.empty or self.pattern_detector is None:
                return _json.dumps({'error': 'No data or detector available', 'symbol': self.symbol})
            from .core.trading_plan_generator import TradingPlanGenerator
            
            current_price = float(self.data['Close'].iloc[-1])
            atr = float(self.data['ATR'].iloc[-1]) if 'ATR' in self.data.columns else \
                  float((self.data['High'] - self.data['Low']).rolling(14).mean().iloc[-1])

            # 1. 主链事件（TR / SOS 与 identify_phase 同源）
            phase_res = self.identify_phase()
            phase_str = SignalExtractor.get_effective_phase(phase_res)
            events = get_events_from_phase(phase_res)
            tr = SignalExtractor.get_event_dict(events, 'trading_range')
            tr_high = tr.get('high', current_price * 1.1)
            tr_low = tr.get('low', current_price * 0.9)
            is_bullish = "Accumulation" in phase_str or "Markup" in phase_str
            
            plan_gen = TradingPlanGenerator(self.data, self.pattern_detector)
            # 获取解析后的代码信息以确定市场
            from .core.symbol_resolver import SymbolResolver
            symbol_info = SymbolResolver().resolve(self.symbol)
            
            _, stop_loss, targets = plan_gen._calculate_levels(
                current_price, atr, tr_high, tr_low, is_bullish
            )

            # 派发初期（Phase A/B）强制拦截过滤
            is_dist = 'DISTRIBUTION' in phase_str.upper() or '派发' in phase_str
            is_early_phase = any(x in phase_str.upper() for x in ['PHASE A', 'PHASE B', 'PHASE_A', 'PHASE_B', 'PHASE A/B']) or \
                             any(x in phase_str for x in ['阶段A', '阶段B', '阶段 A', '阶段 B', '阶段A/B'])
            is_dist_early = is_dist and is_early_phase

            if is_dist_early:
                stop_loss = {
                    "conservative": {
                        "value": 0.0,
                        "derivation": "无",
                        "note": "派发初期（Phase A/B）不提供做空建议，以防被轧空"
                    },
                    "aggressive": {
                        "value": 0.0,
                        "derivation": "无",
                        "note": "派发初期（Phase A/B）不提供做空建议，以防被轧空"
                    },
                    "atr_dynamic_stop": {
                        "value": 0.0,
                        "derivation": "无",
                        "note": "派发初期（Phase A/B）不提供做空建议，以防被轧空"
                    }
                }
                targets = {
                    "target_1": {
                        "value": 0.0,
                        "derivation": "无",
                        "note": "派发初期（Phase A/B）不提供做空目标"
                    },
                    "target_2": {
                        "value": 0.0,
                        "derivation": "无",
                        "note": "派发初期（Phase A/B）不提供做空目标"
                    }
                }

            # 3. SOS 关键确认位（主链 events_detected）
            key_level = None
            try:
                sos = SignalExtractor.get_event_dict(events, 'sos')
                if sos.get('detected'):
                    bt_raw = sos.get('breakthrough_level') or \
                             SignalExtractor._get(SignalExtractor._latest(sos), 'breakthrough_level')
                    if bt_raw:
                        key_level = bt_raw if isinstance(bt_raw, dict) else {
                            'value': float(bt_raw),
                            'derivation': 'events_detected.sos',
                            'note': '前期交易区间上沿阻力位'
                        }
            except (DataError, CalculationError):
                logger.warning("SOS关键确认位获取失败 (数据/计算错误)")
            except Exception:
                pass

            return _json.dumps({
                'symbol': self.symbol,
                'current_price': round(current_price, 2),
                'trading_range': {
                    'high': round(tr_high, 2),
                    'low': round(tr_low, 2),
                    'range_pct': round((tr_high - tr_low) / tr_low * 100, 1)
                },
                'stop_loss': stop_loss,
                'targets': targets,
                'key_confirmation_level': key_level,
                'atr': round(atr, 3),
            }, ensure_ascii=False, indent=2)

        except (DataError, CalculationError, PatternNotFoundError) as e:
            import json as _json
            return _json.dumps({'error': str(e), 'symbol': self.symbol, 'error_type': type(e).__name__}, ensure_ascii=False)
        except Exception as e:
            import json as _json
            logger.exception(f"generate_levels_json 未知异常: {e}")
            if not self.config.silent_fail:
                raise
            return _json.dumps({'error': f"Unexpected: {e}", 'symbol': self.symbol}, ensure_ascii=False)

    def generate_conflict_json(self) -> str:
        """
        原子化工具：仅返回 SOS-SOW 矛盾分析 (Token 高效版)
        
        适用于用户询问"这是震仓还是诱多？"或"信号矛盾如何解读？"时的轻量响应。
        
        Returns:
            JSON string: { symbol, has_conflict, interpretation, confidence,
                          reasons, confirmation_criteria, breakdown_level }
        """
        if not self.pattern_detector:
            self.fetch_data()
            
        try:
            import json as _json

            phase_res = self.identify_phase()
            events = get_events_from_phase(phase_res)
            sos = SignalExtractor.get_event_dict(events, 'sos')
            sow = SignalExtractor.get_event_dict(events, 'sow')
            tr = SignalExtractor.get_event_dict(events, 'trading_range')
            current_price = float(self.data['Close'].iloc[-1])
            
            # 执行矛盾分析
            conflict_res = SOSSOWAnalyzer.analyze_sos_sow_conflict(
                sos, sow, current_price, tr
            )
            
            # 包装结果
            res = {
                'symbol': self.symbol,
                **conflict_res
            }
            
            return _json.dumps(res, ensure_ascii=False, indent=2)
            
        except (DataError, CalculationError, PatternNotFoundError) as e:
            import json as _json
            return _json.dumps({'error': str(e), 'symbol': self.symbol, 'error_type': type(e).__name__}, ensure_ascii=False)
        except Exception as e:
            import json as _json
            logger.exception(f"generate_conflict_json 未知异常: {e}")
            if not self.config.silent_fail:
                raise
            return _json.dumps({'error': f"Unexpected: {e}", 'symbol': self.symbol}, ensure_ascii=False)

    # ----------------------------------------------------------
    # 代理旧方法 (为了兼容性)
    # ----------------------------------------------------------
    def identify_phase(self):
        """识别威科夫阶段"""
        return self.pattern_detector.identify_phase()

    def detect_trading_range(self):
        """检测交易区间"""
        return self.pattern_detector.detect_trading_range()

    def _get_baseline_index_symbol(self) -> Optional[str]:
        """获取基准指数代码；当前标的为指数时返回 None。"""
        from .core.symbol_resolver import SymbolResolver
        return SymbolResolver().resolve_benchmark_index(self.symbol)

    def _analyze_market_environment(self) -> Dict:
        """
        分析市场环境 (v2.6.0 专家级实现)
        
        基于指数的均线排列、成交量能量 (EVR) 判断大盘环境。
        """
        try:
            # 获取基准指数代码
            index_symbol = self._get_baseline_index_symbol()
            
            # 获取指数数据
            idx_analyzer = self._get_cached_index_analyzer()
            if not idx_analyzer or idx_analyzer.data is None:
                return {
                    "environment": MarketEnvironment.UNKNOWN,
                    "reason": "无法获取大盘指数数据",
                    "index_symbol": index_symbol
                }
            
            # 使用专家级分析器
            context_analyzer = MarketContextAnalyzer(idx_analyzer.data, index_symbol)
            return context_analyzer.analyze()
            
        except (DataError, CalculationError) as e:
            logger.warning(f"专家级市场环境分析失败 (数据/计算错误): {e}")
            return {
                "environment": MarketEnvironment.UNKNOWN,
                "reason": f"数据异常: {str(e)}",
                "index_symbol": self._get_baseline_index_symbol()
            }
        except Exception as e:
            logger.warning(f"专家级市场环境分析失败: {e}")
            return {
                "environment": MarketEnvironment.UNKNOWN,
                "reason": f"分析异常: {str(e)}",
                "index_symbol": self._get_baseline_index_symbol()
            }


    def analyze_timeframe_resonance(self) -> Dict:
        """分析多时间框架共振（兼容旧接口）"""
        if not self.mtf_analyzer:
            return {
                'resonance_level': 'unknown',
                'implication': 'data_not_ready',
                'weekly_trend': 'unknown',
                'monthly_trend': 'unknown',
            }

        result = self.mtf_analyzer.analyze_resonance()
        level = result.get('resonance_level', 'no_resonance')
        implication_map = {
            'strong_resonance': 'high_conviction',
            'moderate_resonance': 'confirm_with_risk_control',
            'weak_resonance': 'watch_for_confirmation',
            'no_resonance': 'mixed_signals',
        }
        result['implication'] = implication_map.get(level, 'mixed_signals')
        return result

    def identify_phase_multi_timeframe(self) -> Dict:
        """识别阶段并附加多时间框架趋势（兼容旧接口）"""
        if self.pattern_detector:
            try:
                phase_result = self.identify_phase()
            except (DataError, CalculationError, PatternNotFoundError) as e:
                logger.warning(f'Phase识别失败 (数据/计算错误): {e}')
                phase_result = {'phase': 'unknown'}
            except Exception as e:
                logger.warning(f'Failed to identify phase in multi-timeframe view, fallback to unknown: {e}')
                phase_result = {'phase': 'unknown'}
        else:
            phase_result = {'phase': 'unknown'}
        weekly = self.mtf_analyzer.get_weekly_trend() if self.mtf_analyzer else 'unknown'
        monthly = self.mtf_analyzer.get_monthly_trend() if self.mtf_analyzer else 'unknown'

        merged = dict(phase_result)
        merged['weekly_trend'] = weekly
        merged['monthly_trend'] = monthly
        return merged

    def _is_a_stock(self, symbol: str) -> bool:
        """判断是否为 A 股 (P2 辅助接口)"""
        from .core.symbol_resolver import SymbolResolver, MarketType
        info = SymbolResolver().resolve(symbol)
        return info.market == MarketType.A_SHARE

    def identify_phase_with_rs(self) -> Dict:
        """识别阶段并附加相对强度分析 (P2 增强接口)"""
        # 1. 获取多时间框架阶段信息
        result = self.identify_phase_multi_timeframe()

        # 2. 获取基准指数分析器
        idx_analyzer = self._get_cached_index_analyzer()
        if idx_analyzer and idx_analyzer.data is not None:
            # 3. 计算相对强度
            rs_data = self.rs_analyzer.calculate_rs(idx_analyzer.data)
            result['relative_strength'] = rs_data
        else:
            result['relative_strength'] = {'rs_trend': 'unknown', 'rs_value': None}

        return result

    def _get_cached_index_analyzer(self) -> Optional[Union['WyckoffAnalyzer', '_IndexDataWrapper']]:
        """获取并缓存基准指数分析器"""
        if self._index_analyzer_cache is not None:
            return self._index_analyzer_cache

        index_symbol = self._get_baseline_index_symbol()
        if index_symbol is None:
            logger.debug(f"当前标的 {self.symbol} 为指数，跳过基准指数分析")
            return None
        
        try:
            # 优先使用共享指数缓存 (P1.1)
            if self.index_data_cache is not None:
                index_df = self.index_data_cache.get_index_data(index_symbol, self.period)
                if index_df is not None:
                    logger.debug(f"使用共享指数缓存: {index_symbol}")
                    # 创建一个轻量级包装器，只提供 .data 属性
                    self._index_analyzer_cache = _IndexDataWrapper(index_df)
                    return self._index_analyzer_cache

            # 回退：创建完整的指数分析器
            idx_analyzer = WyckoffAnalyzer(index_symbol, self.period, self.config, self.cache_service)
            idx_analyzer.fetch_data()
            self._index_analyzer_cache = idx_analyzer
            return idx_analyzer
        except (DataError, CalculationError) as e:
            logger.warning(f"指数分析器初始化失败 {index_symbol}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize index analyzer for {index_symbol}: {e}")
            return None

    def calculate_cause_effect(self) -> Dict:
        if not self.pattern_detector:
            return {}

        if not self.law_analyzer and self.data is not None:
            self.law_analyzer = WyckoffLawAnalyzer(self.data, self.config, self.pattern_detector)

        if not self.law_analyzer:
            return {}

        try:
            res = self.law_analyzer.analyze_cause_effect_law_enhanced()
            if not res:
                return {}

            basic = res.get('basic_analysis', {}).copy()
            enhanced = res.get('enhanced_analysis', {})

            # 对齐 cause_bars（因原本 facade.py 期望返回 cause_bars）
            if 'consolidation_duration_days' in basic and 'cause_bars' not in basic:
                basic['cause_bars'] = basic['consolidation_duration_days']
            if 'horizontal_count' in basic and 'cause_bars' not in basic:
                basic['cause_bars'] = basic['horizontal_count']

            # 把一些 facade.py 以前包含而 basic 里面可能叫法不一样的字段对齐
            if isinstance(enhanced, dict):
                # 扁平合入 enhanced 的关键字段，以完美向下兼容
                for k, v in enhanced.items():
                    if k not in basic:
                        basic[k] = v

            return basic
        except Exception as e:
            logger.warning(f"calculate_cause_effect failed: {e}")
            return {}


def batch_scan(symbols: List[str], period: str = "1y",
               scan_mode: str = "quick", config: WyckoffConfig = None,
               **kwargs) -> Dict[str, Any]:
    """
    批量扫描股票（便捷函数）

    Args:
        symbols: 股票代码列表，如 ["AAPL", "MSFT", "GOOGL"]
        period: 数据周期，默认 "1y"
        scan_mode: 扫描模式
            - "quick": 快速扫描（并行，返回摘要）✅ 当前支持
            - "deep"/"accumulation"/"distribution"/"lps"/"lpsy": 深度筛选（待适配新版接口）
        config: WyckoffConfig配置
        **kwargs: 额外参数
            - max_workers: 最大并行线程数（quick模式，默认自动检测）
            - show_progress: 是否显示进度（默认True）

    Returns:
        扫描结果字典:
        {
            "results": List[Dict],      # 扫描结果列表
            "summary": Dict,             # 统计摘要
            "top_picks": List[Dict],     # 顶级机会（TOP 10）
            "failed": List[str],         # 失败的股票
            "scan_mode": str             # 扫描模式
        }

    Examples:
        >>> # 快速扫描多只股票
        >>> result = batch_scan(["AAPL", "MSFT", "GOOGL"])
        >>> print(f"扫描完成: {result['summary']['total_scanned']} 只股票")
        >>> print(f"发现信号: {result['summary']['signal_count']} 个")
        >>>
        >>> # 查看顶级机会
        >>> for pick in result['top_picks']:
        ...     print(f"{pick['symbol']}: {pick['phase']} (评分: {pick.get('weighted_score', pick.get('strength'))})")

    Note:
        - 需要安装 tqdm 库以显示进度条
        - 并行扫描可显著提升效率（建议 4-8 线程）
        - 不同市场可能需要不同的数据周期（A股建议 2y）
    """
    from .services.screener_service import ScreenerService

    screener = ScreenerService(config)
    return screener.batch_scan(symbols, period, scan_mode, **kwargs)
