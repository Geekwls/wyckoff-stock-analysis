import pandas as pd
import logging
from typing import Dict, Optional, Tuple, List, Any, Union
from .base_detector import BaseDetector
from ...config.settings import WyckoffConfig, WyckoffThresholds
from ..enums import WyckoffPhase
from ..utils import PhaseAdapter

logger = logging.getLogger(__name__)

class PhaseIdentifier(BaseDetector):
    """负责识别威科夫阶段和评分"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, thresholds: WyckoffThresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def identify(self, raw_events: Dict) -> Dict:
        """主识别流程"""
        if self.data is None:
            return {'phase': 'Unknown', 'confidence': 0.0, 'phase_enum': WyckoffPhase.UNKNOWN}

        # 🔧 修复信号穿越：只分析相关时间窗口内的事件
        events = self.filter_relevant_events(raw_events)

        phase_str, phase_enum, confidence = self._determine_phase_from_events(events)
        if phase_enum == WyckoffPhase.UNKNOWN:
            phase_str, phase_enum, confidence = self._fallback_logic()
        
        # 🔧 评分修正：如果 Phase A 结构不完整，大幅扣减置信度
        if phase_enum != WyckoffPhase.UNKNOWN:
            completeness_factor = self._calculate_structural_integrity(events, phase_enum)
            confidence *= completeness_factor

            # 🔧 新增：Phase A结构不完整时的额外惩罚
            if phase_enum == WyckoffPhase.PHASE_A:
                has_complete_structure = self._check_phase_a_completeness(events)
                if not has_complete_structure:
                    confidence *= 0.5  # 结构不完整，置信度减半
                    logger.info(f"[Phase A结构不完整] 置信度从{confidence*2:.2f}降低至{confidence:.2f}")

        ma_conf = self._check_ma_confirmation(phase_enum)
        vol_conf = self._check_volume_confirmation(phase_enum)
        
        weights = self.thresholds.SCORING.phase_weights
        final_conf = (
            confidence * weights.get('confidence', 0.5) + 
            ma_conf * weights.get('ma', 0.3) + 
            vol_conf * weights.get('vol', 0.2)
        )
        seq_score = self.calculate_sequence_score(events, phase_enum)
        final_conf *= seq_score.get('adjustment_factor', 1.0)

        # 增加量价质量传递验证 (P2 #2.3)
        quality_factor = self._analyze_phase_a_evidence(events)
        final_conf *= quality_factor

        # 🔧 修复矛盾二：增加相位一致性互斥校验
        phase_str, phase_enum, final_conf = self._check_logical_consistency(events, phase_str, phase_enum, final_conf)

        return {
            'phase': phase_str,
            'phase_enum': phase_enum,
            'confidence': round(min(final_conf, 1.0), 2),
            'ma_confidence': round(ma_conf, 2),
            'vol_confidence': round(vol_conf, 2),
            'sequence_score': seq_score,
            'quality_factor': round(quality_factor, 2)
        }

    def _analyze_phase_a_evidence(self, events: Dict) -> float:
        """
        验证 Phase A 的量价质量传递 (P2 #2.3)
        """
        score = 1.0
        climax = events.get('climax')
        st = events.get('secondary_test')
        
        if climax and hasattr(climax, 'detected') and climax.detected and \
           st and hasattr(st, 'detected') and st.detected:
            try:
                sc_vol = climax.volume
                st_date = st.date
                st_vol = self.data.loc[st_date, 'Volume']
                
                vol_ratio = st_vol / sc_vol
                # 如果 ST 成交量显著小于 SC，说明供应萎缩，增加置信度
                if vol_ratio < 0.4:
                    score += 0.15
                elif vol_ratio > 0.8:
                    score -= 0.15
            except Exception:
                pass
        return score

    def _check_phase_a_completeness(self, events: Dict) -> bool:
        """检查Phase A结构完整性"""
        climax = events.get('climax')
        ar = events.get('automatic_reaction')
        st = events.get('secondary_test')

        has_climax = False
        if climax:
            if hasattr(climax, 'detected'):
                has_climax = climax.detected
            elif isinstance(climax, dict):
                has_climax = climax.get('detected', False)

        has_ar = False
        if ar:
            if hasattr(ar, 'detected'):
                has_ar = ar.detected
            elif isinstance(ar, dict):
                has_ar = ar.get('detected', False)

        has_st = False
        if st:
            if hasattr(st, 'detected'):
                has_st = st.detected
            elif isinstance(st, dict):
                has_st = st.get('detected', False)

        return has_climax and (has_ar or has_st)

    def _determine_phase_from_events(self, events: Dict) -> Tuple[str, WyckoffPhase, float]:
        """从事件序列中判定阶段 - 优化版（方案B）"""

        # 🔧 方案B优化：首先检查是否为"BC强但AR/ST缺失"的模糊结构
        ambiguous_phase = self._check_ambiguous_phase_structure(events)
        if ambiguous_phase:
            return ambiguous_phase  # 返回更精确的阶段标签

        # 标准阶段识别逻辑
        su_info = events.get('spring_upthrust') or {}
        su_data = su_info.get('data')
        ss_info = events.get('sos_sow') or {}
        ss_data = ss_info.get('data')

        climax = events.get('climax')
        ar = events.get('automatic_reaction')
        st = events.get('secondary_test')

        is_spring = su_info.get('_type') == 'spring' and su_data and su_data.detected
        is_upthrust = su_info.get('_type') == 'upthrust' and su_data and su_data.detected
        is_sos = ss_info.get('_type') == 'sos' and ss_data and ss_data.detected
        is_sow = ss_info.get('_type') == 'sow' and ss_data and ss_data.detected

        if is_spring and is_sos:
            return 'Accumulation Phase D (积累期突破)', WyckoffPhase.PHASE_D, 0.85
        if is_spring:
            return 'Accumulation Phase C (积累期震仓)', WyckoffPhase.PHASE_C, 0.70
        if is_upthrust and is_sow:
            return 'Distribution Phase D (派发期跌破)', WyckoffPhase.PHASE_D, 0.85
        if is_upthrust:
            return 'Distribution Phase C (派发期诱多)', WyckoffPhase.PHASE_C, 0.70

        if climax and climax.detected and ar and ar.detected:
            if climax.type == 'selling_climax':
                return 'Accumulation Phase A (恐慌抛售停止)', WyckoffPhase.PHASE_A, 0.75
            return 'Distribution Phase A (买入高潮停止)', WyckoffPhase.PHASE_A, 0.75

        if climax and climax.detected and st and st.detected:
            if climax.type == 'selling_climax':
                return 'Accumulation Phase B (积累期测试)', WyckoffPhase.PHASE_B, 0.60
            return 'Distribution Phase B (派发期测试)', WyckoffPhase.PHASE_B, 0.60

        return 'Unknown', WyckoffPhase.UNKNOWN, 0.30

    def _check_ambiguous_phase_structure(self, events: Dict) -> Tuple[str, WyckoffPhase, float]:
        """
        🔧 方案B核心功能：识别和标记模糊结构

        处理"BC强但AR/ST缺失"的情况，给出更精确的阶段标签
        """
        climax = events.get('climax')

        # 检查是否有强烈的Climax信号
        has_strong_climax = False
        climax_type = None
        climax_confidence = 0.0

        if climax:
            # 安全地检查climax对象
            if hasattr(climax, 'detected'):
                has_strong_climax = climax.detected
                climax_type = getattr(climax, 'type', None)
                climax_confidence = getattr(climax, 'confidence', 0.94)
            elif isinstance(climax, dict):
                has_strong_climax = climax.get('detected', False)
                climax_type = climax.get('type')
                climax_confidence = climax.get('confidence', 0.94)

        # 🔧 方案B增强：设置BC强度阈值（只处理高置信度BC）
        if not has_strong_climax or climax_confidence < 0.85:
            return None  # BC不够强或不存在，不是模糊结构

        # 安全地检查AR/ST
        ar = events.get('automatic_reaction')
        st = events.get('secondary_test')

        has_ar = self._safe_check_detected(ar)
        has_st = self._safe_check_detected(st)

        # 🔧 方案B核心：BC强但AR/ST缺失
        if has_strong_climax and not (has_ar or has_st):
            logger.info(f"[方案B] 检测到模糊结构: {climax_type} (置信度: {climax_confidence:.2f}), 缺失AR/ST确认")

            # 🔧 动态灵敏度调整：尝试检测"准AR"和"准ST"
            weak_ar = self._detect_weak_automatic_reaction(events, climax)
            weak_st = self._detect_weak_secondary_test(events, climax)

            current_price = self.data['Close'].iloc[-1]
            ma20 = self.data['MA20'].iloc[-1] if 'MA20' in self.data.columns else current_price
            ma50 = self.data['MA50'].iloc[-1] if 'MA50' in self.data.columns else current_price
            ma200 = self.data['MA200'].iloc[-1] if 'MA200' in self.data.columns else current_price

            # 根据技术趋势和BC类型给出更精确的标签
            if current_price > ma20 > ma50 > ma200:
                # 🟢 技术面完美多头排列 + Buying Climax
                if climax_type == 'buying_climax':
                    if weak_ar or weak_st:
                        logger.info(f"[方案B] 判定为: Markup Phase E (上涨末期，潜在派发初期)")
                        return 'Markup Phase E (上涨末期，潜在派发初期)', WyckoffPhase.PHASE_E, 0.65
                    else:
                        logger.info(f"[方案B] 判定为: Markup Phase E (强势上涨，伴有买入高潮警示)")
                        return 'Markup Phase E (强势上涨，伴有买入高潮警示)', WyckoffPhase.PHASE_E, 0.60
                else:  # selling_climax
                    logger.info(f"[方案B] 判定为: Markup Phase E (强势上涨，但出现恐慌性抛售)")
                    return 'Markup Phase E (强势上涨，但出现恐慌性抛售)', WyckoffPhase.PHASE_E, 0.55

            elif current_price < ma20 < ma50:
                # 🔴 技术面转弱
                if climax_type == 'buying_climax':
                    logger.info(f"[方案B] 判定为: Distribution Phase A (买入高潮，等待回落确认)")
                    return 'Distribution Phase A (买入高潮，等待回落确认)', WyckoffPhase.PHASE_A, 0.70
                else:  # selling_climax
                    logger.info(f"[方案B] 判定为: Accumulation Phase A (恐慌抛售，等待反弹确认)")
                    return 'Accumulation Phase A (恐慌抛售，等待反弹确认)', WyckoffPhase.PHASE_A, 0.70

            else:
                # 🟡 技术面震荡不明
                if climax_type == 'buying_climax':
                    logger.info(f"[方案B] 判定为: Trending with BC Warning (趋势推进中，买入高潮警示)")
                    return 'Trending with BC Warning (趋势推进中，买入高潮警示)', WyckoffPhase.UNKNOWN, 0.50
                else:
                    logger.info(f"[方案B] 判定为: Trending with SC Warning (趋势整理中，恐慌抛售警示)")
                    return 'Trending with SC Warning (趋势整理中，恐慌抛售警示)', WyckoffPhase.UNKNOWN, 0.50

        return None  # 不是模糊结构

    def _safe_check_detected(self, event) -> bool:
        """安全地检查事件是否被检测到"""
        if event is None:
            return False

        if hasattr(event, 'detected'):
            return event.detected
        elif isinstance(event, dict):
            return event.get('detected', False)

        return False

    def _detect_weak_automatic_reaction(self, events: Dict, climax) -> bool:
        """
        🔧 动态灵敏度调整：检测"准AR"信号

        放宽AR检测条件，寻找"微弱的价格反应"
        """
        if not climax or not hasattr(climax, 'date'):
            return False

        climax_date = climax.date if hasattr(climax, 'date') else climax.get('date')
        if not climax_date:
            return False

        try:
            # 🔧 降低AR检测阈值：正常AR需要明显反向运动，这里寻找微弱反应
            df_after = self.data[self.data.index > climax_date].head(30)
            if len(df_after) < 3:
                return False

            # 正常AR阈值：明显反向运动
            # 准AR阈值：任何价格停滞或微弱反向

            if climax.type == 'buying_climax':
                # BC后的微弱回落
                high_after_bc = df_after['High'].iloc[0:5].max()
                bc_price = climax.price if hasattr(climax, 'price') else climax.get('price')

                # 准AR条件：价格没有创新高，显示上涨动力衰竭
                if bc_price and high_after_bc < bc_price * 1.02:  # 2%容差
                    return True

            else:  # selling_climax
                # SC后的微弱反弹
                low_after_sc = df_after['Low'].iloc[0:5].min()
                sc_price = climax.price if hasattr(climax, 'price') else climax.get('price')

                # 准AR条件：价格没有创新低，显示抛压减轻
                if sc_price and low_after_sc > sc_price * 0.98:  # 2%容差
                    return True

        except Exception as e:
            logger.debug(f"Weak AR detection failed: {e}")

        return False

    def _detect_weak_secondary_test(self, events: Dict, climax) -> bool:
        """
        🔧 动态灵敏度调整：检测"准ST"信号

        放宽ST检测条件，寻找"量能萎缩的价格测试"
        """
        if not climax or not hasattr(climax, 'date') or not hasattr(climax, 'volume'):
            return False

        climax_date = climax.date
        climax_volume = climax.volume

        try:
            df_after = self.data[self.data.index > climax_date].head(30)
            if len(df_after) < 5:
                return False

            # 正常ST：价格测试climax低点 + 量能显著萎缩
            # 准ST：价格接近climax低点 OR 量能萎缩（二选一即可）

            if climax.type == 'buying_climax':
                bc_high = climax.price
                recent_highs = df_after['High'].tail(10)

                # 准ST条件1：价格接近BC高点（容差放宽到3%）
                price_test = (recent_highs >= bc_high * 0.97).any()

                # 准ST条件2：量能显著萎缩（比正常要求更宽松）
                volume_ma = self.data['Volume_MA20'].iloc[-1] if 'Volume_MA20' in self.data.columns else df_after['Volume'].mean()
                vol_shrinkage = (df_after['Volume'].tail(5) < volume_ma * 0.8).any()

                return price_test or vol_shrinkage

            else:  # selling_climax
                sc_low = climax.price
                recent_lows = df_after['Low'].tail(10)

                # 准ST条件1：价格接近SC低点（容差放宽到3%）
                price_test = (recent_lows <= sc_low * 1.03).any()

                # 准ST条件2：量能显著萎缩
                volume_ma = self.data['Volume_MA20'].iloc[-1] if 'Volume_MA20' in self.data.columns else df_after['Volume'].mean()
                vol_shrinkage = (df_after['Volume'].tail(5) < volume_ma * 0.8).any()

                return price_test or vol_shrinkage

        except Exception as e:
            logger.debug(f"Weak ST detection failed: {e}")

        return False

    def _fallback_logic(self) -> Tuple[str, WyckoffPhase, float]:
        """基于均线排布的降级判定逻辑"""
        current = self.data['Close'].iloc[-1]
        
        def get_ma(period):
            if self._indicator_cache:
                try:
                    return self._indicator_cache.get(f'MA{period}').iloc[-1]
                except Exception:
                    pass
            col = f'MA{period}'
            if col in self.data.columns:
                return self.data[col].iloc[-1]
            return self.data['Close'].rolling(window=period).mean().iloc[-1]

        ma20 = get_ma(20)
        ma50 = get_ma(50)
        ma200 = get_ma(200)
        
        if current > ma20 > ma50 > ma200: 
            return "Markup Phase E (强势上涨)", WyckoffPhase.PHASE_E, 0.6
        if current < ma20 < ma50 < ma200: 
            return "Markdown Phase E (强势下跌)", WyckoffPhase.PHASE_E, 0.6
            
        return "Trending (趋势中)", WyckoffPhase.UNKNOWN, 0.4

    def _check_ma_confirmation(self, phase: Union[str, WyckoffPhase]) -> float:
        """检查均线确认"""
        current = self.data['Close'].iloc[-1]
        ma200 = self.data['MA200'].iloc[-1] if 'MA200' in self.data.columns else current
        if PhaseAdapter.is_accumulation(phase) or PhaseAdapter.is_markup(phase): 
            return 0.8 if current > ma200 else 0.4
        if PhaseAdapter.is_distribution(phase) or PhaseAdapter.is_markdown(phase): 
            return 0.8 if current < ma200 else 0.4
        return 0.5

    def _check_volume_confirmation(self, phase: Union[str, WyckoffPhase]) -> float:
        """检查成交量确认 (Effort vs Result)"""
        df = self.data.tail(20)
        up_v = df[df['Close'] > df['Close'].shift(1)]['Volume'].mean()
        dn_v = df[df['Close'] < df['Close'].shift(1)]['Volume'].mean()
        ratio = up_v / dn_v if dn_v > 0 else 1
        
        if PhaseAdapter.is_markup(phase): 
            return 0.9 if ratio > 1.2 else 0.5
        if PhaseAdapter.is_markdown(phase): 
            return 0.9 if ratio < 0.8 else 0.5
        return 0.5

    def filter_relevant_events(self, events: Dict, lookback_days: int = 120) -> Dict:
        """
        🔧 修复信号穿越问题：过滤掉时间跨度过大的“过期”证据
        对于当前阶段识别，只考虑最近 120 个交易日内的信号。
        """
        filtered = {}
        for key, event in events.items():
            if not event: continue

            date = None
            # 安全地获取日期信息
            if isinstance(event, dict):
                date = event.get('date')
                if not date and 'data' in event:
                    data = event.get('data', {})
                    if isinstance(data, dict):
                        date = data.get('date')
                    elif hasattr(data, 'date'):
                        date = data.date
            elif hasattr(event, 'date'):
                date = event.date
            elif hasattr(event, 'get'):
                # 可能是具有get方法的对象（如某些包装类）
                try:
                    date = event.get('date')
                except AttributeError:
                    pass

            if date:
                age = self._get_signal_age_days(date)
                # 如果信号超过 120 天，视为“历史因果”，不再作为当前相位证据
                if age < lookback_days:
                    filtered[key] = event
                else:
                    logger.debug(f"Filtered out historical signal {key} from {date} (age: {age} days)")
            else:
                filtered[key] = event
        return filtered

    def _calculate_structural_integrity(self, events: Dict, phase: WyckoffPhase) -> float:
        """
        计算结构完整性因子 (Phase A 四大支柱：PS → SC/BC → AR → ST)
        """
        climax = events.get('climax')
        ar = events.get('automatic_reaction')
        st = events.get('secondary_test')

        # PS/PSY 初次支撑/供给检测
        ps_event = events.get('preliminary_support')
        ps_detected = False
        if ps_event:
            ps_detected = self._safe_check_detected(ps_event)

        count = 0
        if climax and (isinstance(climax, dict) and climax.get('detected') or getattr(climax, 'detected', False)): count += 1
        if ar and (isinstance(ar, dict) and ar.get('detected') or getattr(ar, 'detected', False)): count += 1
        if st and (isinstance(st, dict) and st.get('detected') or getattr(st, 'detected', False)): count += 1
        if ps_detected: count += 1

        # 如果 4 个支柱只剩 1-2 个，置信度打折
        if count <= 1: return 0.4
        if count == 2: return 0.6
        if count == 3: return 0.85
        return 1.0

    def calculate_sequence_score(self, events: Dict, phase: Union[str, WyckoffPhase]) -> Dict:
        """计算事件序列完整性得分"""
        count = 0
        checks = ['climax', 'automatic_reaction', 'secondary_test', 'spring_upthrust', 'sos_sow']
        for c in checks:
            event = events.get(c)
            if event:
                if isinstance(event, dict): # spring_upthrust or sos_sow
                    data = event.get('data')
                    if data and data.detected: count += 1
                elif hasattr(event, 'detected') and event.detected: 
                    count += 1
            
        completeness = (count / len(checks)) * 100
        factor = 1.0 if completeness >= 80 else 0.8 if completeness >= 60 else 0.6
        return {
            'completeness': completeness, 
            'adjustment_factor': factor, 
            'rating': 'S' if completeness >= 80 else 'B' if completeness >= 60 else 'C'
        }

    def _check_logical_consistency(self, events: Dict, phase_str: str, phase_enum: WyckoffPhase, confidence: float) -> Tuple[str, WyckoffPhase, float]:
        """
        🔧 修复矛盾二：执行相位逻辑互斥检查
        
        威科夫逻辑准则：
        1. 如果检测到 LPS (最后支撑) 或 JOC (跳跃小溪)，说明当前处于上涨推进 (Markup) 或 再积累 (Reaccumulation)。
           即使日线有 SOW 或 FTI 信号，也不能判定为 Distribution (派发)。
        2. 如果价格创出新高且出现 LPS，强制修正相位为 Markup 或 Accumulation Phase D/E。
        """
        # 获取具体的检测标志
        is_lps = False
        lps_event = events.get('lps')
        if lps_event:
            is_lps = lps_event.get('detected') if isinstance(lps_event, dict) else getattr(lps_event, 'detected', False)

        is_joc = False
        joc_event = events.get('joc')
        if joc_event:
            is_joc = joc_event.get('detected') if isinstance(joc_event, dict) else getattr(joc_event, 'detected', False)
            
        is_distribution = PhaseAdapter.is_distribution(phase_enum) or PhaseAdapter.is_markdown(phase_enum)
        
        current_price = self.data['Close'].iloc[-1]
        ma200 = self.data['MA200'].iloc[-1] if 'MA200' in self.data.columns else current_price
        
        # 规则 1：LPS 与 Distribution 互斥
        if is_lps and is_distribution:
            # 修正：既然有 LPS 支撑，就不应该是派发，更可能是再积累或上涨中继
            if current_price > ma200:
                return 'Markup (趋势上涨中继)', WyckoffPhase.PHASE_E, 0.75
            else:
                return 'Accumulation Phase D (积累期突破中)', WyckoffPhase.PHASE_D, 0.70
                
        # 规则 2：JOC 证伪派发 A
        if is_joc and 'Phase A' in phase_str and 'Distribution' in phase_str:
            # 价格已跳跃小溪，不是买入高潮停止，而是强力推进
            return 'Markup Phase E (强势超买推进)', WyckoffPhase.PHASE_E, 0.80
            
        return phase_str, phase_enum, confidence
