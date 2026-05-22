import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from .detectors.trading_range_detector import TradingRangeDetector
from .detectors.classic_pattern_detector import ClassicPatternDetector
from .detectors.strength_weakness_detector import StrengthWeaknessDetector
from .detectors.phase_identifier import PhaseIdentifier
from .detectors.channel_detector import ChannelDetector
from .meng_pattern_enhancer import MengPatternEnhancer
from .phase_coordinator import PhaseCoordinator
from .detectors.ps_detector import PsDetector
from .detectors.psy_detector import PsyDetector
from .adaptive.bayesian_updater import BayesianThresholdModel
from ..config.settings import WyckoffConfig, WyckoffThresholds
from ..schemas import (
    ClimaxModel, WyckoffEventModel, SpringModel, UpthrustModel,
    SosModel, SowModel, LpsModel, LpsyModel, TradingRangeModel,
    JocModel, FtiModel
)
from ..exceptions import (
    PatternDetectionError, PatternNotFoundError, AnalysisError,
    DataError, MissingFieldError, CalculationError
)
from .utils import TypeConverter
import logging

logger = logging.getLogger(__name__)

class WyckoffPatternDetector:
    """威科夫形态检测器 (Facade/Delegate)
    重构说明: 已将具体检测逻辑拆分至 detectors/ 目录下的子类中，以解决 God Object 问题。
    """
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, analysis_cache):
        self.data = data
        self.config = config
        self.thresholds = WyckoffThresholds()
        self._analysis_cache = analysis_cache

        # 初始化技术指标缓存（统一管理）
        from .indicator_cache import IndicatorCache
        self._indicator_cache = IndicatorCache(data)

        # 初始化专门的检测器
        self.range_detector = TradingRangeDetector(data, config, indicator_cache=self._indicator_cache)
        self.classic_detector = ClassicPatternDetector(data, config, self.thresholds, analysis_cache, indicator_cache=self._indicator_cache)
        self.sw_detector = StrengthWeaknessDetector(data, config, self.thresholds, indicator_cache=self._indicator_cache)
        self.phase_identifier = PhaseIdentifier(data, config, self.thresholds, indicator_cache=self._indicator_cache)
        self.channel_detector = ChannelDetector(data, use_log_price=False, indicator_cache=self._indicator_cache)
        self.ps_detector = PsDetector(data, config, self.thresholds, indicator_cache=self._indicator_cache)
        self.psy_detector = PsyDetector(data, config, self.thresholds, indicator_cache=self._indicator_cache)

        # 初始化孟洪涛增强检测器
        self.meng_enhancer = MengPatternEnhancer(data, config, self.thresholds, indicator_cache=self._indicator_cache)

        # 初始化阶段协调器（负责事件收集和阶段验证）
        self.phase_coordinator = PhaseCoordinator(self)

        # 注册所有子检测器以支持统一接口调用
        self.all_detectors = [
            self.range_detector, self.classic_detector,
            self.sw_detector, self.phase_identifier,
            self.meng_enhancer, self.channel_detector,
            self.ps_detector, self.psy_detector
        ]

        # 计算ATR百分比用于动态阈值
        self._atr_pct = self._calculate_atr_pct()

        # 贝叶斯自适应阈值系统
        self.bayesian_model = None
        if getattr(self.config, 'enable_adaptive_thresholds', False):
            self.bayesian_model = BayesianThresholdModel(
                prior_breakout_mu=getattr(self.config, 'prior_breakout_mu', 1.5),
                prior_shrink_mu=getattr(self.config, 'prior_shrink_mu', 0.6),
                prior_sigma=getattr(self.config, 'prior_sigma', 0.5)
            )
            self.bayesian_model.fit(
                self.data,
                breakout_percentile=getattr(self.config, 'amplitude_breakout_percentile', 85.0),
                shrink_percentile=getattr(self.config, 'amplitude_shrink_percentile', 15.0)
            )

    def _update_all_detectors_context(self, phase: str):
        """统一更新所有子检测器的分析上下文"""
        for detector in self.all_detectors:
            detector.update_analysis_context(phase)

    def _calculate_atr_pct(self) -> float:
        """
        计算ATR占价格的百分比

        Returns:
            ATR百分比（如0.03表示3%）
        """
        try:
            if 'ATR' in self.data.columns and len(self.data) > 0:
                atr = self.data['ATR'].iloc[-1]
                price = self.data['Close'].iloc[-1]
                if price > 0:
                    return float(atr / price)
            return 0.03  # 默认3%
        except (KeyError, TypeError, ValueError):
            return 0.03  # 默认3%

    def _get_dynamic_volume_threshold(self, base_threshold: float = 1.5) -> float:
        """
        获取动态成交量阈值

        Args:
            base_threshold: 基础阈值

        Returns:
            动态成交量阈值
        """
        if self.bayesian_model:
            return self.bayesian_model.get_volume_threshold('breakout', default=base_threshold)

        return self.thresholds.get_dynamic_volume_threshold(self._atr_pct, base_threshold)

    def _get_dynamic_shrink_volume_threshold(self, base_threshold: float = 0.6) -> float:
        """获取缩量时的动态阈值"""
        if self.bayesian_model:
            return self.bayesian_model.get_volume_threshold('shrink', default=base_threshold)
        return base_threshold

    def _calculate_climax_confidence(self, vol_ratio: float, close_pos: float = 0.5) -> float:
        """
        🔧 修复 P0-2: 计算 BC/SC 置信度（基于量比分层）

        理论依据：
        - 量比 < 2.0：不是真正的高潮，置信度 < 0.3
        - 量比 2.0-3.0：中等高潮，置信度 0.3-0.7
        - 量比 > 3.0：真正的巨量高潮，置信度 0.7-1.0

        Args:
            vol_ratio: 成交量相对于均量的倍数
            close_pos: 收盘位置（0=最低，1=最高），用于辅助判断

        Returns:
            置信度（0.0-1.0）
        """
        if vol_ratio < 2.0:
            # 低量比：置信度极低
            base_conf = (vol_ratio - 1.0) * 0.3
            # 如果收盘位置高（>0.7），进一步降低置信度（BC应该收盘疲软）
            if close_pos > 0.7:
                base_conf *= 0.5
            return max(0.0, min(0.3, base_conf))
        elif vol_ratio < 3.0:
            # 中等量比：置信度中等
            return 0.3 + (vol_ratio - 2.0) * 0.4
        else:
            # 高量比：置信度高
            return min(1.0, 0.7 + (vol_ratio - 3.0) * 0.1)

    def _validate_climax_effort_result(
        self,
        vol_ratio: float,
        price_progress: float,
        close_pos: float = 0.5
    ) -> tuple:
        """
        🔧 修复 P2-1: 验证 BC/SC 是否符合 Effort vs Result 原则

        理论依据：
        - 巨量但价格停滞 = Effort vs Result 背离（可能不是真正的高潮）
        - 缩量但价格大涨 = 弱势突破（需求不足）
        - 真正的 BC/SC 应该是巨量 + 显著价格推进

        Args:
            vol_ratio: 成交量相对于均量的倍数
            price_progress: 价格变化幅度（百分比）
            close_pos: 收盘位置（0=最低，1=最高）

        Returns:
            (is_valid, confidence_penalty, warning_message)
        """
        # 检查量价背离
        if vol_ratio > 1.5 and abs(price_progress) < 0.01:
            warning = "⚠️ 警告：量价背离，巨量未推动价格显著变化，可能不是真正的 BC/SC"
            return False, 0.5, warning

        # 检查缩量突破
        if vol_ratio < 1.2 and abs(price_progress) > 0.03:
            warning = "⚠️ 警告：缩量突破，需求不足，信号可靠性低"
            return False, 0.7, warning

        # 检查收盘位置（BC 应该收盘疲软）
        if close_pos > 0.7 and vol_ratio < 2.0:
            warning = "⚠️ 警告：收盘位置偏高位但量能不足，疑似诱多"
            return False, 0.6, warning

        # 通过验证
        return True, 1.0, None

    def _get_dynamic_price_threshold(self, base_threshold: float = 0.03) -> float:
        """
        获取动态价格变化阈值

        Args:
            base_threshold: 基础阈值

        Returns:
            动态价格变化阈值
        """
        return self.thresholds.get_dynamic_price_threshold(self._atr_pct, base_threshold)

    # --- 代理方法 (Delegated Methods) ---

    def detect_trading_range(self, window: int = 60) -> Dict:
        return self.range_detector.detect(window)

    def detect_climax(self) -> Dict:
        return self.classic_detector.detect_climax()

    def detect_automatic_reaction(self, climax_res: Dict) -> Dict:
        return self.classic_detector.detect_automatic_reaction(climax_res)

    def detect_secondary_test(self, climax_res: Dict, ar_res: Dict) -> Dict:
        return self.classic_detector.detect_secondary_test(climax_res, ar_res)

    def detect_spring(self, lookback: int = None) -> Dict:
        #  缺隗3修复：传递TR数据，让子检测器能用TR下沿作为Spring支撑位
        tr = self.range_detector.detect()
        return self.classic_detector.detect_spring(lookback, trading_range=tr)

    def detect_upthrust(self, lookback: int = None) -> Dict:
        return self.classic_detector.detect_upthrust(lookback)

    def detect_sos(self, window: int = 40) -> Dict:
        return self.sw_detector.detect_sos(window)

    def detect_sow_variants(self) -> Dict:
        return self.sw_detector.detect_sow_variants()

    def detect_channels(self) -> Dict:
        return self.channel_detector.detect()

    def detect_joc(self, lookback: int = 90, trading_range: Dict = None) -> Dict:
        """检测 JOC (Jump Over Creek) 跃过小溪"""
        # 联动逻辑：如遇超买刺穿+放量，则抑制普通 JOC，改报趋势耗尽
        channel_res = self.detect_channels()
        ob_os = channel_res.get('overbought_oversold')
        if ob_os and ob_os['status'] == 'overbought':
            return {
                'detected': False,
                'reason': 'suppressed_by_overbought_climax',
                'channel_warning': ob_os['message']
            }

        joc_res = self.classic_detector.detect_joc(lookback, trading_range=trading_range)

        # 联动“吸收”检测，增强置信度
        if joc_res.get('detected'):
            tr_for_abs = trading_range if trading_range is not None else self.detect_trading_range()
            absorption_res = self.detect_absorption(trading_range=tr_for_abs)
            if absorption_res.get('detected'):
                joc_res['absorption_confirmed'] = True
                joc_res['confidence'] = float(min(1.0, joc_res.get('confidence', 0.7) * 1.25))
                joc_res['description'] = joc_res.get('description', '') + f" | 🌟 [主力强力吸收确认] 突破前有 {absorption_res['consecutive_days']} 天完美的蓄势吸收，此突破极大概率为真实突破 (JOC)"

            #  区间失效级联风控：若 TR 已失效，同步折半置信度并提示风险
            if trading_range and trading_range.get('invalidated_tr') == True:
                joc_res['confidence'] = float(joc_res.get('confidence', 0.8) * 0.5)
                warning_note = " ⚠️ [风控警告] 当前有效交易区间(TR)已被标记为【已失效/已跌破】，参考系已崩塌，此 JOC 突破的置信度已自动折半（防范假突破）！"
                joc_res['description'] = joc_res.get('description', '') + warning_note
                joc_res['warning'] = warning_note

        return joc_res

    def detect_fti(self, lookback: int = 90, trading_range: Dict = None) -> Dict:
        """检测 FTI (Fall Through Ice) 跌破冰线"""
        # 联动逻辑：如遇超卖刺穿+放量，则抑制普通 FTI，改报趋势耗尽
        channel_res = self.detect_channels()
        ob_os = channel_res.get('overbought_oversold')
        if ob_os and ob_os['status'] == 'oversold':
            return {
                'detected': False,
                'reason': 'suppressed_by_oversold_climax',
                'channel_warning': ob_os['message']
            }

        fti_res = self.classic_detector.detect_fti(lookback, trading_range=trading_range)

        #  区间失效级联风控：若 TR 已失效，同步折半置信度并提示风险
        if fti_res.get('detected'):
            if trading_range and trading_range.get('invalidated_tr') == True:
                fti_res['confidence'] = float(fti_res.get('confidence', 0.8) * 0.5)
                warning_note = " ⚠️ [风控警告] 当前有效交易区间(TR)已被标记为【已失效/已突破】，参考系已崩塌，此 FTI 破位的置信度已自动折半（防范假跌破）！"
                fti_res['description'] = fti_res.get('description', '') + warning_note
                fti_res['warning'] = warning_note

        return fti_res

    def detect_vsa_signals(self, lookback: int = 20) -> Dict:
        return self.classic_detector.detect_vsa_signals(lookback)

    def detect_utad(self, lookback: int = 120) -> Dict:
        """检测 UTAD（派发后的上冲回落）"""
        return self.classic_detector.detect_utad(lookback)

    def detect_divergence(self, window: int = 30) -> Dict:
        return self.classic_detector.detect_divergence(window)

    def identify_phase(self) -> Dict:
        # 收集事件后识别（使用阶段协调器）
        events = self.phase_coordinator.collect_all_events()
        phase_result = self.phase_identifier.identify(events)

        # 附加事件序列验证结果
        phase_result['sequence_validation'] = getattr(events, 'sequence_validation', {})

        # 构建 events_detected（供 scoring 引擎使用）
        # 直接使用强类型 EventsModel
        phase_result['events_detected'] = events

        # 将独立的吸收检测加入结果
        abs_res = self.detect_absorption()
        if abs_res and abs_res.get('detected'):
            phase_result['absorption'] = abs_res

        # 集成孟洪涛核心证据分析
        evidence_analysis = self.analyze_phase_a_evidence(events)

        # 将证据分析结果添加到 phase_result 中
        phase_result['core_evidence'] = evidence_analysis

        # 如果有证据分析，更新阶段描述
        if 'error' not in evidence_analysis:
            if evidence_analysis['strength'] == 'strong':
                phase_result['confidence'] = max(phase_result.get('confidence', 0), 0.80)
            elif evidence_analysis['strength'] == 'weak':
                phase_result['confidence'] = max(phase_result.get('confidence', 0), 0.50)
            elif evidence_analysis['strength'] == 'none':
                # 如果没有核心证据，降低置信度
                if 'Accumulation' in phase_result.get('phase', ''):
                    phase_result['confidence'] = min(phase_result.get('confidence', 0.50), 0.30)

        return phase_result

    # --- 私有辅助方法 ---

    # 以下复杂方法已迁移到 PhaseCoordinator 类以减少代码复杂度
    # 委托给协调器处理，保持向后兼容性

    def _collect_all_events(self) -> Dict[str, Any]:
        """
        收集所有威科夫事件（委托给阶段协调器）

        此方法保留以保持向后兼容性，实际逻辑由 PhaseCoordinator 处理
        """
        return self.phase_coordinator.collect_all_events()

    def detect_sow(self, trading_range: Dict = None) -> Dict:
        """
        检测 SOW (Sign of Weakness)

        🔧 新增：传递交易区间参数用于验证是否跌破区间下沿
        """
        if trading_range is None:
            trading_range = self.detect_trading_range()
        return self.sw_detector.detect_sow(trading_range=trading_range)

    def detect_lps(self, sos_result: Dict = None, spring_res: Dict = None, trading_range: Dict = None) -> Dict:
        """检测 LPS (Last Point of Support)"""
        if trading_range is None:
            trading_range = self.detect_trading_range()
        return self.sw_detector.detect_lps(spring_res=spring_res, trading_range=trading_range, sos_result=sos_result)

    def detect_lpsy(self, sow_result: Dict = None, trading_range: Dict = None) -> Dict:
        """检测 LPSY (Last Point of Supply)"""
        if trading_range is None:
            trading_range = self.detect_trading_range()
        return self.sw_detector.detect_lpsy(trading_range=trading_range)

    # --- 孟洪涛增强检测方法 ---

    def detect_spring_menhongtao(self) -> Dict:
        """
        孟洪涛Spring（震仓）增强检测
        """
        try:
            return self.meng_enhancer.detect_spring_enhanced()
        except Exception as e:
            logger.exception(f"孟洪涛Spring检测失败: {e}")
            return self.detect_spring()

    def detect_joc_menhongtao(self) -> Dict:
        """
        孟洪涛JOC（跃过小溪）增强检测
        """
        try:
            return self.meng_enhancer.detect_joc_enhanced()
        except Exception as e:
            logger.exception(f"孟洪涛JOC检测失败: {e}")
            return self.detect_joc()

    def detect_vsa_menhongtao(self) -> Dict:
        """
        孟洪涛VSA（Volume Spread Analysis）微观分析
        集成孟洪涛增强信号 + 经典VSA信号（Bag Holding, Shakeout, Divergence）
        """
        try:
            # 获取孟洪涛增强VSA信号（含成交量趋势上下文）
            vsa_signals = self.meng_enhancer.detect_vsa_signals()

            # 集成经典VSA信号
            try:
                bag_holding = self.classic_detector.detect_bag_holding()
                vsa_signals['bag_holding'] = bag_holding
            except Exception as e:
                logger.debug(f"Bag Holding检测失败: {e}")
                vsa_signals['bag_holding'] = {"detected": False}

            try:
                shakeout = self.classic_detector.detect_shakeout(self.sw_detector)
                vsa_signals['shakeout'] = shakeout
            except Exception as e:
                logger.debug(f"Shakeout检测失败: {e}")
                vsa_signals['shakeout'] = {"detected": False}

            try:
                divergence = self.classic_detector.detect_divergence()
                vsa_signals['divergence'] = divergence
            except Exception as e:
                logger.debug(f"Divergence检测失败: {e}")
                vsa_signals['divergence'] = {"detected": False}

            return vsa_signals
        except Exception as e:
            logger.exception(f"VSA检测失败: {e}")
            return {
                "no_supply": {"detected": False, "error": str(e)},
                "no_demand": {"detected": False, "error": str(e)},
                "stopping_vol": {"detected": False, "error": str(e)},
                "bag_holding": {"detected": False},
                "shakeout": {"detected": False},
                "divergence": {"detected": False},
                "volume_trend": {"trend": "unknown"}
            }

    def detect_boring_zone(self) -> Dict:
        """检测枯燥区 (Boring Zone)"""
        return self.meng_enhancer.detect_boring_zone()

    def detect_dead_corner_breakout(self) -> Dict:
        """检测死角突破 (Dead Corner Breakout)"""
        return self.meng_enhancer.detect_dead_corner_breakout()

    def detect_rvs(self, market_df: Optional[pd.DataFrame] = None, industry_dfs: Optional[Dict] = None) -> Dict:
        """检测成交量相对强度 (RVS)"""
        return self.meng_enhancer.detect_rvs(market_df, industry_dfs)

    def detect_choch(self) -> Dict:
        """检测特征变异 (CHoCH)"""
        return self.meng_enhancer.reversal.detect_choch()

    def detect_preliminary_support(self, lookback: int = 90) -> Dict:
        """检测初次支撑 (Preliminary Support, PS)"""
        return self.meng_enhancer.detect_preliminary_support(lookback)

    def detect_preliminary_supply(self, lookback: int = 90) -> Dict:
        """检测初次供应 (Preliminary Supply, PSY)"""
        return self.meng_enhancer.detect_preliminary_supply(lookback)

    def _handle_detection_error(self, pattern_type: str, exc: Exception) -> Dict:
        """
        统一异常处理逻辑
        根据 silent_fail 配置决定是抛出异常还是返回降级结果。
        """
        # 提取详细上下文信息
        cols_context = f", 现有列: {list(self.data.columns)}" if hasattr(self, 'data') and self.data is not None else ""
        data_len_context = f", 数据行数: {len(self.data)}" if hasattr(self, 'data') and self.data is not None else ""
        last_row_context = ""
        if hasattr(self, 'data') and self.data is not None and not self.data.empty:
            try:
                last_row_context = f", 最新数据截面: {self.data.iloc[-1].to_dict()}"
            except Exception:
                pass

        if isinstance(exc, (DataError, MissingFieldError)):
            # 数据层错误：始终向上传播，除非开启静默模式
            err_msg = f"[{pattern_type}] 数据异常 (静默模式): {exc}{cols_context}"
            if self.config.silent_fail:
                logger.error(err_msg)
                return {"detected": False, "error": f"DataError: {exc}", "error_code": exc.error_code.value}
            logger.error(f"[{pattern_type}] 数据异常: {exc}{cols_context}")
            raise exc
        elif isinstance(exc, (CalculationError, PatternDetectionError)):
            # 计算/逻辑错误：始终向上传播
            err_msg = f"[{pattern_type}] 计算异常 (静默模式): {exc}{data_len_context}{last_row_context}"
            if self.config.silent_fail:
                logger.error(err_msg)
                return {"detected": False, "error": str(exc)}
            logger.error(f"[{pattern_type}] 计算异常: {exc}{data_len_context}{last_row_context}")
            raise
        elif isinstance(exc, PatternNotFoundError):
            # 业务性"无信号"：返回正常结果
            return {"detected": False, "reason": exc.reason}
        else:
            # 未知异常
            err_msg = f"[{pattern_type}] 未知异常: {exc}{data_len_context}{last_row_context}"
            if self.config.silent_fail:
                logger.exception(f"[{pattern_type}] 未知异常 (静默模式): {exc}{data_len_context}{last_row_context}")
                return {"detected": False, "error": f"Unexpected: {exc}"}
            logger.error(err_msg)
            raise PatternDetectionError(pattern_type, str(exc)) from exc

    # ============================================================
    # 孟洪涛核心证据检测（Core Evidence Detection）
    # ============================================================

    def _detect_climax(self, direction: str, lookback_days: int = 60) -> Dict:
        """
        通用高潮检测核心逻辑
        Args:
            direction: 'selling' (SC) 或 'buying' (BC)
            lookback_days: 回溯天数
        """
        is_selling = direction == 'selling'
        label = "SC" if is_selling else "BC"
        climax_type = "selling_climax" if is_selling else "buying_climax"

        # 检查必要字段
        required_cols = {'Close', 'Open', 'Volume', 'High', 'Low'}
        missing = required_cols - set(self.data.columns)
        if missing:
            raise MissingFieldError(f"缺失必要列: {missing}")

        # 优化 1: 在全局 DataFrame 上计算滑动均值，避免 tail 截取导致的边界 NaN 丢数据问题
        global_vol_ma = self.data['Volume_MA20'] if 'Volume_MA20' in self.data.columns else self.data['Volume'].rolling(20).mean()
        global_high_low_range = self.data['High'] - self.data['Low']
        global_avg_range = global_high_low_range.rolling(20).mean()

        recent_data = self.data.tail(lookback_days)
        vol_ma = global_vol_ma.loc[recent_data.index]
        high_low_range = global_high_low_range.loc[recent_data.index]
        avg_range = global_avg_range.loc[recent_data.index]

        # 动态阈值
        climax_vol_threshold = self._get_dynamic_volume_threshold(max(self.thresholds.VOLUME_CONFIRMATION['strong'], 2.5))
        fallback_vol_threshold = self._get_dynamic_volume_threshold(2.5)

        if is_selling:
            # SC: 阴线 + 价差放大
            # 优化 4: 纠正价格与成交量动态阈值混用偏差。将 1.8x 乘数与自适应价格波动率自适应绑定
            climax_range_threshold = 1.8 * (self._get_dynamic_price_threshold(0.03) / 0.03)
            candidates = recent_data[
                (recent_data['Volume'] > vol_ma * climax_vol_threshold) &
                (high_low_range > avg_range * climax_range_threshold) &
                (recent_data['Close'] < recent_data['Open'])
            ]
            if candidates.empty:
                min_idx = recent_data['Low'].idxmin()
                min_row = recent_data.loc[min_idx]
                vol_ratio = min_row['Volume'] / vol_ma.loc[min_idx] if vol_ma.loc[min_idx] > 0 else 1.0
                if vol_ratio > fallback_vol_threshold:
                    climax_idx = min_idx
                else:
                    return {"detected": False, "reason": "No climactic volume found at lows"}
            else:
                climax_idx = candidates.index[-1]
        else:
            # BC: 收盘偏低 或 长上影线
            range_size = recent_data['High'] - recent_data['Low']
            close_pos = (recent_data['Close'] - recent_data['Low']) / range_size.replace(0, 1e-9)
            upper_shadow = recent_data['High'] - recent_data[['Open', 'Close']].max(axis=1)
            upper_shadow_ratio = upper_shadow / range_size.replace(0, 1e-9)

            candidates = recent_data[
                (recent_data['Volume'] > vol_ma * climax_vol_threshold) &
                ((close_pos < 0.5) | (upper_shadow_ratio > 0.4))
            ]
            if candidates.empty:
                max_idx = recent_data['High'].idxmax()
                max_row = recent_data.loc[max_idx]
                vol_ratio = max_row['Volume'] / vol_ma.loc[max_idx] if vol_ma.loc[max_idx] > 0 else 1.0
                max_close_pos = (max_row['Close'] - max_row['Low']) / max(max_row['High'] - max_row['Low'], 1e-9)
                max_upper_shadow = (max_row['High'] - max(max_row['Open'], max_row['Close'])) / max(max_row['High'] - max_row['Low'], 1e-9)
                if vol_ratio > fallback_vol_threshold and (max_close_pos < 0.6 or max_upper_shadow > 0.3):
                    climax_idx = max_idx
                else:
                    return {"detected": False, "reason": "No climactic volume found at highs with poor close"}
            else:
                climax_idx = candidates.index[-1]

        row = recent_data.loc[climax_idx]
        vol_ratio = row['Volume'] / vol_ma.loc[climax_idx]

        # Squat Bar 检测
        bar_vol = row['Volume']
        bar_spread = row['High'] - row['Low']
        bar_vol_ma20 = vol_ma.loc[climax_idx]
        bar_spread_ma20 = avg_range.loc[climax_idx] if not pd.isna(avg_range.loc[climax_idx]) else bar_spread

        is_squat = (bar_vol > bar_vol_ma20 * 2.0) and (bar_spread < bar_spread_ma20 * 0.8)
        squat_dir = "none"
        if is_squat:
            squat_dir = "bullish" if row['Close'] >= (row['High'] + row['Low']) / 2.0 else "bearish"

        # 置信度计算
        close_pos = (row['Close'] - row['Low']) / max(row['High'] - row['Low'], 1e-9)
        base_confidence = self._calculate_climax_confidence(vol_ratio, close_pos)

        # Effort vs Result 验证
        price_progress = (row['Close'] - row['Open']) / row['Open']
        is_valid, penalty, warning = self._validate_climax_effort_result(vol_ratio, price_progress, close_pos)

        # Squat Bar 联动
        if is_selling and is_squat and squat_dir == "bullish":
            is_valid = True
            penalty = 1.0
            base_confidence = min(1.0, base_confidence * 1.15)
            logger.info(f"[{label} 蹲坐柱联动] 检测到看涨蹲坐柱，豁免背离惩罚并提升置信度")
        elif not is_selling and is_squat and squat_dir == "bearish":
            is_valid = True
            penalty = 1.0
            base_confidence = min(1.0, base_confidence * 1.15)
            logger.info(f"[{label} 蹲坐柱联动] 检测到看跌蹲坐柱，豁免背离惩罚并提升置信度")

        if warning and not ((is_selling and is_squat and squat_dir == "bullish") or (not is_selling and is_squat and squat_dir == "bearish")):
            logger.warning(f"[{label} Effort vs Result] {warning}")

        confidence = base_confidence * penalty
        price_key = 'Low' if is_selling else 'High'

        result = {
            "detected": True,
            "date": climax_idx,
            "price": float(row[price_key]),
            "volume": float(row['Volume']),
            "type": climax_type,
            "volume_ratio": float(vol_ratio),
            "confidence": float(confidence)
        }
        self.classic_detector.reversal._verify_climax_confirmation(result)
        return result

    def detect_climax_panic_selling(self, lookback_days: int = 60) -> Dict:
        """
        检测恐慌性抛售（Selling Climax, SC）
        理论依据：主跌段末端，成交量极度放大，价差扩大，通常伴随长下影线。
        """
        try:
            return self._detect_climax('selling', lookback_days)
        except (DataError, MissingFieldError, CalculationError, PatternDetectionError, PatternNotFoundError):
            raise
        except Exception as e:
            return self._handle_detection_error("SC", e)

    def detect_climax_buying(self, lookback_days: int = 60) -> Dict:
        """
        检测买入高潮（Buying Climax, BC）
        理论依据：主升段末端，成交量异常放大，价格创阶段新高，但收盘表现疲软。
        """
        try:
            return self._detect_climax('buying', lookback_days)
        except (DataError, MissingFieldError, CalculationError, PatternDetectionError, PatternNotFoundError):
            raise
        except Exception as e:
            return self._handle_detection_error("BC", e)

    def detect_automatic_rally(self, lookback_days: int = 60) -> Dict:
        """
        检测自然反弹（Automatic Rally, AR）

        重构实现：代理调用 ClassicPatternDetector 的统一 AR 检测方法，实现 DRY。
        同时对返回结果进行完美包装，向下兼容旧接口的一切字段与格式。
        """
        try:
            sc_res = self.detect_climax_panic_selling(lookback_days)
            if not sc_res['detected']:
                # 优化 5: 若无典型暴量 SC，降级尝试寻找 SOT 作为备用 baseline
                sot_res = self.detect_stopping_of_transient(lookback_days)
                if sot_res.get('detected'):
                    sc_res = {
                        "detected": True,
                        "date": pd.to_datetime(sot_res["date"]),
                        "price": float(sot_res["close"]),
                        "type": "stopping_volume",
                        "confidence": 0.5
                    }
                    logger.info("SC未检测到，已成功通过 SOT 停止行为进行柔性基准线降级适配")
                else:
                    # 二级柔性降级：使用 lookback 窗口内的局部最低价 (Local Low) 作为 baseline
                    recent_df = self.data.tail(lookback_days)
                    if not recent_df.empty:
                        min_idx = recent_df['Low'].idxmin()
                        sc_res = {
                            "detected": True,
                            "date": min_idx,
                            "price": float(recent_df.loc[min_idx, 'Low']),
                            "type": "local_extreme_low",
                            "confidence": 0.4
                        }
                        logger.info(f"未检测到 SC 和 SOT，已降级使用近 {lookback_days} 日局部低点 (Local Low) 作为 AR 基准线")
                    else:
                        return {"detected": False, "reason": "No SC or fallback data found to baseline AR"}

            # 调用统一的底层 AR 检测逻辑
            ar_res = self.classic_detector.detect_automatic_reaction(sc_res)
            if not ar_res.get('detected'):
                return {"detected": False, "reason": "AR not detected by reversal detector"}

            sc_date = pd.to_datetime(sc_res['date'])
            sc_low = sc_res['price']

            ar_date = ar_res['date']
            ar_high = ar_res['price']
            rebound_pct = float(ar_res['rebound_pct']) * 100.0

            # 计算 ar_window_bars 兼容字段
            ar_window_bars = 3
            if ar_res.get('detection_layer') == '5d_extended':
                ar_window_bars = 5
            elif ar_res.get('detection_layer') in ('swing_high', '15d_extreme_fallback'):
                ar_window_bars = 15

            return {
                "detected": True,
                "sc_date": sc_date,
                "sc_low": float(sc_low),
                "ar_date": ar_date,
                "date": ar_date,
                "price": float(ar_high),
                "ar_high": float(ar_high),
                "rebound_pct": float(rebound_pct),
                "ar_window_bars": ar_window_bars,
                "confidence": min(100, max(0, (rebound_pct - 1) * 12))
            }
        except (DataError, MissingFieldError, CalculationError, PatternDetectionError, PatternNotFoundError):
            raise
        except Exception as e:
            return self._handle_detection_error("AR", e)

    def detect_preliminary_support(self, lookback_days: int = 90) -> Dict:
        """
        检测初次支撑（Preliminary Support, PS）
        """
        return self.ps_detector.detect(lookback_days)

    def detect_preliminary_supply(self, lookback_days: int = 90) -> Dict:
        """
        检测初次供应（Preliminary Supply, PSY）
        """
        return self.psy_detector.detect(lookback_days)

    def _validate_ps_sc_sequence(self, ps_res: Dict, sc_res: Dict) -> Tuple[bool, str]:
        """
        验证PS和SC是否符合威科夫理论的时间序列

        Args:
            ps_res: PS检测结果
            sc_res: SC检测结果

        Returns:
            (是否有效, 原因说明)

        规则：
        1. PS日期必须早于SC日期
        2. PS价格应该高于SC低点（PS是支撑位，SC应该跌破PS）
        3. 时间差应该在合理范围内（PS到SC通常5-60天）
        """
        if not ps_res.get('detected') or not sc_res.get('detected'):
            return False, "PS或SC未检测到"

        # 检查日期顺序
        ps_date = self._parse_date(ps_res.get('ps_date') or ps_res.get('date'))
        sc_date = self._parse_date(sc_res.get('date'))

        if not ps_date or not sc_date:
            return False, "无法解析PS或SC日期"

        # PS必须在SC之前
        if ps_date >= sc_date:
            logger.warning(f"PS日期{ps_date}晚于或等于SC日期{sc_date}，不符合Phase A序列")
            return False, f"PS日期({ps_date})晚于SC日期({sc_date})"

        # 检查价格关系：PS价格应该高于SC低点
        ps_price = ps_res.get('ps_price') or ps_res.get('price')
        sc_price = sc_res.get('price')  # SC的价格就是低点

        if ps_price and sc_price:
            # PS价格应该高于SC低点
            # PS是支撑位，SC应该跌破PS
            # 优化 6: 修正反向偏置容差。PS必须是高于或等于SC恐慌抛售低点，仅允许 1% 极端毛刺选定容差
            if ps_price < sc_price * 0.99:
                logger.warning(
                    f"PS价格{ps_price}低于SC价格{sc_price}，"
                    f"不符合支撑位在上、创新低在下的时序逻辑"
                )
                return False, f"PS价格({ps_price})低于SC价格({sc_price})，违反承接时序"

        # 检查时间差
        time_diff = (sc_date - ps_date).days
        if time_diff > 90:  # 超过90天太长了
            logger.warning(f"PS到SC时间差{time_diff}天过长，可能不是同一个Phase A")
            return False, f"PS到SC时间差({time_diff}天)过长"

        return True, "PS与SC时序一致"

    def _validate_psy_bc_sequence(self, psy_res: Dict, bc_res: Dict) -> Tuple[bool, str]:
        """
        验证 PSY (初次供应) 和 BC (买入高潮) 的时序逻辑
        """
        if not psy_res.get('detected') or not bc_res.get('detected'):
            return False, "缺少PSY或BC证据"

        psy_date = self._parse_date(psy_res.get('date'))
        bc_date = self._parse_date(bc_res.get('date'))

        if psy_date is None or bc_date is None:
            return False, "日期解析失败"

        if psy_date > bc_date:
            return False, "时序错误：PSY出现在BC之后"

        time_diff = (bc_date - psy_date).days
        if time_diff > 60:
            return False, f"PSY到BC时间差({time_diff}天)过长"

        return True, "PSY与BC时序一致"

    def _parse_date(self, date_val):
        """统一日期解析 — 委托至共享 TypeConverter"""
        return TypeConverter.parse_date_naive(date_val)

    def analyze_phase_a_evidence(self, events: Any = None) -> Dict:
        """
        综合分析 Phase A 的核心证据 (吸筹或派发)
        """
        try:
            acc_res = self._analyze_accumulation_phase_a(events)
            dist_res = self._analyze_distribution_phase_a(events)

            # 返回证据权重更高的一个
            if dist_res['detected_weight'] > acc_res['detected_weight']:
                dist_res['direction'] = 'distribution'
                return dist_res
            else:
                acc_res['direction'] = 'accumulation'
                return acc_res
        except Exception as e:
            logger.exception(f"Phase A证据分析失败: {e}")
            return {"phase_a_confirmed": False, "strength": "none", "error": str(e)}

    def _analyze_accumulation_phase_a(self, events: Any = None) -> Dict:
        """分析吸筹阶段 A 的证据 (PS -> SC -> AR -> ST)"""
        if events is not None:
            if hasattr(events, 'model_dump'):
                events_dict = events.model_dump()
            elif hasattr(events, 'dict'):
                events_dict = events.dict()
            elif isinstance(events, dict):
                events_dict = events
            else:
                events_dict = None
        else:
            events_dict = None

        if events_dict is not None:
            raw_climax = events_dict.get('climax') or {}
            if raw_climax.get('detected') and raw_climax.get('type') == 'selling_climax':
                sc_res = raw_climax
            else:
                sc_res = {'detected': False}

            ps_res = events_dict.get('preliminary_support') or {'detected': False}
            ar_res = events_dict.get('automatic_reaction') or {'detected': False}
            st_res = events_dict.get('secondary_test') or {'detected': False}
        else:
            sc_res = self.detect_climax_panic_selling()
            ps_res = self.detect_preliminary_support()
            ar_res = self.detect_automatic_rally()
            st_res = self.detect_secondary_test(sc_res, ar_res)

        ps_sc_valid, ps_sc_reason = self._validate_ps_sc_sequence(ps_res, sc_res)

        def _check_detected(res: dict, required_fields: list) -> bool:
            return bool(res.get("detected")) and all(k in res for k in required_fields)

        checks = []
        ps_detected = _check_detected(ps_res, ['ps_price'])
        sc_detected = _check_detected(sc_res, ['date', 'price'])

        checks.append({'id': 'PS', 'detected': ps_detected, 'weight': 2 if ps_sc_valid else 1})
        checks.append({'id': 'SC', 'detected': sc_detected, 'weight': 3 if ps_sc_valid else 2})
        checks.append({'id': 'AR', 'detected': _check_detected(ar_res, ['date', 'price']), 'weight': 2})
        checks.append({'id': 'ST', 'detected': _check_detected(st_res, ['date', 'price']), 'weight': 1})

        detected_weight = sum(c['weight'] for c in checks if c['detected'])
        strength = "strong" if detected_weight >= 4 else ("weak" if detected_weight >= 2 else "none")

        return {
            "phase_a_confirmed": strength != "none",
            "strength": strength,
            "detected_weight": detected_weight,
            "evidence": {"ps": ps_res, "sc": sc_res, "ar": ar_res, "st": st_res}
        }

    def _analyze_distribution_phase_a(self, events: Any = None) -> Dict:
        """分析派发阶段 A 的证据 (PSY -> BC -> AR -> ST)"""
        if events is not None:
            if hasattr(events, 'model_dump'):
                events_dict = events.model_dump()
            elif hasattr(events, 'dict'):
                events_dict = events.dict()
            elif isinstance(events, dict):
                events_dict = events
            else:
                events_dict = None
        else:
            events_dict = None

        if events_dict is not None:
            raw_climax = events_dict.get('climax') or {}
            if raw_climax.get('detected') and raw_climax.get('type') == 'buying_climax':
                bc_res = raw_climax
            else:
                bc_res = {'detected': False}

            psy_res = events_dict.get('preliminary_supply') or {'detected': False}
            ar_res = events_dict.get('automatic_reaction') or {'detected': False}
            st_res = events_dict.get('secondary_test') or {'detected': False}
        else:
            bc_res = self.detect_climax_buying()
            psy_res = self.detect_preliminary_supply()
            ar_res = self.detect_automatic_reaction(bc_res)
            st_res = self.detect_secondary_test(bc_res, ar_res)

        psy_bc_valid, psy_bc_reason = self._validate_psy_bc_sequence(psy_res, bc_res)

        def _check_detected(res: dict, required_fields: list) -> bool:
            return bool(res.get("detected")) and all(k in res for k in required_fields)

        checks = []
        psy_detected = _check_detected(psy_res, ['price'])
        bc_detected = _check_detected(bc_res, ['date', 'price'])

        checks.append({'id': 'PSY', 'detected': psy_detected, 'weight': 2 if psy_bc_valid else 1})
        checks.append({'id': 'BC', 'detected': bc_detected, 'weight': 3 if psy_bc_valid else 2})
        checks.append({'id': 'AR', 'detected': _check_detected(ar_res, ['date', 'price']), 'weight': 2})
        checks.append({'id': 'ST', 'detected': _check_detected(st_res, ['date', 'price']), 'weight': 1})

        detected_weight = sum(c['weight'] for c in checks if c['detected'])
        strength = "strong" if detected_weight >= 4 else ("weak" if detected_weight >= 2 else "none")

        return {
            "phase_a_confirmed": strength != "none",
            "strength": strength,
            "detected_weight": detected_weight,
            "evidence": {"psy": psy_res, "bc": bc_res, "ar": ar_res, "st": st_res}
        }

    def detect_stopping_of_transient(self, lookback_days: int = 20) -> Dict:
        """
        检测停止行为（Stopping of Transient, SOT）

        注意：使用动态rolling mean避免前瞻偏差
        每一天的基准成交量只使用该天及之前的数据计算
        """
        try:
            # 检查必要字段
            required_cols = {'Close', 'Open', 'Volume', 'High', 'Low'}
            missing = required_cols - set(self.data.columns)
            if missing:
                raise MissingFieldError(f"缺失必要列: {missing}")

            recent_data = self.data.tail(lookback_days)
            if len(recent_data) < 10:
                return {"detected": False, "reason": "Insufficient data"}

            # 使用动态计算的rolling mean，避免前瞻偏差
            # 对于每一天，只使用该天及之前的数据计算平均成交量
            volume_series = self.data['Volume']

            for idx in range(len(recent_data) - 5, len(recent_data)):
                row = recent_data.iloc[idx]

                # 优化 2: 安全获取全局整数索引，避免 len(self.data) < lookback_days 时的负切片越界
                try:
                    global_idx = self.data.index.get_loc(row.name)
                except (KeyError, ValueError):
                    global_idx = len(self.data) - len(recent_data) + idx

                if global_idx < 0 or global_idx >= len(self.data):
                    continue

                # 动态计算：只使用当前行及之前的数据
                # 使用20日窗口，但确保不使用未来数据
                window_start = max(0, global_idx - 19)  # 20日窗口
                window_data = volume_series.iloc[window_start:global_idx + 1]
                avg_vol = window_data.mean() if len(window_data) > 0 else 0

                body = abs(row['Close'] - row['Open'])
                range_size = row['High'] - row['Low']
                if range_size == 0: continue

                vol_ratio = row['Volume'] / avg_vol if avg_vol > 0 else 0
                body_ratio = body / range_size

                # 动态阈值：基于ATR适配
                sot_vol_threshold = self._get_dynamic_volume_threshold(1.3)
                sot_body_threshold = 0.3  # 实体占比阈值保持固定，因为这是形态特征而非波动率特征

                if vol_ratio > sot_vol_threshold and body_ratio < sot_body_threshold:
                    return {
                        "detected": True,
                        "date": row.name.strftime("%Y-%m-%d"),
                        "volume_ratio": float(vol_ratio),
                        "body_ratio": float(body_ratio),
                        "close": float(row['Close']),
                        "volume": float(row['Volume']),
                        "confidence": min(100, vol_ratio * 40),
                        "avg_vol_window": int(len(window_data)),
                        "note": "使用动态rolling mean避免前瞻偏差",
                        "dynamic_thresholds": {
                            "vol_threshold": sot_vol_threshold,
                            "body_threshold": sot_body_threshold,
                            "atr_pct": self._atr_pct
                        }
                    }
            return {"detected": False, "reason": "No SOT pattern found"}
        except (DataError, MissingFieldError, CalculationError, PatternDetectionError, PatternNotFoundError):
            raise
        except Exception as e:
            return self._handle_detection_error("SOT", e)

    def detect_absorption(self, lookback_days: int = 15, trading_range: Dict = None) -> Dict:
        """
        检测独立的“吸收（Absorption）”行为
        理论依据：大卫·维斯极度强调在阻力位（Creek）下方的吸收行为。
        即价格紧贴阻力位，连续高量但拒绝显著回落，这是 JOC 之前最强的看涨前置信号。
        """
        try:
            # 检查必要字段
            required_cols = {'Close', 'Open', 'Volume', 'High', 'Low'}
            missing = required_cols - set(self.data.columns)
            if missing:
                raise MissingFieldError(f"缺失必要列: {missing}")

            if self.data is None or len(self.data) < 20:
                return {"detected": False, "reason": "insufficient_data"}

            if trading_range is None:
                trading_range = self.detect_trading_range()

            #  优化 3: 级联联动：若 TR 已失效，吸收行为失去参考系，跳过检测防止高位滞涨误判
            if trading_range and trading_range.get('invalidated_tr') == True:
                return {
                    "detected": False,
                    "reason": "trading_range_invalidated",
                    "note": "⚠️ 交易区间(TR)已失效，吸收行为失去参考系，跳过检测防止高位滞涨误判"
                }

            # 1. 寻找 Creek 水位 (阻力位)
            if trading_range and trading_range.get("high") is not None:
                creek_level = float(trading_range["high"])
            else:
                # 降级：使用近60日的高点作为 Creek 水位
                creek_level = float(self.data['High'].tail(60).max())

            df = self.data.tail(lookback_days).copy()
            n = len(df)
            if n < 3:
                return {"detected": False, "reason": "insufficient_lookback"}

            closes = df['Close'].values
            highs = df['High'].values
            lows = df['Low'].values
            volumes = df['Volume'].values

            # 计算 20日均量与ATR
            vol_ma20_s = self.data['Volume_MA20'].values if 'Volume_MA20' in self.data.columns else self.data['Volume'].rolling(20).mean().values
            atr_s = self.data['ATR'].values if 'ATR' in self.data.columns else (self.data['High'] - self.data['Low']).rolling(14).mean().values

            vol_ma = vol_ma20_s[-n:]
            atr = atr_s[-n:]

            # 我们要寻找是否有连续至少3天符合吸收特征的 K 线序列
            # 优化 3: 限制 Creek 阻力下方的宽容度区间，防止突破暴涨后判定为吸收行为
            is_near_creek = (highs > creek_level * 0.95) & (closes < creek_level * 1.03)
            is_high_volume = np.zeros(n, dtype=bool)
            is_narrow_range = np.zeros(n, dtype=bool)
            is_high_close = np.zeros(n, dtype=bool)

            for i in range(n):
                v_ma = vol_ma[i] if not pd.isna(vol_ma[i]) else volumes[i]
                a_val = atr[i] if not pd.isna(atr[i]) else (highs[i] - lows[i])

                is_high_volume[i] = volumes[i] > v_ma * 1.3  # 放宽到 1.3倍均量
                is_narrow_range[i] = (highs[i] - lows[i]) < a_val * 0.85  # 窄幅，小于0.85倍ATR
                is_high_close[i] = closes[i] >= (highs[i] + lows[i]) / 2.0  # 收盘中位以上

            is_absorption_bar = is_near_creek & is_high_volume & is_narrow_range & is_high_close

            # 寻找是否有连续 >= 3 天的 is_absorption_bar
            consecutive_count = 0
            best_streak = 0
            end_idx = -1

            for i in range(n):
                if is_absorption_bar[i]:
                    consecutive_count += 1
                    if consecutive_count > best_streak:
                        best_streak = consecutive_count
                        end_idx = i
                else:
                    consecutive_count = 0

            if best_streak >= 3:
                absorption_dates = [df.index[j] for j in range(end_idx - best_streak + 1, end_idx + 1)]
                avg_vol_multiplier = float(np.mean(volumes[end_idx - best_streak + 1:end_idx + 1] / vol_ma[end_idx - best_streak + 1:end_idx + 1]))

                return {
                    "detected": True,
                    "creek_level": creek_level,
                    "consecutive_days": best_streak,
                    "dates": [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in absorption_dates],
                    "avg_volume_ratio": round(avg_vol_multiplier, 2),
                    "confidence": float(min(1.0, 0.5 + (best_streak - 3) * 0.15 + (avg_vol_multiplier - 1.5) * 0.2)),
                    "description": f"🎯 发现主力【蓄势吸收】特征：在阻力位 {creek_level:.2f} 下方连续 {best_streak} 天放量窄幅横盘，收盘强劲，说明所有抛盘已被多头主动蚕食吸收，即将向上跃过小溪 (JOC)"
                }

            return {"detected": False, "reason": "no_consecutive_absorption_sequence"}
        except (DataError, MissingFieldError, CalculationError, PatternDetectionError, PatternNotFoundError):
            raise
        except Exception as e:
            return self._handle_detection_error("Absorption", e)
