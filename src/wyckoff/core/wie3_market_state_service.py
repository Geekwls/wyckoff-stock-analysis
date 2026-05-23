"""Unified WIE 3.0 microstructure pipeline shared by facade and orchestrator."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from ..config.settings import WyckoffThresholds
from ..exceptions import CalculationError, DataError

logger = logging.getLogger(__name__)

ResolveIndexFn = Callable[[], Optional[pd.DataFrame]]
CacheKey = Tuple[str, str]


@dataclass
class WIE3AnalysisResult:
    market_state: object
    df_vsa: pd.DataFrame
    rs_bypass_warning: bool = False


def _frame_fingerprint(df: Optional[pd.DataFrame]) -> str:
    if df is None or df.empty:
        return "empty"
    close_col = 'Close' if 'Close' in df.columns else ('close' if 'close' in df.columns else None)
    if close_col is None:
        return f"{len(df)}:{df.index[-1]}"
    close = df[close_col]
    return f"{len(df)}:{df.index[-1]}:{float(close.iloc[-1]):.6f}:{float(close.iloc[0]):.6f}"


class WIE3MarketStateService:
    """Run the VSA → APS → Regime → RS → state-engine stack once for all callers."""

    def __init__(self, thresholds: Optional[WyckoffThresholds] = None):
        import collections
        self.thresholds = thresholds or WyckoffThresholds()
        self.vsa_analyzer = None
        self.efficiency_analyzer = None
        self.aps_analyzer = None
        self.regime_tracker = None
        self.rs_engine = None
        self._engines_ready = False
        self._result_cache: collections.OrderedDict[CacheKey, WIE3AnalysisResult] = collections.OrderedDict()
        self._cache_max_size = 50

    def clear_cache(self) -> None:
        """Drop memoized results, e.g. after fetch_data loads fresh OHLCV."""
        self._result_cache.clear()

    def _ensure_engines(self) -> bool:
        if self._engines_ready:
            return True
        try:
            from .vsa_analyzer import VSAAnalyzer
            from .expansion_efficiency import ExpansionEfficiencyEngine
            from .aps_engine import APSEngine
            from .regime_tracker import RegimeTracker
            from .relative_strength import RelativeStrengthEngine

            self.vsa_analyzer = VSAAnalyzer()
            self.efficiency_analyzer = ExpansionEfficiencyEngine()
            self.aps_analyzer = APSEngine()
            self.regime_tracker = RegimeTracker()
            self.rs_engine = RelativeStrengthEngine()
            self._engines_ready = True
            logger.info("[WIE 3.0 MVP] 微观结构引擎初始化完成")
            return True
        except Exception as exc:
            logger.error(f"[WIE 3.0 MVP] 引擎初始化失败: {exc}")
            self.vsa_analyzer = None
            self._engines_ready = False
            return False

    def analyze(
        self,
        data: pd.DataFrame,
        *,
        index_df: Optional[pd.DataFrame] = None,
        resolve_index_df: Optional[ResolveIndexFn] = None,
    ) -> Optional[WIE3AnalysisResult]:
        if data is None or data.empty:
            logger.warning("[WIE 3.0 MVP] 数据未就绪,跳过微观结构分析")
            return None

        if not self._ensure_engines():
            logger.warning("[WIE 3.0 MVP] 引擎初始化失败,跳过微观结构分析")
            return None

        effective_index = index_df
        if (effective_index is None or effective_index.empty) and resolve_index_df is not None:
            logger.warning(
                "[WIE 3.0 MVP] [Wave4-偏差三] 大盘基准数据缺失！"
                "RS 引擎正在尝试后台自适应拉取对应市场默认指数..."
            )
            try:
                effective_index = resolve_index_df()
                if effective_index is not None and not effective_index.empty:
                    logger.info(
                        f"[WIE 3.0 MVP] [Wave4] RS 引擎：已自适应拉取大盘数据，"
                        f"行数={len(effective_index)}，RS 分析正常激活。"
                    )
            except Exception as exc:
                logger.warning(f"[WIE 3.0 MVP] [Wave4] RS 自适应拉取失败: {exc}")
                effective_index = None

        cache_key = (
            _frame_fingerprint(data),
            _frame_fingerprint(effective_index),
        )
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            logger.debug("[WIE 3.0 MVP] 使用 memoized 微观结构结果")
            return cached

        try:
            result = self._compute(data, effective_index=effective_index)
            if result is not None:
                self._result_cache[cache_key] = result
                if len(self._result_cache) > self._cache_max_size:
                    self._result_cache.popitem(last=False)
            return result
        except (DataError, CalculationError):
            raise
        except Exception as exc:
            raise CalculationError("WIE3_MVP", str(exc)) from exc

    def _compute(
        self,
        data: pd.DataFrame,
        *,
        effective_index: Optional[pd.DataFrame],
    ) -> Optional[WIE3AnalysisResult]:
        df_vsa = self.vsa_analyzer.analyze(data)
        df_eff = self.efficiency_analyzer.analyze(df_vsa)
        df_aps = self.aps_analyzer.analyze(df_eff)
        df_regime = self.regime_tracker.track(df_vsa, df_eff, df_aps)

        df_rs, rs_bypass_warning = self._resolve_relative_strength(
            df_regime,
            effective_index=effective_index,
        )

        market_state = self._run_state_engine(data, df_vsa, df_aps, df_regime, df_rs)
        if market_state is None:
            return None

        logger.info(
            f"[WIE 3.0 MVP] 状态机序列推演完成: {market_state.regime} "
            f"(APS={market_state.aps:.2f}, CDS={market_state.cds}, "
            f"VPOC={market_state.vpoc_price:.2f}, Entropy={market_state.state_entropy:.4f})"
        )
        return WIE3AnalysisResult(
            market_state=market_state,
            df_vsa=df_vsa,
            rs_bypass_warning=rs_bypass_warning,
        )

    def _resolve_relative_strength(
        self,
        df_regime: pd.DataFrame,
        *,
        effective_index: Optional[pd.DataFrame],
    ) -> tuple[pd.DataFrame, bool]:
        if effective_index is not None and not effective_index.empty:
            df_rs = self.rs_engine.analyze(df_regime, effective_index)
            df_rs['rs_bypass_warning'] = False
            return df_rs, False

        logger.warning(
            "[WIE 3.0 MVP] [Wave4-偏差三] RS 引擎：大盘数据自适应拉取失败！"
            "相对强度分析已强制旁路，liquidity_retention 将置为中性 1.0。"
            "请检查网络连接或手动传入 index_df。"
        )
        df_rs = df_regime.copy()
        if 'liquidity_retention' not in df_rs.columns:
            df_rs['liquidity_retention'] = 1.0
        if 'hidden_strength' not in df_rs.columns:
            df_rs['hidden_strength'] = False
        if 'hidden_weakness' not in df_rs.columns:
            df_rs['hidden_weakness'] = False
        df_rs['idx_log_return'] = 0.0
        df_rs['asset_log_return'] = 0.0
        df_rs['rs_bypass_warning'] = True
        return df_rs, True

    def _run_state_engine(
        self,
        data: pd.DataFrame,
        df_vsa: pd.DataFrame,
        df_aps: pd.DataFrame,
        df_regime: pd.DataFrame,
        df_rs: pd.DataFrame,
    ):
        from .state_engine import EventDrivenStateEngine
        from .wie3_calibration import load_transition_matrix, resolve_transition_matrix_path

        matrix_path = resolve_transition_matrix_path(self.thresholds)
        transition_matrix = load_transition_matrix(matrix_path) if matrix_path else None
        state_engine = EventDrivenStateEngine(
            entropy_degraded_threshold=self.thresholds.STATE_ENTROPY_DEGRADED_THRESHOLD,
            transition_matrix=transition_matrix,
        )

        n_rows = len(df_rs)
        closes = data['Close'].values if 'Close' in data.columns else df_rs['close'].values
        aps_vals = df_aps['aps'].values if 'aps' in df_aps.columns else np.zeros(n_rows)
        cds_vals = df_regime['cds'].values if 'cds' in df_regime.columns else np.zeros(n_rows)
        lcs_vals = df_regime['lcs'].values if 'lcs' in df_regime.columns else np.zeros(n_rows)
        vpocs = df_regime['vpoc_price'].values if 'vpoc_price' in df_regime.columns else np.zeros(n_rows)
        exp_effs = (
            df_vsa['expansion_efficiency'].values
            if 'expansion_efficiency' in df_vsa.columns else np.zeros(n_rows)
        )
        clvs = df_vsa['clv'].values if 'clv' in df_vsa.columns else np.zeros(n_rows)
        retentions = (
            df_rs['liquidity_retention'].values
            if 'liquidity_retention' in df_rs.columns else np.ones(n_rows)
        )
        hidden_strength = (
            df_rs['hidden_strength'].values
            if 'hidden_strength' in df_rs.columns else np.zeros(n_rows, dtype=bool)
        )
        hidden_weakness = (
            df_rs['hidden_weakness'].values
            if 'hidden_weakness' in df_rs.columns else np.zeros(n_rows, dtype=bool)
        )
        if 'event_flag' in df_regime.columns:
            event_flags = df_regime['event_flag'].astype(str).tolist()
        else:
            event_flags = ['NORMAL'] * n_rows
        if hasattr(df_rs.index, 'strftime'):
            timestamps = [str(idx) for idx in df_rs.index]
        else:
            timestamps = [str(i) for i in range(n_rows)]

        states = state_engine.batch_update(
            closes, aps_vals, cds_vals, lcs_vals, vpocs,
            exp_effs, clvs, retentions, hidden_strength, hidden_weakness,
            event_flags, timestamps,
        )
        return states[-1] if states else None
