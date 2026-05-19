import pandas as pd
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
from ..exceptions import PatternDetectionError, AnalysisError
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

    def detect_joc(self, lookback: int = 90) -> Dict:
        # 联动逻辑：如遇超买刺穿+放量，则抑制普通 JOC，改报趋势耗尽
        channel_res = self.detect_channels()
        ob_os = channel_res.get('overbought_oversold')
        if ob_os and ob_os['status'] == 'overbought':
            return {
                'detected': False,
                'reason': 'suppressed_by_overbought_climax',
                'channel_warning': ob_os['message']
            }
        #  缺隗6修复：传递TR数据，让子检测器能用TR上沿作为Creek水位
        tr = self.range_detector.detect()
        joc_res = self.classic_detector.detect_joc(lookback, trading_range=tr)
        
        # 联动“吸收”检测，增强置信度
        if joc_res.get('detected'):
            absorption_res = self.detect_absorption()
            if absorption_res.get('detected'):
                joc_res['absorption_confirmed'] = True
                joc_res['confidence'] = float(min(1.0, joc_res.get('confidence', 0.7) * 1.25))
                joc_res['description'] = joc_res.get('description', '') + f" | 🌟 [主力强力吸收确认] 突破前有 {absorption_res['consecutive_days']} 天完美的蓄势吸收，此突破极大概率为真实突破 (JOC)"
        return joc_res

    def detect_fti(self, lookback: int = 90) -> Dict:
        # 联动逻辑：如遇超卖刺穿+放量，则抑制普通 FTI，改报趋势耗尽
        channel_res = self.detect_channels()
        ob_os = channel_res.get('overbought_oversold')
        if ob_os and ob_os['status'] == 'oversold':
            return {
                'detected': False,
                'reason': 'suppressed_by_oversold_climax',
                'channel_warning': ob_os['message']
            }
        return self.classic_detector.detect_fti(lookback)

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
        evidence_analysis = self.analyze_phase_a_evidence()

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
        return self.sw_detector.detect_lps(spring_res=spring_res, trading_range=trading_range)

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

    # ============================================================
    # 孟洪涛核心证据检测（Core Evidence Detection）
    # ============================================================

    def detect_climax_panic_selling(self, lookback_days: int = 60) -> Dict:
        """
        检测恐慌性抛售（Selling Climax, SC）
        理论依据：主跌段末端，成交量极度放大，价差扩大，通常伴随长下影线。
        
        使用动态阈值：基于ATR适配不同波动率的资产
        """
        try:
            recent_data = self.data.tail(lookback_days)
            # 不直接取最低点，而是寻找符合高潮特征的 Bar
            vol_ma = recent_data['Volume_MA20'] if 'Volume_MA20' in recent_data.columns else recent_data['Volume'].rolling(20).mean()
            
            # 计算价差 ATR 参考
            high_low_range = recent_data['High'] - recent_data['Low']
            avg_range = high_low_range.rolling(20).mean()
            
            # 动态阈值：基于ATR适配
            # 威科夫理论：SC必须伴随巨幅放量，通常为均量2倍以上
            #  修复 P0-1: SC 至少需要 2.5x 巨量，fallback 也需要 2.5x
            climax_vol_threshold = self._get_dynamic_volume_threshold(max(self.thresholds.VOLUME_CONFIRMATION['strong'], 2.5))
            climax_range_threshold = self._get_dynamic_volume_threshold(1.8)
            fallback_vol_threshold = self._get_dynamic_volume_threshold(2.5)  #  取消低量 fallback，强制 2.5x
            
            # 高潮候选者：成交量 > 动态阈值倍均量 且 价差 > 动态阈值倍均价差
            candidates = recent_data[
                (recent_data['Volume'] > vol_ma * climax_vol_threshold) & 
                (high_low_range > avg_range * climax_range_threshold) &
                (recent_data['Close'] < recent_data['Open']) # 必须是阴线或低收
            ]
            
            if candidates.empty:
                # 降级：如果找不到完美高潮，找最低点且量能尚可的
                min_idx = recent_data['Low'].idxmin()
                min_row = recent_data.loc[min_idx]
                vol_ratio = min_row['Volume'] / vol_ma.loc[min_idx] if vol_ma.loc[min_idx] > 0 else 1.0
                if vol_ratio > fallback_vol_threshold:
                    is_climax = True
                    sc_idx = min_idx
                else:
                    return {"detected": False, "reason": "No climactic volume found at lows"}
            else:
                # 取最后一个符合条件的作为 SC (通常 SC 后会有 AR)
                sc_idx = candidates.index[-1]
                is_climax = True

            sc_row = recent_data.loc[sc_idx]
            vol_ratio = sc_row['Volume'] / vol_ma.loc[sc_idx]

            # 计算当时是否是 squat bar (蹲坐柱)
            sc_vol = sc_row['Volume']
            sc_spread = sc_row['High'] - sc_row['Low']
            sc_vol_ma20 = vol_ma.loc[sc_idx]
            sc_spread_ma20 = avg_range.loc[sc_idx] if not pd.isna(avg_range.loc[sc_idx]) else sc_spread
            
            is_sc_squat = (sc_vol > sc_vol_ma20 * 2.0) and (sc_spread < sc_spread_ma20 * 0.8)
            sc_squat_dir = "none"
            if is_sc_squat:
                sc_squat_dir = "bullish" if sc_row['Close'] >= (sc_row['High'] + sc_row['Low']) / 2.0 else "bearish"

            #  修复 P0-2: 使用新的 confidence 计算方法，基于量比分层
            sc_close_pos = (sc_row['Close'] - sc_row['Low']) / max(sc_row['High'] - sc_row['Low'], 1e-9)
            base_confidence = self._calculate_climax_confidence(vol_ratio, sc_close_pos)

            #  修复 P2-1: Effort vs Result 验证
            price_progress = (sc_row['Close'] - sc_row['Open']) / sc_row['Open']
            is_valid, penalty, warning = self._validate_climax_effort_result(vol_ratio, price_progress, sc_close_pos)

            # 联动 Squat Bar：如果检测到看涨蹲坐柱，豁免背离惩罚并提升置信度
            if is_sc_squat and sc_squat_dir == "bullish":
                is_valid = True
                penalty = 1.0  # 豁免惩罚
                base_confidence = min(1.0, base_confidence * 1.15)
                logger.info("[SC 蹲坐柱联动] 检测到看涨蹲坐柱作为SC，豁免背离惩罚并提升置信度")

            if warning and not (is_sc_squat and sc_squat_dir == "bullish"):
                logger.warning(f"[SC Effort vs Result] {warning}")

            confidence = base_confidence * penalty

            result = {
                "detected": is_climax,
                "date": sc_idx, # 保持 Timestamp 类型以供其他检测器使用
                "price": float(sc_row['Low']),
                "volume": float(sc_row['Volume']),
                "type": "selling_climax",
                "volume_ratio": float(vol_ratio),
                "confidence": float(confidence)
            }
            # P1 修复：增加 AR 确认逻辑
            self.classic_detector.reversal._verify_climax_confirmation(result)
            return result
        except (KeyError, ValueError, TypeError) as e:
            logger.exception(f"SC检测失败: {e}")
            return {"detected": False, "error": str(e)}
        except Exception as e:
            logger.exception(f"SC检测失败: 未知异常: {e}")
            raise PatternDetectionError("SC", f"未知异常: {e}") from e

    def detect_climax_buying(self, lookback_days: int = 60) -> Dict:
        """
        检测买入高潮（Buying Climax, BC）
        理论依据：主升段末端，成交量异常放大，价格创阶段新高，但收盘表现疲软（长上影线或收盘位置偏低），代表需求被庞大的派发供应吸收。
        使用动态阈值：基于ATR适配不同波动率的资产
        """
        try:
            recent_data = self.data.tail(lookback_days)
            vol_ma = recent_data['Volume_MA20'] if 'Volume_MA20' in recent_data.columns else recent_data['Volume'].rolling(20).mean()
            
            # 动态阈值
            #  修复 P0-1: BC 至少需要 2.5x 巨量，fallback 也需要 2.5x
            climax_vol_threshold = self._get_dynamic_volume_threshold(max(self.thresholds.VOLUME_CONFIRMATION['strong'], 2.5))
            fallback_vol_threshold = self._get_dynamic_volume_threshold(2.5)  #  取消低量 fallback，强制 2.5x
            
            # 计算收盘位置分位和上影线比例
            range_size = recent_data['High'] - recent_data['Low']
            avg_range = range_size.rolling(20).mean()
            close_pos = (recent_data['Close'] - recent_data['Low']) / range_size.replace(0, 1e-9)
            upper_shadow = recent_data['High'] - recent_data[['Open', 'Close']].max(axis=1)
            upper_shadow_ratio = upper_shadow / range_size.replace(0, 1e-9)
            
            # 高潮候选者：成交量大 且 (收盘偏低 或 长上影线) 且 必须是阳线或高开(可选，主要是放量冲高回落)
            candidates = recent_data[
                (recent_data['Volume'] > vol_ma * climax_vol_threshold) & 
                ((close_pos < 0.5) | (upper_shadow_ratio > 0.4))
            ]
            
            if candidates.empty:
                # 降级：找最高点且量能尚可的
                max_idx = recent_data['High'].idxmax()
                max_row = recent_data.loc[max_idx]
                vol_ratio = max_row['Volume'] / vol_ma.loc[max_idx] if vol_ma.loc[max_idx] > 0 else 1.0
                # 验证最高点是否符合偏弱收盘
                max_close_pos = (max_row['Close'] - max_row['Low']) / max(max_row['High'] - max_row['Low'], 1e-9)
                max_upper_shadow = (max_row['High'] - max(max_row['Open'], max_row['Close'])) / max(max_row['High'] - max_row['Low'], 1e-9)
                
                if vol_ratio > fallback_vol_threshold and (max_close_pos < 0.6 or max_upper_shadow > 0.3):
                    is_climax = True
                    bc_idx = max_idx
                else:
                    return {"detected": False, "reason": "No climactic volume found at highs with poor close"}
            else:
                # 取最后一个符合条件的作为 BC
                bc_idx = candidates.index[-1]
                is_climax = True

            bc_row = recent_data.loc[bc_idx]
            vol_ratio = bc_row['Volume'] / vol_ma.loc[bc_idx]

            # 计算当时是否是 squat bar (蹲坐柱)
            bc_vol = bc_row['Volume']
            bc_spread = bc_row['High'] - bc_row['Low']
            bc_vol_ma20 = vol_ma.loc[bc_idx]
            bc_spread_ma20 = avg_range.loc[bc_idx] if not pd.isna(avg_range.loc[bc_idx]) else bc_spread
            
            is_bc_squat = (bc_vol > bc_vol_ma20 * 2.0) and (bc_spread < bc_spread_ma20 * 0.8)
            bc_squat_dir = "none"
            if is_bc_squat:
                bc_squat_dir = "bullish" if bc_row['Close'] >= (bc_row['High'] + bc_row['Low']) / 2.0 else "bearish"

            #  修复 P0-2: 使用新的 confidence 计算方法，基于量比分层
            bc_close_pos = (bc_row['Close'] - bc_row['Low']) / max(bc_row['High'] - bc_row['Low'], 1e-9)
            base_confidence = self._calculate_climax_confidence(vol_ratio, bc_close_pos)

            #  修复 P2-1: Effort vs Result 验证
            price_progress = (bc_row['Close'] - bc_row['Open']) / bc_row['Open']
            is_valid, penalty, warning = self._validate_climax_effort_result(vol_ratio, price_progress, bc_close_pos)

            # 联动 Squat Bar：如果检测到看跌蹲坐柱，豁免背离惩罚并提升置信度
            if is_bc_squat and bc_squat_dir == "bearish":
                is_valid = True
                penalty = 1.0  # 豁免惩罚
                base_confidence = min(1.0, base_confidence * 1.15)
                logger.info("[BC 蹲坐柱联动] 检测到看跌蹲坐柱作为BC，豁免背离惩罚并提升置信度")

            if warning and not (is_bc_squat and bc_squat_dir == "bearish"):
                logger.warning(f"[BC Effort vs Result] {warning}")

            confidence = base_confidence * penalty

            result = {
                "detected": is_climax,
                "date": bc_idx,
                "price": float(bc_row['High']),
                "volume": float(bc_row['Volume']),
                "type": "buying_climax",
                "volume_ratio": float(vol_ratio),
                "confidence": float(confidence)
            }
            # P1 修复：增加回落确认逻辑
            self.classic_detector.reversal._verify_climax_confirmation(result)
            return result
        except (KeyError, ValueError, TypeError) as e:
            logger.exception(f"BC检测失败: {e}")
            return {"detected": False, "error": str(e)}
        except Exception as e:
            logger.exception(f"BC检测失败: 未知异常: {e}")
            raise PatternDetectionError("BC", f"未知异常: {e}") from e

    def detect_automatic_rally(self, lookback_days: int = 60) -> Dict:
        """
        检测自然反弹（Automatic Rally, AR）
        
        孟洪涛《新威科夫操盘法》定义：
        - AR 是 SC 后 **立即** 发生的剧烈反弹（1-3 根K线内）
        - 不是数周后任意时间点的最高价
        - AR 极值通常形成 TR 上沿
        """
        try:
            sc_res = self.detect_climax_panic_selling(60)
            if not sc_res['detected']:
                return {"detected": False, "reason": "No SC found to baseline AR"}
            
            sc_date = pd.to_datetime(sc_res['date'])
            sc_low = sc_res['price']

            after_sc = self.data.loc[self.data.index > sc_date]
            if len(after_sc) < 2:
                return {"detected": False, "reason": "Insufficient data after SC"}

            # 威科夫 AR：只在 SC 后 1-3 根K线内寻找反弹高点
            ar_window = after_sc.head(3)
            
            # 放宽条件：如果前3根没有明显反弹，扩展到5根
            ar_high = ar_window['High'].max()
            ar_idx = ar_window['High'].idxmax()

            # 修正：反弹起点应为 SC 当日的收盘价或实体中位值，而非最低价 (P1 #2.1)
            sc_bar = self.data.loc[sc_date]
            baseline = (sc_bar['Open'] + sc_bar['Close']) / 2
            
            rebound_pct = (ar_high - baseline) / baseline * 100
            
            # 威科夫理论中，AR 是剧烈反弹（通常 > 3%）
            is_ar = rebound_pct > 3

            # 扩展搜索：如果 3 根K线内未找到充分反弹，扩展到 5 根
            if not is_ar:
                ar_window_5 = after_sc.head(5)
                ar_high_5 = ar_window_5['High'].max()
                ar_idx_5 = ar_window_5['High'].idxmax()
                rebound_pct_5 = (ar_high_5 - baseline) / baseline * 100
                if rebound_pct_5 > 3:
                    ar_high = ar_high_5
                    ar_idx = ar_idx_5
                    rebound_pct = rebound_pct_5
                    is_ar = True

            return {
                "detected": is_ar,
                "sc_date": sc_date,
                "sc_low": float(sc_low),
                "ar_date": ar_idx,
                "date": ar_idx,
                "price": float(ar_high),
                "ar_high": float(ar_high),
                "rebound_pct": float(rebound_pct),
                "ar_window_bars": 3 if ar_idx in after_sc.head(3).index else 5,
                "confidence": min(100, max(0, (rebound_pct - 1) * 12)) if is_ar else 0
            }
        except (KeyError, ValueError, TypeError) as e:
            logger.exception(f"AR检测失败: {e}")
            return {"detected": False, "error": str(e)}
        except Exception as e:
            logger.exception(f"AR检测失败: 未知异常: {e}")
            raise PatternDetectionError("AR", f"未知异常: {e}") from e

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
            if ps_price < sc_price * 0.95:  # 允许5%容差
                logger.warning(
                    f"PS价格{ps_price}远低于SC价格{sc_price}，"
                    f"不符合Phase A逻辑（PS应该是支撑位，SC应跌破PS）"
                )
                return False, f"PS价格({ps_price})低于SC价格({sc_price})，时序混乱"

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

    def analyze_phase_a_evidence(self) -> Dict:
        """
        综合分析 Phase A 的核心证据 (吸筹或派发)
        """
        try:
            acc_res = self._analyze_accumulation_phase_a()
            dist_res = self._analyze_distribution_phase_a()

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

    def _analyze_accumulation_phase_a(self) -> Dict:
        """分析吸筹阶段 A 的证据 (PS -> SC -> AR -> ST)"""
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

    def _analyze_distribution_phase_a(self) -> Dict:
        """分析派发阶段 A 的证据 (PSY -> BC -> AR -> ST)"""
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
            recent_data = self.data.tail(lookback_days)
            if len(recent_data) < 10:
                return {"detected": False, "reason": "Insufficient data"}
            
            # 使用动态计算的rolling mean，避免前瞻偏差
            # 对于每一天，只使用该天及之前的数据计算平均成交量
            volume_series = self.data['Volume']
            
            for idx in range(len(recent_data) - 5, len(recent_data)):
                row = recent_data.iloc[idx]
                global_idx = len(self.data) - lookback_days + idx
                
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
        except (KeyError, ValueError, TypeError) as e:
            logger.exception(f"SOT检测失败: {e}")
            return {"detected": False, "error": str(e)}
        except Exception as e:
            logger.exception(f"SOT检测失败: 未知异常: {e}")
            raise PatternDetectionError("SOT", f"未知异常: {e}") from e

    def detect_absorption(self, lookback_days: int = 15) -> Dict:
        """
        检测独立的“吸收（Absorption）”行为
        理论依据：大卫·维斯极度强调在阻力位（Creek）下方的吸收行为。
        即价格紧贴阻力位，连续高量但拒绝显著回落，这是 JOC 之前最强的看涨前置信号。
        """
        try:
            if self.data is None or len(self.data) < 20:
                return {"detected": False, "reason": "insufficient_data"}

            # 1. 寻找 Creek 水位 (阻力位)
            tr = self.range_detector.detect()
            if tr.get("is_consolidation") and tr.get("high") is not None:
                creek_level = float(tr["high"])
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
            import numpy as np
            vol_ma20_s = self.data['Volume_MA20'].values if 'Volume_MA20' in self.data.columns else self.data['Volume'].rolling(20).mean().values
            atr_s = self.data['ATR'].values if 'ATR' in self.data.columns else (self.data['High'] - self.data['Low']).rolling(14).mean().values
            
            vol_ma = vol_ma20_s[-n:]
            atr = atr_s[-n:]

            # 我们要寻找是否有连续至少3天符合吸收特征的 K 线序列
            is_near_creek = highs > creek_level * 0.95
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
        except Exception as e:
            logger.exception(f"吸收检测失败: {e}")
            return {"detected": False, "error": str(e)}

