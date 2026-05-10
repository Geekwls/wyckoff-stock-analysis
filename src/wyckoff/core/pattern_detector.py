import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from .detectors.trading_range_detector import TradingRangeDetector
from .detectors.classic_pattern_detector import ClassicPatternDetector
from .detectors.strength_weakness_detector import StrengthWeaknessDetector
from .detectors.phase_identifier import PhaseIdentifier
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

        # 初始化专门的检测器
        self.range_detector = TradingRangeDetector(data, config)
        self.classic_detector = ClassicPatternDetector(data, config, self.thresholds, analysis_cache)
        self.sw_detector = StrengthWeaknessDetector(data, config, self.thresholds)
        self.phase_identifier = PhaseIdentifier(data, config, self.thresholds)

        # 初始化孟洪涛增强检测器
        self.meng_enhancer = MengPatternEnhancer(data, config)

        # 初始化阶段协调器（负责事件收集和阶段验证）
        self.phase_coordinator = PhaseCoordinator(self)

        # 注册所有子检测器以支持统一接口调用
        self.all_detectors = [
            self.range_detector, self.classic_detector,
            self.sw_detector, self.phase_identifier,
            self.meng_enhancer
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
            self.bayesian_model.fit(self.data)
    
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
        except Exception:
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
        return self.classic_detector.detect_spring(lookback)

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

    def detect_joc(self, lookback: int = 90) -> Dict:
        return self.classic_detector.detect_joc(lookback)

    def detect_fti(self, lookback: int = 90) -> Dict:
        return self.classic_detector.detect_fti(lookback)

    def detect_vsa_signals(self, lookback: int = 20) -> Dict:
        return self.classic_detector.detect_vsa_signals(lookback)

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
                phase_result['confidence'] = max(phase_result.get('confidence', 0), 80)
            elif evidence_analysis['strength'] == 'weak':
                phase_result['confidence'] = max(phase_result.get('confidence', 0), 50)
            elif evidence_analysis['strength'] == 'none':
                # 如果没有核心证据，降低置信度
                if 'Accumulation' in phase_result.get('phase', ''):
                    phase_result['confidence'] = min(phase_result.get('confidence', 50), 30)

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

    def detect_lps(self, sos_result: Dict = None, spring_res: Dict = None) -> Dict:
        """检测 LPS (Last Point of Support)"""
        return self.sw_detector.detect_lps(spring_res=spring_res)

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
            # 高波动资产需要更高的成交量确认
            climax_vol_threshold = self._get_dynamic_volume_threshold(self.thresholds.VOLUME_CONFIRMATION['strong'])
            climax_range_threshold = self._get_dynamic_volume_threshold(1.5)  # 保持 1.5 倍平均价差
            fallback_vol_threshold = self._get_dynamic_volume_threshold(self.thresholds.VOLUME_CONFIRMATION['moderate'])
            
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
            
            confidence = min(100, (vol_ratio - 1.0) * 50)

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

    def detect_automatic_rally(self, lookback_days: int = 60) -> Dict:
        """
        检测自然反弹（Automatic Rally, AR）
        """
        try:
            sc_res = self.detect_climax_panic_selling(60) # 复用 SC 检测结果
            if not sc_res['detected']:
                return {"detected": False, "reason": "No SC found to baseline AR"}
            
            sc_date = pd.to_datetime(sc_res['date'])
            sc_low = sc_res['price']

            after_sc = self.data.loc[self.data.index > sc_date]
            if len(after_sc) < 2:
                return {"detected": False, "reason": "Insufficient data after SC"}

            ar_high = after_sc['High'].max()
            ar_idx = after_sc['High'].idxmax()

            # 修正：反弹起点应为 SC 当日的收盘价或实体中位值，而非最低价 (P1 #2.1)
            sc_bar = self.data.loc[sc_date]
            baseline = (sc_bar['Open'] + sc_bar['Close']) / 2
            
            rebound_pct = (ar_high - baseline) / baseline * 100
            # 威科夫理论中，AR 通常非常剧烈
            is_ar = rebound_pct > 5 

            return {
                "detected": is_ar,
                "sc_date": sc_date,
                "sc_low": float(sc_low),
                "ar_date": ar_idx,
                "date": ar_idx, # 兼容性
                "price": float(ar_high), # 兼容性
                "ar_high": float(ar_high),
                "rebound_pct": float(rebound_pct),
                "confidence": min(100, (rebound_pct - 3) * 10) if is_ar else 0
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
        
        威科夫理论定义：
        - PS 是主跌段中的第一次抄底尝试
        - 发生在 SC（恐慌抛售）之前
        - 特征：成交量放大 + 价格止跌/反弹 + 下影线抵抗
        - PS 失败后会引发恐慌抛售（SC）
        
        时序关系：PS → SC → AR → ST
        """
        try:
            # 获取足够历史数据
            data = self.data.tail(lookback_days)
            if len(data) < 20:
                return {"detected": False, "reason": "Insufficient data"}
            
            # 步骤1：识别主跌段
            # 主跌段定义：价格持续下跌，低于20日均线
            ma20 = data['Close'].rolling(window=20).mean()
            downtrend_mask = data['Close'] < ma20
            
            if not downtrend_mask.any():
                return {"detected": False, "reason": "No downtrend found"}
            
            # 找到主跌段的起点（价格跌破MA20的位置）
            downtrend_start = None
            for i in range(len(data)):
                if downtrend_mask.iloc[i]:
                    downtrend_start = i
                    break
            
            if downtrend_start is None or downtrend_start >= len(data) - 5:
                return {"detected": False, "reason": "Downtrend too short"}
            
            # 步骤2：在主跌段中寻找PS
            # PS特征：
            # 1. 成交量放大（超过MA20的动态阈值倍）
            # 2. 价格止跌或反弹（收盘价高于前一日）
            # 3. 下影线较长（显示买盘抵抗）
            
            # 动态阈值：基于ATR适配
            ps_vol_threshold = self._get_dynamic_volume_threshold(1.2)
            ps_vol_strong_threshold = self._get_dynamic_volume_threshold(1.5)
            
            potential_ps = []
            downtrend_data = data.iloc[downtrend_start:]
            
            for i in range(2, len(downtrend_data) - 1):
                current = downtrend_data.iloc[i]
                prev = downtrend_data.iloc[i-1]
                next_day = downtrend_data.iloc[i+1] if i + 1 < len(downtrend_data) else None
                
                # 获取成交量均线
                vol_ma = current.get('Volume_MA20', data['Volume'].iloc[:downtrend_start + i].tail(20).mean())
                
                # 条件1：成交量放大（使用动态阈值）
                vol_ratio = current['Volume'] / vol_ma if vol_ma > 0 else 0
                vol_heavy = vol_ratio > ps_vol_threshold
                
                # 条件2：价格止跌或反弹
                # 收盘价高于前一日收盘，或者当日收阳
                price_stabilized = (current['Close'] > prev['Close']) or (current['Close'] > current['Open'])
                
                # 条件3：下影线抵抗
                # 下影线长度 > 实体长度的0.5倍
                body = abs(current['Close'] - current['Open'])
                lower_shadow = min(current['Open'], current['Close']) - current['Low']
                shadow_resistance = lower_shadow > body * 0.5 if body > 0 else lower_shadow > 0
                
                # 综合判断
                if vol_heavy and price_stabilized and shadow_resistance:
                    # 计算置信度
                    confidence = 50
                    if vol_ratio > ps_vol_strong_threshold:
                        confidence += 15
                    if current['Close'] > current['Open']:  # 收阳线
                        confidence += 10
                    if lower_shadow > body:  # 下影线长于实体
                        confidence += 10
                    if next_day is not None and next_day['Close'] > current['Close']:  # 次日继续上涨
                        confidence += 15
                    
                    potential_ps.append({
                        'idx': downtrend_start + i,
                        'date': data.index[downtrend_start + i],
                        'price': float(current['Close']),
                        'low': float(current['Low']),
                        'vol_ratio': float(vol_ratio),
                        'lower_shadow_ratio': float(lower_shadow / (body + 0.001)),
                        'confidence': min(100, confidence)
                    })
            
            if not potential_ps:
                return {"detected": False, "reason": "No PS pattern found in downtrend"}
            
            # 选择置信度最高的PS
            best_ps = max(potential_ps, key=lambda x: x['confidence'])
            
            # 验证：PS之后应该有SC（恐慌抛售）
            # 检查PS之后是否出现价格创新低且成交量放大的情况
            ps_idx = best_ps['idx']
            post_ps_data = data.iloc[ps_idx + 1:]
            
            # 寻找可能的SC（在PS之后，价格创新低）
            sc_found = False
            sc_price = None
            for i in range(len(post_ps_data)):
                row = post_ps_data.iloc[i]
                if row['Low'] < best_ps['low']:  # 价格创新低
                    vol_ma = row.get('Volume_MA20', data['Volume'].iloc[:ps_idx + i + 1].tail(20).mean())
                    if row['Volume'] > vol_ma * 1.5:  # 成交量放大
                        sc_found = True
                        sc_price = float(row['Low'])
                        break
            
            return {
                "detected": True,
                "ps_date": best_ps['date'].strftime("%Y-%m-%d"),
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

            checks = [
                {'id': 'PS', 'detected': ps_res.get("detected", False), 'weight': 1},
                {'id': 'SC', 'detected': sc_res.get("detected", False), 'weight': 2},
                {'id': 'AR', 'detected': ar_res.get("detected", False), 'weight': 2},
                {'id': 'ST', 'detected': st_res.get("detected", False), 'weight': 1}
            ]

            evidence_count = sum(1 for c in checks if c['detected'])
            detected_weight = sum(c['weight'] for c in checks if c['detected'])

            is_valid_sequence = False
            if ps_res.get('detected') and sc_res.get('detected') and ar_res.get('detected'):
                # 兼容性处理：支持 Timestamp 或字符串
                def to_dt(d): return pd.to_datetime(d) if d else None
                
                ps_date = to_dt(ps_res.get('ps_date'))
                sc_date = to_dt(sc_res.get('date'))
                ar_date = to_dt(ar_res.get('ar_date'))
                
                if ps_date and sc_date and ar_date:
                    if ps_date < sc_date < ar_date:
                        is_valid_sequence = True

            if detected_weight >= 4 and is_valid_sequence:
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
                "is_valid_sequence": is_valid_sequence,
                "evidence_count": evidence_count,
                "total_checks": 4,
                "evidence": {
                    "sc": sc_res,
                    "ps": ps_res,
                    "ar": ar_res,
                    "st": st_res,
                    "sot": sot_res,
                    "spring": spring_res
                }
            }
        except (KeyError, ValueError, TypeError) as e:
            logger.exception(f"Phase A证据分析失败: {e}")
            return {"phase_a_confirmed": False, "strength": "none", "error": str(e)}
        except Exception as e:
            logger.exception(f"Phase A证据分析失败: 未知异常: {e}")
            raise AnalysisError(f"Phase A证据分析失败: {e}") from e
