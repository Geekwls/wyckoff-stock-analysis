import pandas as pd
import logging
from typing import Dict, Any
from .reports.section_builders.header_section import HeaderSection
from .reports.section_builders.evidence_section import EvidenceSection
from .reports.section_builders.pattern_section import PatternSection
from .reports.section_builders.signal_section import SignalSection
from .reports.section_builders.conclusion_section import ConclusionSection
from .recommendation_engine import RecommendationEngine
from .enums import MarketEnvironment

logger = logging.getLogger(__name__)

class WyckoffReportGenerator:
    """
    威科夫分析报告生成器 (Facade)
    采用 Section Builders 模式拆分原本巨大的上帝类
    """
    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.data = analyzer.data
        self.config = analyzer.config
        self.symbol = analyzer.symbol
        self.pattern_detector = getattr(analyzer, 'pattern_detector', None)
        self.rec_engine = getattr(analyzer, 'orchestrator', Any).rec_engine if hasattr(analyzer, 'orchestrator') else RecommendationEngine(self.config)
        self.thresholds = getattr(analyzer, 'thresholds', None) or {}

        # 初始化区块构建器
        self.header_builder = HeaderSection(self)
        self.evidence_builder = EvidenceSection(self)
        self.pattern_builder = PatternSection(self)
        self.signal_builder = SignalSection(self)
        self.conclusion_builder = ConclusionSection(self)

    def generate_report(self) -> str:
        if self.data is None:
            self.analyzer.fetch_data()
            self.data = self.analyzer.data
            self.pattern_detector = self.analyzer.pattern_detector

        # 获取各检测器的结果
        phase_result = self.pattern_detector.identify_phase()
        trading_range = self.pattern_detector.detect_trading_range()
        
        # 模式检测
        spring = self.pattern_detector.detect_spring_menhongtao()
        upthrust = self.pattern_detector.detect_upthrust()
        sos = self.pattern_detector.detect_sos()
        sow = self.pattern_detector.detect_sow()
        lps = self.pattern_detector.detect_lps()
        lpsy = self.pattern_detector.detect_lpsy()
        
        # 高级信号
        joc = self.pattern_detector.detect_joc_menhongtao()
        fti = self.pattern_detector.detect_fti()
        vsa = self.pattern_detector.detect_vsa_menhongtao()
        boring_res = self.pattern_detector.detect_boring_zone()
        dead_corner = self.pattern_detector.detect_dead_corner_breakout()
        
        # 外部分析
        cause_effect = getattr(self.analyzer, 'calculate_cause_effect', lambda: {})()
        market_env_res = getattr(self.analyzer, '_analyze_market_environment', lambda: {})()
        market_env = market_env_res.get('environment', MarketEnvironment.UNKNOWN)
        
        # 信号质量
        patterns = self.pattern_detector._collect_all_events()
        patterns.update({'phase': phase_result.get('phase'), 'boring_zone': boring_res, 'dead_corner_breakout': dead_corner})
        quality_data = self.rec_engine.calculate_signal_quality(self.data, patterns, market_env)
        
        # 跨周期分析
        from .multi_timeframe_analyzer import MultiTimeframeAnalyzer
        mtf = MultiTimeframeAnalyzer(self.data, self.pattern_detector).analyze_resonance()
        conflict = self._analyze_conflict(phase_result.get('phase'), mtf)

        # 🔧 终极逻辑自检 (Final Sanity Check): 解决“诊断与处方打架”问题
        is_distribution = 'Distribution' in phase_result.get('phase', '')
        
        # 组装报告
        report = self.header_builder.build(phase_result, trading_range)
        report += self.evidence_builder.build(phase_result)
        report += self.pattern_builder.build(trading_range, spring, upthrust, sos, sow, lps, lpsy, phase_result.get('phase'))
        report += self.signal_builder.build(joc, fti, vsa, boring_res, dead_corner)
        
        # 在生成结论前，如果处于派发阶段，强制修正做多信号为无效
        if is_distribution:
            # 强制屏蔽做多信号的影响
            joc['detected'] = False
            lps['detected'] = False
            spring['detected'] = False
            logger.warning(f"Detection contradiction: Distribution phase detected. Bullish signals (JOC/LPS/Spring) suppressed for {self.symbol}.")

        report += self.conclusion_builder.build(
            phase_result, trading_range, cause_effect, conflict, quality_data,
            joc, spring, sos, lps, fti, upthrust, sow, lpsy, mtf,
            boring_res, dead_corner, market_env
        )
        
        return report

    def _analyze_conflict(self, phase, mtf) -> dict:
        weekly_trend = mtf.get('weekly_trend', 'unknown')
        monthly_trend = mtf.get('monthly_trend', 'unknown')
        trend_agreement = mtf.get('trend_agreement', False)
        
        # 简单的冲突检测逻辑
        has_conflict = not trend_agreement and weekly_trend != 'unknown'
        return {
            'has_conflict': has_conflict,
            'daily_side': 'bullish' if 'Accumulation' in str(phase) else 'bearish' if 'Distribution' in str(phase) else 'neutral',
            'weekly_trend': weekly_trend,
            'monthly_trend': monthly_trend
        }
