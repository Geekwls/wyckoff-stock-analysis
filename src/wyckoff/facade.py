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
            
            # 科创板：688开头
            if code.startswith('688'):
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
        """
        计算因果效应 (基于点数图水平计数)
        
        威科夫因果法则核心：
        - 因（Cause）：水平准备（横向盘整的规模，用点数图列数衡量）
        - 果（Effect）：垂直运动（价格突破后的目标幅度）
        
        正确方法：使用点数图（P&F）的水平计数来预测垂直目标
        简单的"天数×ATR×斐波那契"不是威科夫方法
        """
        if not self.pattern_detector:
            return {}
        
        # 获取交易区间信息
        tr = self.pattern_detector.detect_trading_range()
        if not tr.get('is_consolidation'):
            return {}
        
        try:
            # 关键修复：先获取当前阶段，用于确定因果法则的目标方向
            phase_result = self.identify_phase()
            current_phase = phase_result.get('phase', '')
            
            # 使用点数图计算因果效应
            # box_size_pct=1.0 表示每个箱体为价格的1%
            # reversal_boxes=3 表示需要3个箱体的反转才改变方向
            # phase: 传入阶段信息，让因果法则计算考虑阶段方向
            pnf_result = calculate_cause_effect_from_pnf(
                self.data, 
                box_size_pct=1.0,
                reversal_boxes=3,
                phase=current_phase  # 传入阶段信息
            )
            
            # 如果点数图计算成功
            if pnf_result.get('horizontal_count', 0) >= 3:
                return {
                    'method': 'point_and_figure',
                    'cause_bars': pnf_result.get('horizontal_count', 0),
                    'vertical_count': pnf_result.get('vertical_count', 0),
                    'accumulation_range': pnf_result.get('accumulation_range', {}),
                    'base_effect': pnf_result.get('base_effect', 0),
                    'breakout_direction': pnf_result.get('breakout_direction', 'up'),
                    'description': pnf_result.get('description', ''),
                    'targets': pnf_result.get('targets', {}),
                    'theory': '威科夫因果法则：水平计数决定垂直目标'
                }
            else:
                # 如果点数图计算失败，使用改进的估算方法
                # 基于波动率收缩和时间积累的综合估算
                cause_bars = tr.get('consolidation_duration_days', 40)
                
                # 计算波动率收缩程度（真正的"因"）
                recent_data = self.data.tail(cause_bars)
                if len(recent_data) < 10:
                    return {}
                
                # 使用ATR的百分比变化来衡量波动率收缩
                atr_series = (recent_data['High'] - recent_data['Low']).rolling(window=5).mean()
                atr_start = atr_series.iloc[0] if len(atr_series) > 0 else 0
                atr_end = atr_series.iloc[-1] if len(atr_series) > 0 else 0
                
                # 波动率收缩越明显，积累的能量越大
                volatility_contraction = 1 - (atr_end / atr_start) if atr_start > 0 else 0
                
                # 基于波动率收缩和时间积累计算潜力
                base_price = tr['high']
                price_range = tr['high'] - tr['low']
                
                # 使用波动率收缩系数调整目标
                # 收缩越明显，突破潜力越大
                contraction_factor = max(0.5, 1 + volatility_contraction * 2)
                potential_move = price_range * contraction_factor * (cause_bars / 30)
                
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
                    'theory': '改进估算：基于波动率收缩和时间积累'
                }
                
        except Exception as e:
            logger.warning(f"点数图计算失败，使用备用方法: {e}")
            # 备用方法
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
