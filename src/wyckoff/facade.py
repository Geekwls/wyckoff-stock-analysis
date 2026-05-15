#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析器 - Facade (库层)
Wyckoff Analyzer - Facade for Orchestrator and Detectors

这是纯库层代码，不依赖任何应用层代码。
"""

import pandas as pd
import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

# 库层内部导入
from .config.settings import WyckoffConfig, WyckoffThresholds
from .core.enums import MarketEnvironment, WyckoffPhase
from .core.cache_service import CacheService
from .core.orchestrator import WyckoffOrchestrator
from .core.pattern_detector import WyckoffPatternDetector
from .core.law_analyzer import WyckoffLawAnalyzer
from .core.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from .core.relative_strength_analyzer import RelativeStrengthAnalyzer
from .core.report_generator import WyckoffReportGenerator
from .core.point_and_figure import PointAndFigureCalculator, calculate_cause_effect_from_pnf
from .core.sos_sow_analyzer import SOSSOWAnalyzer

logger = logging.getLogger(__name__)


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
    ):
        self.symbol = symbol
        self.period = period
        self.config = config or WyckoffConfig()
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
                          current_price, key_events_summary, phase_advice }
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

            import json as _json
            return _json.dumps({
                'symbol': self.symbol,
                'phase': phase_str,
                'phase_confidence': round(float(confidence), 3),
                'sequence_completeness': round(float(seq_completeness), 3),
                'current_price': current_price,
                'key_events_summary': events_summary,
                'phase_advice': phase_advice,
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            import json as _json
            return _json.dumps({'error': str(e), 'symbol': self.symbol}, ensure_ascii=False)

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

        except Exception as e:
            import json as _json
            return _json.dumps({'error': str(e), 'symbol': self.symbol}, ensure_ascii=False)

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
            
        except Exception as e:
            import json as _json
            return _json.dumps({'error': str(e), 'symbol': self.symbol}, ensure_ascii=False)

    # ----------------------------------------------------------
    # 代理旧方法 (为了兼容性)
    # ----------------------------------------------------------
    def identify_phase(self):
        """识别威科夫阶段"""
        return self.pattern_detector.identify_phase()

    def detect_trading_range(self):
        """检测交易区间"""
        return self.pattern_detector.detect_trading_range()

    def _get_baseline_index_symbol(self) -> str:
        """
        获取基准指数代码
        
        A股市场分类：
        - 上证主板：600/601/603/605开头 → sh.000001 (上证综指)
        - 科创板：688开头 → sh.000688 (科创50) 或 sh.000001
        - 深证主板：000/001/002/003开头 → sz.399001 (深证成指)
        - 创业板：300/301开头 → sz.399006 (创业板指)
        - 北交所：8/4开头 → bj.899050 (北证50)
        """
        from .core.symbol_resolver import SymbolResolver, MarketType
        info = SymbolResolver().resolve(self.symbol)
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
        
        # 美股
        return "SPY"

    def _analyze_market_environment(self) -> Dict:
        """
        分析市场环境
        
        基于指数的均线排列判断大盘环境：
        - BULLISH: MA20 > MA50 > MA200 (多头排列)
        - BEARISH: MA20 < MA50 < MA200 (空头排列)
        - NEUTRAL: 其他情况
        """
        try:
            # 获取基准指数代码
            index_symbol = self._get_baseline_index_symbol()
            
            # 获取指数分析器
            idx_analyzer = self._get_cached_index_analyzer()
            if not idx_analyzer or idx_analyzer.data is None or len(idx_analyzer.data) < 200:
                # 数据不足，返回未知
                return {
                    "environment": MarketEnvironment.UNKNOWN,
                    "reason": "指数数据不足200日",
                    "index_symbol": index_symbol
                }
            
            data = idx_analyzer.data
            
            # 计算均线
            close = data['Close']
            ma20 = close.rolling(20).mean().iloc[-1]
            ma50 = close.rolling(50).mean().iloc[-1]
            ma200 = close.rolling(200).mean().iloc[-1]
            current_price = close.iloc[-1]
            
            # 判断均线排列
            # 多头排列：MA20 > MA50 > MA200 且价格在MA20之上
            if ma20 > ma50 > ma200 and current_price > ma20:
                environment = MarketEnvironment.STRONG_BULL
                description = "多头排列：MA20>MA50>MA200，顺势做多"
                trend_strength = "strong"
            # 弱势多头：MA20 > MA50 但 MA50 < MA200
            elif ma20 > ma50:
                environment = MarketEnvironment.WEAK_BULL
                description = "弱势多头：短期均线向上，中期均线承压"
                trend_strength = "weak"
            # 空头排列：MA20 < MA50 < MA200 且价格在MA20之下
            elif ma20 < ma50 < ma200 and current_price < ma20:
                environment = MarketEnvironment.STRONG_BEAR
                description = "空头排列：MA20<MA50<MA200，顺势做空"
                trend_strength = "strong"
            # 弱势空头：MA20 < MA50 但 MA50 > MA200
            elif ma20 < ma50:
                environment = MarketEnvironment.BEAR
                description = "弱势空头：短期均线向下，中期均线支撑"
                trend_strength = "weak"
            # 震荡/中性
            else:
                environment = MarketEnvironment.RANGE_BOUND
                description = "震荡整理：均线交织，方向不明"
                trend_strength = "neutral"
            
            # 计算价格相对MA200的位置（判断是否在牛熊分界线之上）
            price_vs_ma200 = (current_price - ma200) / ma200 * 100
            
            return {
                "environment": environment,
                "description": description,
                "trend_strength": trend_strength,
                "index_symbol": index_symbol,
                "current_price": round(float(current_price), 2),
                "ma20": round(float(ma20), 2),
                "ma50": round(float(ma50), 2),
                "ma200": round(float(ma200), 2),
                "price_vs_ma200_pct": round(float(price_vs_ma200), 2),
                "ma_alignment": f"MA20={ma20:.2f}, MA50={ma50:.2f}, MA200={ma200:.2f}"
            }
            
        except Exception as e:
            logger.warning(f"市场环境分析失败: {e}")
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
        try:
            # 创建指数分析器（注意：避免递归创建指数的指数）
            idx_analyzer = WyckoffAnalyzer(index_symbol, self.period, self.config, self.cache_service)
            idx_analyzer.fetch_data()
            self._index_analyzer_cache = idx_analyzer
            return idx_analyzer
        except Exception as e:
            logger.warning(f"Failed to initialize index analyzer for {index_symbol}: {e}")
            return None

    def calculate_cause_effect(self) -> Dict:
        if not self.pattern_detector:
            return {}

        tr = self.pattern_detector.detect_trading_range()
        if not tr:
            return {}

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

        except Exception as e:
            logger.warning(f"点数图计算失败，使用备用方法: {e}")
            cause_bars = tr.get('consolidation_duration_days', 40)
            base_price = tr['high']
            price_range = tr['high'] - tr['low']
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
