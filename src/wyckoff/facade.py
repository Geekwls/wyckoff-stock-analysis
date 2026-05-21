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
from typing import Dict, List, Tuple, Optional, Any, TYPE_CHECKING
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
from .core.point_and_figure import PointAndFigureCalculator, calculate_cause_effect_from_pnf
from .core.sos_sow_analyzer import SOSSOWAnalyzer
from .core.market_context_analyzer import MarketContextAnalyzer
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

        # 核心编排器
        self.orchestrator = WyckoffOrchestrator(self.config)

        # 运行时数据与探测器 (fetch_data 后初始化)
        self.data = None
        self.pattern_detector = None
        self.law_analyzer = None
        self.mtf_analyzer = None
        self.rs_analyzer = None

        # WIE 3.0 MVP 微观结构引擎 (fetch_data 后初始化)
        self.wie3_vsa_analyzer = None
        self.wie3_efficiency_analyzer = None
        self.wie3_aps_analyzer = None
        self.wie3_regime_tracker = None
        self.wie3_rs_engine = None
        self.wie3_state_engine = None
        self.wie3_market_state = None  # 存储最新的市场状态

        self._index_analyzer_cache: Optional['WyckoffAnalyzer'] = None

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
        self.symbol, self.data = self.orchestrator.data_fetcher.fetch_data(self.symbol, self.period, frequency=frequency)
        if self.data is not None:
            self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)
            self.law_analyzer = WyckoffLawAnalyzer(self.data, self.config, self.pattern_detector)
            self.mtf_analyzer = MultiTimeframeAnalyzer(self.data, self.pattern_detector)
            self.rs_analyzer = RelativeStrengthAnalyzer(self.data, self.symbol)

        return self.data

    def _init_wie3_mvp_engines(self):
        """初始化 WIE 3.0 MVP 微观结构分析引擎"""
        try:
            from .core.vsa_analyzer import VSAAnalyzer
            from .core.expansion_efficiency import ExpansionEfficiencyEngine
            from .core.aps_engine import APSEngine
            from .core.regime_tracker import RegimeTracker
            from .core.relative_strength import RelativeStrengthEngine
            from .core.state_engine import EventDrivenStateEngine

            # 1. VSA 微观量价解构
            self.wie3_vsa_analyzer = VSAAnalyzer()

            # 2. 推动效率引擎 (修补奇点)
            self.wie3_efficiency_analyzer = ExpansionEfficiencyEngine()

            # 3. APS 吸收动力学引擎
            self.wie3_aps_analyzer = APSEngine()

            # 4. Regime 追踪与 VPOC 引擎
            self.wie3_regime_tracker = RegimeTracker()

            # 5. 相对强度引擎 (需要大盘数据)
            self.wie3_rs_engine = RelativeStrengthEngine()

            # 6. 事件驱动状态引擎
            self.wie3_state_engine = EventDrivenStateEngine()

            logger.info("[WIE 3.0 MVP] 微观结构引擎初始化完成")

        except Exception as e:
            logger.error(f"[WIE 3.0 MVP] 引擎初始化失败: {e}")
            # 不影响主流程,继续运行
            self.wie3_vsa_analyzer = None
            self.wie3_efficiency_analyzer = None
            self.wie3_aps_analyzer = None
            self.wie3_regime_tracker = None
            self.wie3_rs_engine = None
            self.wie3_state_engine = None

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

        # 惰性加载 (Lazy Initialization): 仅在实际调用时初始化引擎，节约基础扫描时的资源
        if not self.wie3_vsa_analyzer:
            self._init_wie3_mvp_engines()

        if not self.wie3_vsa_analyzer:
            logger.warning("[WIE 3.0 MVP] 引擎初始化失败,跳过微观结构分析")
            return None

        try:
            # 1. VSA 微观量价解构
            df_vsa = self.wie3_vsa_analyzer.analyze(self.data)
            logger.debug("[WIE 3.0 MVP] VSA 分析完成")

            # 2. 推动效率分析
            df_eff = self.wie3_efficiency_analyzer.analyze(df_vsa)
            logger.debug("[WIE 3.0 MVP] 推动效率分析完成")

            # 3. APS 吸收动力学分析
            df_aps = self.wie3_aps_analyzer.analyze(df_eff)
            logger.debug("[WIE 3.0 MVP] APS 吸收动力学分析完成")

            # 4. Regime 追踪与 VPOC 计算
            df_regime = self.wie3_regime_tracker.track(df_vsa, df_eff, df_aps)
            logger.debug("[WIE 3.0 MVP] Regime 追踪与 VPOC 计算完成")

            # 5. 相对强度分析 (如果提供了大盘数据)
            has_index_data = index_df is not None and not index_df.empty
            if has_index_data:
                df_rs = self.wie3_rs_engine.analyze(df_regime, index_df)
                logger.debug("[WIE 3.0 MVP] 相对强度分析完成")
            else:
                # ─────────────────────────────────────────────────────────────
                # Wave 4 偏差三修正：RS 静默旁路 → 主动警告 + 后台自适应拉取
                # 原来：无大盘数据时静默将 RS 置为 1.0，等于"雷达关闭但显示无敌机"
                # 修正：先尝试自适应拉取对应市场的默认指数，再明确警告用户
                # ─────────────────────────────────────────────────────────────
                logger.warning(
                    "[WIE 3.0 MVP] [Wave4-偏差三] 大盘基准数据缺失！"
                    "RS 引擎正在尝试后台自适应拉取对应市场默认指数..."
                )
                # 尝试通过 _get_cached_index_analyzer 自适应拉取
                auto_index_df = None
                try:
                    auto_idx = self._get_cached_index_analyzer()
                    if auto_idx is not None and hasattr(auto_idx, 'data') and auto_idx.data is not None:
                        auto_index_df = auto_idx.data
                        logger.info(
                            f"[WIE 3.0 MVP] [Wave4] RS 引擎：已自适应拉取大盘数据，"
                            f"行数={len(auto_index_df)}，RS 分析正常激活。"
                        )
                except Exception as _auto_e:
                    logger.warning(f"[WIE 3.0 MVP] [Wave4] RS 自适应拉取失败: {_auto_e}")

                if auto_index_df is not None and not auto_index_df.empty:
                    df_rs = self.wie3_rs_engine.analyze(df_regime, auto_index_df)
                    df_rs['rs_bypass_warning'] = False
                    logger.debug("[WIE 3.0 MVP] RS 分析（自适应大盘数据）完成")
                else:
                    # 自适应拉取仍然失败，进入旁路并设置显式警告标志
                    logger.warning(
                        "[WIE 3.0 MVP] [Wave4-偏差三] RS 引擎：大盘数据自适应拉取失败！"
                        "相对强度分析已强制旁路，liquidity_retention 将置为中性 1.0。"
                        "请检查网络连接或手动传入 index_df。"
                    )
                    df_rs = df_regime.copy()  # 修复 SettingWithCopyWarning 隐患
                    # 添加默认的相对强度字段（中性兜底）
                    if 'liquidity_retention' not in df_rs.columns:
                        df_rs['liquidity_retention'] = 1.0
                    if 'hidden_strength' not in df_rs.columns:
                        df_rs['hidden_strength'] = False
                    if 'hidden_weakness' not in df_rs.columns:
                        df_rs['hidden_weakness'] = False
                    # 添加默认字段以供 extract_summary 使用
                    df_rs['idx_log_return'] = 0.0
                    df_rs['asset_log_return'] = 0.0
                    # 设置旁路警告标志，供 report_generator 渲染 [!WARNING]
                    df_rs['rs_bypass_warning'] = True


            # 6. 状态机推演 (P1.2: 向量化批量更新)
            # 必须重置状态机，确保每次 analyze 都是从先验开始，而不是从上次的脏状态开始
            from .core.state_engine import EventDrivenStateEngine
            self.wie3_state_engine = EventDrivenStateEngine()

            n_rows = len(df_rs)
            
            # 准备向量化输入数组
            closes = self.data['Close'].values if 'Close' in self.data.columns else df_rs['close'].values
            aps_vals = df_aps['aps'].values if 'aps' in df_aps.columns else np.zeros(n_rows)
            cds_vals = df_regime['cds'].values if 'cds' in df_regime.columns else np.zeros(n_rows)
            lcs_vals = df_regime['lcs'].values if 'lcs' in df_regime.columns else np.zeros(n_rows)
            vpocs = df_regime['vpoc_price'].values if 'vpoc_price' in df_regime.columns else np.zeros(n_rows)
            exp_effs = df_vsa['expansion_efficiency'].values if 'expansion_efficiency' in df_vsa.columns else np.zeros(n_rows)
            clvs = df_vsa['clv'].values if 'clv' in df_vsa.columns else np.zeros(n_rows)
            retentions = df_rs['liquidity_retention'].values if 'liquidity_retention' in df_rs.columns else np.ones(n_rows)
            hs = df_rs['hidden_strength'].values if 'hidden_strength' in df_rs.columns else np.zeros(n_rows, dtype=bool)
            hw = df_rs['hidden_weakness'].values if 'hidden_weakness' in df_rs.columns else np.zeros(n_rows, dtype=bool)
            
            # 处理 event_flag
            if 'event_flag' in df_regime.columns:
                event_flags = df_regime['event_flag'].astype(str).tolist()
            else:
                event_flags = ['NORMAL'] * n_rows
            
            # 处理 timestamps
            if hasattr(df_rs.index, 'strftime'):
                timestamps = [str(idx) for idx in df_rs.index]
            else:
                timestamps = [str(i) for i in range(n_rows)]
            
            # 执行向量化批量更新
            all_states = self.wie3_state_engine.batch_update(
                closes, aps_vals, cds_vals, lcs_vals, vpocs,
                exp_effs, clvs, retentions, hs, hw, event_flags, timestamps
            )
            
            # 取最后一个状态作为最终结果
            if all_states:
                self.wie3_market_state = all_states[-1]

            logger.info(
                f"[WIE 3.0 MVP] 状态机序列推演完成: {self.wie3_market_state.regime} "
                f"(APS={self.wie3_market_state.aps:.2f}, CDS={self.wie3_market_state.cds}, "
                f"VPOC={self.wie3_market_state.vpoc_price:.2f}, Entropy={self.wie3_market_state.state_entropy:.4f})"
            )

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
            phase_str   = phase_res.get('phase', 'Unknown')
            confidence  = phase_res.get('confidence', 0.0)

            # 序列评分
            seq = phase_res.get('sequence_score', {})
            seq_completeness = seq.get('completeness', 0.0) if isinstance(seq, dict) else 0.0

            # 关键事件摘要（轻量版）
            events_summary = {}
            try:
                tr = self.pattern_detector.detect_trading_range()
                events_summary['trading_range'] = {
                    'high': tr.get('high'), 'low': tr.get('low'),
                    'duration_days': tr.get('duration_days')
                }
                sos = self.pattern_detector.sw_detector.detect_sos()
                events_summary['sos_detected'] = sos.get('detected', False)
                sow = self.pattern_detector.sw_detector.detect_sow()
                events_summary['sow_detected'] = sow.get('detected', False)
                spring = self.pattern_detector.reversal_detector.detect_spring()
                events_summary['spring_detected'] = spring.get('detected', False)
            except Exception:
                pass

            # 阶段挂钩建议（按 SKILL.md 规则）
            phase_upper = phase_str.upper()
            if 'PHASE_A' in phase_upper or 'PHASE_B' in phase_upper or \
               'PHASE A' in phase_upper or 'PHASE B' in phase_upper:
                phase_advice = "Observation / Very light position try-out only (Phase A/B)"
            elif 'PHASE_C' in phase_upper or 'PHASE C' in phase_upper:
                phase_advice = "Batch entry / Position building (Phase C)"
            elif 'PHASE_D' in phase_upper or 'PHASE_E' in phase_upper or \
                 'PHASE D' in phase_upper or 'PHASE E' in phase_upper:
                phase_advice = "Hold / Add to position (Phase D/E)"
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
            from .core.trading_plan_generator import TradingPlanGenerator
            
            current_price = float(self.data['Close'].iloc[-1])
            atr = float(self.data['ATR'].iloc[-1]) if 'ATR' in self.data.columns else \
                  float((self.data['High'] - self.data['Low']).rolling(14).mean().iloc[-1])

            # 1. 获取交易区间
            tr = self.pattern_detector.detect_trading_range()
            tr_high = tr.get('high', current_price * 1.1)
            tr_low  = tr.get('low',  current_price * 0.9)

            # 2. 复用 TradingPlanGenerator 的计算逻辑
            phase_res = self.identify_phase()
            phase_str = phase_res.get('phase', 'Unknown')
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

            # 3. SOS-SOW 关键确认位
            key_level = None
            try:
                sos = self.pattern_detector.sw_detector.detect_sos()
                if sos.get('detected'):
                    bt_raw = sos.get('latest', sos).get('breakthrough_level') or \
                             sos.get('breakthrough_level')
                    if bt_raw:
                        key_level = bt_raw if isinstance(bt_raw, dict) else {
                            'value': float(bt_raw),
                            'derivation': 'max_high_in_60d_range',
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
            
            sos = self.pattern_detector.sw_detector.detect_sos()
            sow = self.pattern_detector.sw_detector.detect_sow()
            current_price = float(self.data['Close'].iloc[-1])
            tr = self.pattern_detector.detect_trading_range()
            
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
        """
        获取基准指数代码
        
        A股市场分类：
        - 上证主板：600/601/603/605开头 → sh.000001 (上证综指)
        - 科创板：688开头 → sh.000688 (科创50) 或 sh.000001
        - 深证主板：000/001/002/003开头 → sz.399001 (深证成指)
        - 创业板：300/301开头 → sz.399006 (创业板指)
        - 北交所：8/4开头 → bj.899050 (北证50)
        
        返回 None 如果当前标的本身就是指数（避免递归分析）
        """
        from .core.symbol_resolver import SymbolResolver, MarketType
        info = SymbolResolver().resolve(self.symbol)
        
        # 指数代码白名单 (避免递归分析)
        INDEX_SYMBOLS = {
            'sh.000001', 'sh.000300', 'sh.000688', 'sh.000016',
            'sz.399001', 'sz.399006', 'sz.399005', 'sz.399673',
            'bj.899050',
            '^HSI', '^GSPC', '^DJI', '^IXIC',  # 港股/美股指数
            'BTC-USD', 'ETH-USD',  # 加密货币基准
        }
        
        normalized = info.normalized if hasattr(info, 'normalized') else self.symbol
        if normalized in INDEX_SYMBOLS or self.symbol in INDEX_SYMBOLS:
            return None
        
        if info.market == MarketType.A_SHARE:
            code = info.normalized.split('.')[-1]
            prefix = info.normalized.split('.')[0]
            
            # 北交所：8或4开头（430/830/870等）
            if code.startswith(('8', '4')) and prefix == 'BJ':
                return "bj.899050"  # 北证50
            
            # 科创板：688/689开头
            if code.startswith(('688', '689')):
                return "sh.000688"  # 科创50
            
            # 创业板：300/301开头
            if code.startswith(('300', '301')):
                return "sz.399006"  # 创业板指
            
            # 上证主板：600/601/603/605开头
            if code.startswith('6'):
                return "sh.000001"  # 上证综指
            
            # 深证主板：000/001/002/003开头
            return "sz.399001"  # 深证成指
        
        if info.market == MarketType.CRYPTO:
            return "BTC-USD"
            
        if info.market == MarketType.HK_STOCK:
            return "^HSI"  # 恒生指数
            
        # 美股及其他默认
        return "SPY"

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

    def _get_cached_index_analyzer(self) -> Optional['WyckoffAnalyzer']:
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

        tr = self.pattern_detector.detect_trading_range()
        if not tr:
            return {}

        # 区间边界失效校验：若 tr_low > 0 且最近 60 个交易日内最低价跌破过 tr_low，但当前收盘价已重新站回 tr_low * 1.03 以上
        tr_low = tr.get('low', 0.0)
        tr_high = tr.get('high', 0.0)
        recent_data = self.data.tail(60) if self.data is not None else pd.DataFrame()
        recent_low = recent_data['Low'].min() if not recent_data.empty else 0.0
        current_price = self.data['Close'].iloc[-1] if self.data is not None and not self.data.empty else 0.0

        if tr_low > 0 and recent_low < tr_low and current_price >= tr_low * 1.03:
            return {
                'method': 'invalidated_tr',
                'cause_bars': 0,
                'volatility_contraction': 0.0,
                'contraction_factor': 0.0,
                'description': "🚨 原交易区间参考性已下降：价格曾跌破原支撑位且已大幅收回，表明市场已找到新的需求抵抗，当前正在重建结构。根据威科夫原则，原区间已失效，必须暂停目标测算，等待新的有效 TR 形成。",
                'targets': {'target_1': 0.0, 'target_2': 0.0, 'target_3': 0.0},
                'theory': "威科夫区间失效原则",
                'tr_low': tr_low,
                'tr_high': tr_high,
                'current_price': current_price
            }

        try:
            phase_result = self.identify_phase()
            current_phase = phase_result.get('phase', '')

            pnf_result = calculate_cause_effect_from_pnf(
                self.data, 
                box_size_pct=1.0,
                reversal_boxes=3,
                phase=current_phase,
                known_tr_high=tr.get('high'),
                known_tr_low=tr.get('low'),
            )

            if pnf_result.get('horizontal_count', 0) >= 3:
                return {
                    'method': pnf_result.get('method', 'point_and_figure'),
                    'cause_bars': pnf_result.get('horizontal_count', 0),
                    'vertical_count': pnf_result.get('vertical_count', 0),
                    'accumulation_range': pnf_result.get('accumulation_range', {}),
                    'base_effect': pnf_result.get('base_effect', 0),
                    'breakout_direction': pnf_result.get('breakout_direction', 'up'),
                    'description': pnf_result.get('description', ''),
                    'targets': pnf_result.get('targets', {}),
                    'theory': '威科夫因果法则：水平计数决定垂直目标',
                    '_pnf_method': pnf_result.get('_pnf_method', ''),
                }

            cause_bars = tr.get('consolidation_duration_days', 40)
            recent_data = self.data.tail(cause_bars)
            if len(recent_data) < 10:
                return {}

            atr_series = (recent_data['High'] - recent_data['Low']).rolling(window=5).mean()
            atr_start = atr_series.iloc[0] if len(atr_series) > 0 else 0
            atr_end = atr_series.iloc[-1] if len(atr_series) > 0 else 0
            volatility_contraction = 1 - (atr_end / atr_start) if atr_start > 0 else 0

            base_price = tr['high']
            price_range = tr['high'] - tr['low']

            # 威科夫因果法则：水平积累宽度 → 垂直目标幅度
            # 波动率收缩越大 → 积累越充分 → 突破后的爆发力越强
            # 但当无收缩时，使用基础水平计数
            if volatility_contraction > 0.1:
                # 有显著波动率收缩：收缩越多，蓄力越强
                contraction_factor = 1 + volatility_contraction * 1.5
            else:
                # 无显著收缩：使用标准水平计数法
                contraction_factor = 1.0

            time_factor = cause_bars / 30
            potential_move = price_range * contraction_factor * time_factor

            return {
                'method': 'volatility_contraction',
                'cause_bars': cause_bars,
                'volatility_contraction': round(volatility_contraction * 100, 1),
                'contraction_factor': round(contraction_factor, 2),
                'description': f"基于波动率收缩{volatility_contraction*100:.1f}%和{cause_bars}天积累，"
                              f"预计突破幅度为{potential_move/base_price*100:.1f}%",
                'targets': {
                    'target_1': round(base_price + potential_move * 0.618, 2),
                    'target_2': round(base_price + potential_move, 2),
                    'target_3': round(base_price + potential_move * 1.618, 2),
                },
                'theory': '威科夫因果法则：水平积累宽度 × 波动率收缩 → 垂直目标'
            }

        except (DataError, CalculationError) as e:
            logger.warning(f"点数图计算失败 (数据/计算错误): {e}")
            if not self.config.silent_fail:
                raise
            cause_bars = tr.get('consolidation_duration_days', 40)
            base_price = tr.get('high', 0)
            price_range = tr.get('high', 0) - tr.get('low', 0)
            potential_move = price_range * 1.0

            return {
                'method': 'fallback',
                'cause_bars': cause_bars,
                'description': f"备用估算：横盘{cause_bars}天，预计突破幅度为{potential_move/base_price*100:.1f}%",
                'targets': {
                    'target_1': round(base_price + potential_move * 0.618, 2),
                    'target_2': round(base_price + potential_move, 2),
                    'target_3': round(base_price + potential_move * 1.618, 2),
                },
                'theory': '备用估算方法'
            }


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
