import logging
import pandas as pd
from typing import Dict, Any, Optional
from .data_fetcher import WyckoffDataFetcher
from .pattern_detector import WyckoffPatternDetector
from .recommendation_engine import RecommendationEngine
from .report_generator import WyckoffReportGenerator
from ..config.settings import WyckoffConfig
from ..exceptions import WyckoffError, DataError, CalculationError
from .enums import MarketEnvironment

logger = logging.getLogger(__name__)

class WyckoffOrchestrator:
    """
    威科夫分析编排器 (P2 #1)
    负责驱动整个分析生命周期
    """

    def __init__(self, config: WyckoffConfig = None):
        self.config = config or WyckoffConfig()
        self.data_fetcher = WyckoffDataFetcher(self.config)
        self.rec_engine = RecommendationEngine(self.config)

    def run_analysis(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """
        运行完整分析流程
 
        将分析流程拆分为清晰的步骤，提高可读性和可测试性。
        """
        try:
            # 步骤1: 数据获取和准备
            resolved_symbol, data = self._fetch_and_prepare_data(symbol, period)
 
            # 步骤1.5: 跨周期协调器初始化与数据抓取 (降级兼容)
            from .multi_timeframe_coordinator import MultiTimeframeCoordinator
            mtf_coordinator = MultiTimeframeCoordinator()
            mtf_coordinator.set_timeframe_data('daily', data)
 
            # 尝试抓取周线
            try:
                _, weekly_data = self.data_fetcher.fetch_data(symbol, period, frequency="1w")
                if weekly_data is not None and len(weekly_data) > 0:
                    mtf_coordinator.set_timeframe_data('weekly', weekly_data)
            except Exception as e:
                logger.info(f"无法获取周线数据，忽略周线共振: {e}")
 
            # 尝试获取小时线数据 (通常 1y 的小时线可能太大，我们可以用最近 1 个月 "1m" 的 1h 数据)
            try:
                _, hourly_data = self.data_fetcher.fetch_data(symbol, "1m", frequency="1h")
                if hourly_data is not None and len(hourly_data) > 0:
                    mtf_coordinator.set_timeframe_data('hourly', hourly_data)
            except Exception as e:
                logger.info(f"无法获取小时线数据，忽略小时线共振: {e}")
 
            # 步骤2: 形态检测和阶段识别
            patterns, detector = self._detect_patterns_and_phase(data)
 
            # 步骤3: 市场环境分析
            market_env = self._analyze_market_env(resolved_symbol, period)
 
            # 步骤4: 生成交易建议 (注入多周期共振)
            quality, trading_plan, risk_advice, resonance_result = self._generate_recommendations(
                data, patterns, market_env, detector, mtf_coordinator
            )
 
            # 步骤5: 组装结果包
            return self._assemble_result(
                resolved_symbol, data, patterns, market_env,
                quality, trading_plan, risk_advice, resonance_result
            )
 
        except (DataError, CalculationError):
            # 数据/计算错误直接向上传播，由调用方根据 silent_fail 决定处理方式
            raise
        except WyckoffError:
            raise
        except Exception as e:
            logger.exception(f"分析执行异常: {symbol}")
            raise CalculationError("Orchestrator", str(e)) from e

    def _fetch_and_prepare_data(self, symbol: str, period: str) -> tuple:
        """
        步骤1: 数据获取和准备

        Returns:
            (resolved_symbol, data) 元组
        """
        resolved_symbol, data = self.data_fetcher.fetch_data(symbol, period)
        return resolved_symbol, data

    def _detect_patterns_and_phase(self, data: pd.DataFrame) -> tuple:
        """
        步骤2: 形态检测和阶段识别

        Returns:
            (patterns, detector) 元组

        关键修复：确保在调用 detect_sos() 之前正确设置阶段信息
        """
        # WyckoffPatternDetector 会创建内部 IndicatorCache，无需外部传入
        detector = WyckoffPatternDetector(data, self.config, analysis_cache=None)

        # 首先获取阶段信息（这会触发 _collect_all_events()）
        phase_info = detector.identify_phase()
        phase_str = phase_info.get('phase', '')

        # 设置阶段信息到检测器（让 SOS/SOW 检测器根据阶段动态调整）
        if hasattr(detector, 'sw_detector') and hasattr(detector.sw_detector, 'set_current_phase'):
            detector.sw_detector.set_current_phase(phase_str)

        # 收集形态模式
        patterns = self._collect_patterns(detector, phase=phase_str)
        patterns.update(phase_info)

        return patterns, detector

    def _generate_recommendations(
        self, data: pd.DataFrame, patterns: Dict, market_env: Any, detector,
        mtf_coordinator: Optional[Any] = None
    ) -> tuple:
        """
        步骤4: 生成交易建议

        Returns:
            (quality, trading_plan, risk_advice, resonance_result) 元组
        """
        # 找出当前主要的检测信号并运行跨周期共振验证
        resonance_result = None
        has_conflict = False
        conflict_details = ""
        
        if mtf_coordinator:
            # 找到发生的第一个核心信号
            detected_signal_type = "spring"  # 默认
            detected_direction = "long"      # 默认做多
            
            for sig in ['joc', 'spring', 'sos', 'lps']:
                if patterns.get(sig, {}).get('detected'):
                    detected_signal_type = sig
                    detected_direction = 'long'
                    break
            else:
                for sig in ['fti', 'upthrust', 'sow', 'lpsy']:
                    if patterns.get(sig, {}).get('detected'):
                        detected_signal_type = sig
                        detected_direction = 'short'
                        break

            # 运行跨周期共振验证
            resonance_result = mtf_coordinator.verify_signal_resonance(
                detected_signal_type, detected_direction, patterns
            )
            
            # 判断是否有跨周期冲突
            weekly_dir = resonance_result.get('weekly_trend', {}).get('direction', 'neutral')
            if weekly_dir != 'neutral' and weekly_dir != detected_direction:
                has_conflict = True
                conflict_details = f"周线趋势方向为 {weekly_dir}，但日线威科夫信号 {detected_signal_type.upper()} 方向为 {detected_direction}，二者冲突。"

        # 计算信号质量
        quality = self.rec_engine.calculate_signal_quality(data, patterns, market_env)

        # 计算因果目标
        targets = self._calculate_targets(detector)

        # 生成交易计划和风险建议
        trading_plan = self.rec_engine.generate_trading_plan(data, patterns, targets)
        
        # 将共振状态融入风险建议与决策中
        risk_advice = self.rec_engine.generate_risk_advice(
            quality, trading_plan,
            has_conflict=has_conflict,
            conflict_details=conflict_details,
            market_env=market_env,
            data=data,
            phase_str=patterns.get('phase', '')
        )

        return quality, trading_plan, risk_advice, resonance_result

    def _assemble_result(
        self, symbol: str, data: pd.DataFrame, patterns: Dict,
        market_env: Any, quality: Dict, trading_plan: Dict, risk_advice: Dict,
        resonance_result: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        步骤5: 组装最终结果包

        Returns:
            包含所有分析结果的字典
        """
        res = {
            "symbol": symbol,
            "data": data,
            "patterns": patterns,
            "market_env": market_env,
            "quality": quality,
            "trading_plan": trading_plan,
            "risk_advice": risk_advice
        }
        if resonance_result:
            res["resonance"] = resonance_result
        return res

    def _collect_patterns(self, detector: WyckoffPatternDetector, phase: str = '') -> Dict[str, Any]:
        """
        收集形态检测结果
        
        关键修复：传入阶段信息，让SOS检测器根据阶段动态调整信号分类
        - 在派发阶段，向上突破应归类为UT/UTAD
        - 在吸筹阶段，向上突破才是SOS
        """
        # 关键修复：在检测SOS之前，先设置当前阶段
        if hasattr(detector, 'sw_detector') and hasattr(detector.sw_detector, 'set_current_phase'):
            detector.sw_detector.set_current_phase(phase)

        trading_range = detector.detect_trading_range()
        spring = detector.detect_spring_menhongtao()
        sos = detector.detect_sos()
        sow = detector.detect_sow(trading_range=trading_range)
        joc = detector.detect_joc_menhongtao()

        return {
            "joc": joc,
            "fti": detector.detect_fti(),
            "spring": spring,
            "upthrust": detector.detect_upthrust(),
            "sos": sos,
            "sow": sow,
            "lps": detector.detect_lps(sos, spring, trading_range=trading_range, joc_result=joc),
            "lpsy": detector.detect_lpsy(trading_range=trading_range)
        }

    def _analyze_market_env(self, symbol: str, period: str) -> Any:
        # 简化版大盘分析 (未来从 WyckoffAnalyzer 彻底迁移)
        return MarketEnvironment.UNKNOWN

    def _calculate_targets(self, detector: WyckoffPatternDetector) -> Dict[str, Any]:
        # 因果目标计算 (基于水平准备时长)
        tr = detector.detect_trading_range()
        if tr.get('is_consolidation'):
            duration = tr.get('consolidation_duration_days', 40)
            # 估算波动率
            recent_data = detector.data.tail(20)
            atr = (recent_data['High'] - recent_data['Low']).mean()
            potential = duration * atr * 0.25 # 修正系数
            
            return {
                "target_1": round(tr['high'] + potential * 0.618, 2),
                "target_2": round(tr['high'] + potential, 2),
                "target_3": round(tr['high'] + potential * 1.618, 2)
            }
        return {}
