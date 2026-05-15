import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from .detectors.trading_range_detector import TradingRangeDetector
from .detectors.classic_pattern_detector import ClassicPatternDetector
from .detectors.strength_weakness_detector import StrengthWeaknessDetector
from .detectors.phase_identifier import PhaseIdentifier
from .detectors.channel_detector import ChannelDetector
from .meng_pattern_enhancer import MengPatternEnhancer
from .phase_coordinator import PhaseCoordinator
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

        # 初始化孟洪涛增强检测器
        self.meng_enhancer = MengPatternEnhancer(data, config, self.thresholds, indicator_cache=self._indicator_cache)

        # 初始化阶段协调器（负责事件收集和阶段验证）
        self.phase_coordinator = PhaseCoordinator(self)

        # 注册所有子检测器以支持统一接口调用
        self.all_detectors = [
            self.range_detector, self.classic_detector,
            self.sw_detector, self.phase_identifier,
            self.meng_enhancer, self.channel_detector
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

    def detect_sow(self, window: int = 40) -> Dict:
        return self.sw_detector.detect_sow(window)

    def detect_sos_variants(self) -> Dict:
        return self.sw_detector.detect_sos_variants()

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
        return self.classic_detector.detect_joc(lookback, trading_range=tr)

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
        phase_result['sequence_validation'] = events.get('sequence_validation', {})

        # 构建 events_detected（供 scoring 引擎使用）
        # 直接使用原始检测 dict，避免 Pydantic 丢弃 volume_ratio 等字段
        raw = events.get('_raw_events', {})
        events_detected = {k: v for k, v in raw.items()
                           if isinstance(v, dict) and v.get('detected')}
        phase_result['events_detected'] = events_detected

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
        """
        try:
            return self.meng_enhancer.detect_vsa_signals()
        except Exception as e:
            logger.exception(f"VSA检测失败: {e}")
            return {
                "no_supply": {"detected": False, "error": str(e)},
                "no_demand": {"detected": False, "error": str(e)},
                "stopping_vol": {"detected": False, "error": str(e)}
            }

    def detect_boring_zone(self) -> Dict:
        """检测枯燥区 (Boring Zone)"""
        return self.meng_enhancer.detect_boring_zone()

    def detect_dead_corner_breakout(self) -> Dict:
        """检测死角突破 (Dead Corner Breakout)"""
        return self.meng_enhancer.detect_dead_corner_breakout()

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

            #  修复 P0-2: 使用新的 confidence 计算方法，基于量比分层
            sc_close_pos = (sc_row['Close'] - sc_row['Low']) / max(sc_row['High'] - sc_row['Low'], 1e-9)
            base_confidence = self._calculate_climax_confidence(vol_ratio, sc_close_pos)

            #  修复 P2-1: Effort vs Result 验证
            price_progress = (sc_row['Close'] - sc_row['Open']) / sc_row['Open']
            is_valid, penalty, warning = self._validate_climax_effort_result(vol_ratio, price_progress, sc_close_pos)

            if warning:
                logger.warning(f"[SC Effort vs Result] {warning}")

            confidence = base_confidence * penalty

            return {
                "detected": is_climax,
                "date": sc_idx, # 保持 Timestamp 类型以供其他检测器使用
                "price": float(sc_row['Low']),
                "volume": float(sc_row['Volume']),
                "type": "selling_climax",
                "volume_ratio": float(vol_ratio),
                "confidence": float(confidence)
            }
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
            #  修复 P0-2: 使用新的 confidence 计算方法，基于量比分层
            bc_close_pos = (bc_row['Close'] - bc_row['Low']) / max(bc_row['High'] - bc_row['Low'], 1e-9)
            base_confidence = self._calculate_climax_confidence(vol_ratio, bc_close_pos)

            #  修复 P2-1: Effort vs Result 验证
            price_progress = (bc_row['Close'] - bc_row['Open']) / bc_row['Open']
            is_valid, penalty, warning = self._validate_climax_effort_result(vol_ratio, price_progress, bc_close_pos)

            if warning:
                logger.warning(f"[BC Effort vs Result] {warning}")

            confidence = base_confidence * penalty

            return {
                "detected": is_climax,
                "date": bc_idx,
                "price": float(bc_row['High']),
                "volume": float(bc_row['Volume']),
                "type": "buying_climax",
                "volume_ratio": float(vol_ratio),
                "confidence": float(confidence)
            }
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

    def _find_downtrend_start(self, data: pd.DataFrame) -> Optional[int]:
        """找到主跌段起点（价格跌破MA20的位置）"""
        ma20 = data['Close'].rolling(window=20).mean()
        downtrend_mask = data['Close'] < ma20
        if not downtrend_mask.any():
            return None
        for i in range(len(data)):
            if downtrend_mask.iloc[i]:
                return i
        return None

    def _evaluate_ps_candidate(self, current, prev, next_day, vol_ma,
                                 ps_vol_threshold, ps_vol_strong_threshold) -> Optional[Dict]:
        """评估单个K线是否为PS候选"""
        vol_ratio = current['Volume'] / vol_ma if vol_ma > 0 else 0
        vol_heavy = vol_ratio > ps_vol_threshold
        price_stabilized = (current['Close'] > prev['Close']) or (current['Close'] > current['Open'])
        body = abs(current['Close'] - current['Open'])
        lower_shadow = min(current['Open'], current['Close']) - current['Low']
        shadow_resistance = lower_shadow > body * 0.5 if body > 0 else lower_shadow > 0
        
        if not (vol_heavy and price_stabilized and shadow_resistance):
            return None
        
        confidence = 50
        if vol_ratio > ps_vol_strong_threshold:
            confidence += 15
        if current['Close'] > current['Open']:
            confidence += 10
        if lower_shadow > body:
            confidence += 10
        if next_day is not None and next_day['Close'] > current['Close']:
            confidence += 15
        
        return {
            'vol_ratio': float(vol_ratio),
            'lower_shadow_ratio': float(lower_shadow / (body + 0.001)),
            'confidence': min(100, confidence)
        }

    def _verify_ps_with_sc(self, data: pd.DataFrame, best_ps: Dict) -> Tuple[bool, Optional[float]]:
        """验证PS之后是否有SC（恐慌抛售）"""
        ps_idx = best_ps['idx']
        post_ps_data = data.iloc[ps_idx + 1:]
        for i in range(len(post_ps_data)):
            row = post_ps_data.iloc[i]
            if row['Low'] < best_ps['low']:
                vol_ma = row.get('Volume_MA20', data['Volume'].iloc[:ps_idx + i + 1].tail(20).mean())
                if row['Volume'] > vol_ma * 1.5:
                    return True, float(row['Low'])
        return False, None

    def detect_preliminary_support(self, lookback_days: int = 90) -> Dict:
        """
        检测初次支撑（Preliminary Support, PS）
        
        威科夫理论定义：
        - PS 是主跌段中的第一次抄底尝试，发生在 SC（恐慌抛售）之前
        - 特征：成交量放大 + 价格止跌/反弹 + 下影线抵抗
        时序关系：PS → SC → AR → ST
        """
        try:
            data = self.data.tail(lookback_days)
            if len(data) < 20:
                return {"detected": False, "reason": "Insufficient data"}
            
            downtrend_start = self._find_downtrend_start(data)
            if downtrend_start is None:
                return {"detected": False, "reason": "No downtrend found"}
            if downtrend_start >= len(data) - 5:
                return {"detected": False, "reason": "Downtrend too short"}
            
            ps_vol_threshold = self._get_dynamic_volume_threshold(1.2)
            ps_vol_strong_threshold = self._get_dynamic_volume_threshold(1.5)
            
            potential_ps = []
            downtrend_data = data.iloc[downtrend_start:]
            
            for i in range(2, len(downtrend_data) - 1):
                current = downtrend_data.iloc[i]
                prev = downtrend_data.iloc[i-1]
                next_day = downtrend_data.iloc[i+1] if i + 1 < len(downtrend_data) else None
                vol_ma = current.get('Volume_MA20', data['Volume'].iloc[:downtrend_start + i].tail(20).mean())
                
                candidate = self._evaluate_ps_candidate(
                    current, prev, next_day, vol_ma,
                    ps_vol_threshold, ps_vol_strong_threshold
                )
                if candidate:
                    candidate.update({
                        'idx': downtrend_start + i,
                        'date': data.index[downtrend_start + i],
                        'price': float(current['Close']),
                        'low': float(current['Low']),
                    })
                    potential_ps.append(candidate)
            
            if not potential_ps:
                return {"detected": False, "reason": "No PS pattern found in downtrend"}

            best_ps = max(potential_ps, key=lambda x: x['confidence'])
            sc_found, sc_price = self._verify_ps_with_sc(data, best_ps)

            return {
                "detected": True,
                "ps_date": best_ps['date'].strftime("%Y-%m-%d") if hasattr(best_ps['date'], 'strftime') else str(best_ps['date']),
                "ps_price": best_ps['price'],
                "ps_low": best_ps['low'],
                "vol_ratio": best_ps['vol_ratio'],
                "lower_shadow_ratio": best_ps['lower_shadow_ratio'],
                "confidence": best_ps['confidence'],
                "sc_confirmed_after": sc_found,
                "sc_price": sc_price,
                "theory": "PS是主跌段中的第一次抄底尝试，发生在SC之前"
            }
        except (KeyError, ValueError, TypeError) as e:
            logger.exception(f"PS检测失败: {e}")
            return {"detected": False, "error": str(e)}
        except Exception as e:
            logger.exception(f"PS检测失败: 未知异常: {e}")
            raise PatternDetectionError("PS", f"未知异常: {e}") from e

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

    def _parse_date(self, date_val):
        """统一日期解析 — 委托至共享 TypeConverter"""
        return TypeConverter.parse_date_naive(date_val)

    def analyze_phase_a_evidence(self) -> Dict:
        """
        综合分析 Phase A 的核心证据 (PS -> SC -> AR -> ST)
        """
        try:
            sc_res = self.detect_climax_panic_selling()
            ps_res = self.detect_preliminary_support()
            ar_res = self.detect_automatic_rally()
            st_res = self.detect_secondary_test(sc_res, ar_res)
            sot_res = self.detect_stopping_of_transient()
            spring_res = self.detect_spring_menhongtao()

            #  新增：PS/SC时序验证
            ps_sc_valid, ps_sc_reason = self._validate_ps_sc_sequence(ps_res, sc_res)

            # 检测+必要字段双重验证，确保与报告层显示一致
            def _check_detected(res: dict, required_fields: list) -> bool:
                return bool(res.get("detected")) and all(k in res for k in required_fields)

            #  修复：PS 和 SC 独立检测，时序验证作为质量修正而非开关
            # 威科夫理论：PS 和 SC 是独立事件，时序异常时各自仍可能有效
            checks = []

            ps_detected = _check_detected(ps_res, ['ps_price'])
            sc_detected = _check_detected(sc_res, ['date', 'price', 'volume_ratio'])

            # PS：独立检测，时序验证影响权重而非否决
            checks.append({
                'id': 'PS',
                'detected': ps_detected,
                'weight': 2 if ps_sc_valid else 1,  # 时序有效则权重加倍
                'note': 'PS与SC时序一致' if ps_sc_valid and ps_detected else
                        ('PS已检测到（时序异常）' if ps_detected else ps_sc_reason)
            })

            # SC：独立检测，时序验证影响权重而非否决
            checks.append({
                'id': 'SC',
                'detected': sc_detected,
                'weight': 3 if ps_sc_valid else 2,  # 时序有效则权重更高
                'note': 'SC与PS时序一致' if ps_sc_valid and sc_detected else
                        ('SC已检测到（时序异常）' if sc_detected else ps_sc_reason)
            })

            # AR和ST：独立验证
            checks.append({
                'id': 'AR',
                'detected': _check_detected(ar_res, ['date', 'price']),
                'weight': 2
            })

            checks.append({
                'id': 'ST',
                'detected': _check_detected(st_res, ['date', 'price', 'volume_ratio']),
                'weight': 1
            })

            evidence_count = sum(1 for c in checks if c['detected'])
            detected_weight = sum(c['weight'] for c in checks if c['detected'])

            #  修复：基于有效证据重新计算强度
            if detected_weight >= 4 and ps_sc_valid:
                strength = "strong"
                phase_a_confirmed = True
            elif detected_weight >= 2:
                strength = "weak"
                phase_a_confirmed = True
            else:
                strength = "none"
                phase_a_confirmed = False

            return {
                "phase_a_confirmed": phase_a_confirmed,
                "strength": strength,
                "is_valid_sequence": ps_sc_valid,  # 使用PS/SC时序验证
                "evidence_count": evidence_count,
                "total_checks": 4,
                "evidence": {
                    "sc": sc_res,
                    "ps": ps_res,
                    "ar": ar_res,
                    "st": st_res,
                    "sot": sot_res,
                    "spring": spring_res
                },
                #  新增：时序验证信息
                "sequence_validation": {
                    "ps_sc_valid": ps_sc_valid,
                    "ps_sc_reason": ps_sc_reason,
                    "ps_date": ps_res.get('ps_date') if ps_res else None,
                    "sc_date": sc_res.get('date') if sc_res else None,
                    "ps_price": ps_res.get('ps_price') if ps_res else None,
                    "sc_price": sc_res.get('price') if sc_res else None,
                    "notes": [c.get('note', '') for c in checks if not c['detected']]
                }
            }
        except (KeyError, ValueError, TypeError) as e:
            logger.exception(f"Phase A证据分析失败: {e}")
            return {"phase_a_confirmed": False, "strength": "none", "error": str(e)}
        except Exception as e:
            logger.exception(f"Phase A证据分析失败: 未知异常: {e}")
            raise AnalysisError(f"Phase A证据分析失败: {e}") from e

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

