import pandas as pd
from typing import Dict, Optional, Any
import logging
from .pattern_detector import WyckoffPatternDetector
from ..exceptions import PatternDetectionError

logger = logging.getLogger(__name__)

class MultiTimeframeAnalyzer:
    """
    多时间框架分析器
    提取自 WyckoffAnalyzer，负责周线、月线趋势及共振分析
    """
    def __init__(self, data: pd.DataFrame, pattern_detector: WyckoffPatternDetector):
        self.data = data
        self.pattern_detector = pattern_detector

    def get_weekly_trend(self) -> str:
        """获取周线趋势"""
        if self.data is None or len(self.data) < 40:
            return 'unknown'
            
        # 简单采样 (Friday resample)
        weekly = self.data.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).ffill().dropna()
        
        if len(weekly) < 20:
            return 'unknown'
            
        weekly['MA10'] = weekly['Close'].rolling(10).mean()
        weekly['MA20'] = weekly['Close'].rolling(20).mean()
        
        current_close = weekly['Close'].iloc[-1]
        ma10 = weekly['MA10'].iloc[-1]
        ma20 = weekly['MA20'].iloc[-1]
        
        if current_close > ma10 > ma20: return 'bullish'
        elif current_close < ma10 < ma20: return 'bearish'
        return 'neutral'

    def get_monthly_trend(self) -> str:
        """获取月线趋势"""
        if self.data is None or len(self.data) < 120:
            return 'unknown'
            
        monthly = self.data.resample('ME').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).ffill().dropna()
        
        if len(monthly) < 12:
            return 'unknown'
            
        monthly['MA6'] = monthly['Close'].rolling(6).mean()
        monthly['MA12'] = monthly['Close'].rolling(12).mean()
        
        current_close = monthly['Close'].iloc[-1]
        ma6 = monthly['MA6'].iloc[-1]
        ma12 = monthly['MA12'].iloc[-1]
        
        if current_close > ma6 > ma12: return 'bullish'
        elif current_close < ma6 < ma12: return 'bearish'
        return 'neutral'

    def analyze_resonance(self) -> Dict:
        """
        🔧 v1.3增强：增强的多时间框架共振分析

        新增功能：
        1. 更精确的趋势一致性计算
        2. 信号共振强度评分
        3. 量能共振检测
        4. 交易建议生成
        """
        try:
            daily_analysis = self.pattern_detector.identify_phase()
        except Exception as e:
            logger.warning(f'Failed to identify daily phase for resonance, fallback to unknown: {e}')
            daily_analysis = {'phase': 'unknown', 'events_detected': {}}
        daily_events = daily_analysis.get('events_detected', {}) or {}

        weekly_resonance = self._check_signal_resonance('weekly')
        monthly_resonance = self._check_signal_resonance('monthly')

        resonance_strength = 0
        resonance_signals = []

        # Spring共振（权重调整）
        spring_upthrust = daily_events.get('spring_upthrust') or {}
        if spring_upthrust.get('_type') == 'spring':
            resonance_strength += 1
            resonance_signals.append('daily_spring')
        if weekly_resonance.get('has_spring'):
            resonance_strength += 2  # 周线Spring权重更高
            resonance_signals.append('weekly_spring')
        if monthly_resonance.get('has_spring'):
            resonance_strength += 3  # 月线Spring权重最高
            resonance_signals.append('monthly_spring')

        # SOS共振
        sos_sow = daily_events.get('sos_sow') or {}
        if sos_sow.get('_type') == 'sos':
            resonance_strength += 1
            resonance_signals.append('daily_sos')
        if weekly_resonance.get('has_sos'):
            resonance_strength += 2
            resonance_signals.append('weekly_sos')
        if monthly_resonance.get('has_sos'):
            resonance_strength += 3
            resonance_signals.append('monthly_sos')

        # JOC共振（新增）
        joc_result = self.pattern_detector.detect_joc()
        if joc_result.get('detected'):
            resonance_strength += 1
            resonance_signals.append('daily_joc')

        weekly_trend = self.get_weekly_trend()
        monthly_trend = self.get_monthly_trend()

        #  v1.3增强：更精确的趋势一致性计算
        trend_alignment_score = self._calculate_trend_alignment_enhanced(
            daily_analysis.get('phase', 'unknown'), weekly_trend, monthly_trend
        )

        #  v1.3新增：量能共振检测
        volume_resonance = self._detect_volume_resonance_enhanced()

        #  v1.3增强：综合评分（考虑趋势一致性和量能共振）
        resonance_strength = resonance_strength * 0.7 + trend_alignment_score * 0.2 + volume_resonance * 0.1

        if trend_alignment_score >= 0.8:
            resonance_strength += 2
            resonance_signals.append('strong_trend_alignment')
        elif trend_alignment_score >= 0.6:
            resonance_strength += 1
            resonance_signals.append('moderate_trend_alignment')

        if volume_resonance >= 0.8:
            resonance_strength += 1
            resonance_signals.append('volume_resonance')

        # 共振等级分类
        if resonance_strength >= 8: resonance_level = 'strong_resonance'
        elif resonance_strength >= 5: resonance_level = 'moderate_resonance'
        elif resonance_strength >= 2: resonance_level = 'weak_resonance'
        else: resonance_level = 'no_resonance'

        #  v1.3新增：生成交易建议
        trading_implication = self._generate_mtf_trading_advice(
            resonance_level, resonance_strength, trend_alignment_score
        )

        return {
            'resonance_level': resonance_level,
            'resonance_strength': round(resonance_strength, 2),
            'resonance_signals': resonance_signals,
            'daily_phase': daily_analysis.get('phase', 'unknown'),
            'weekly_trend': weekly_trend,
            'monthly_trend': monthly_trend,
            'trend_alignment_score': round(trend_alignment_score, 3),
            'volume_resonance': round(volume_resonance, 3),
            'trading_implication': trading_implication,
            'confidence_boost': round(self._calculate_confidence_boost(resonance_strength), 2),
            'weekly_analysis': weekly_resonance,
            'monthly_analysis': monthly_resonance
        }

    def _calculate_trend_alignment_enhanced(self, daily_phase: str, weekly_trend: str, monthly_trend: str) -> float:
        """
        🔧 v1.3新增：增强版趋势一致性计算

        Args:
            daily_phase: 日线阶段
            weekly_trend: 周线趋势
            monthly_trend: 月线趋势

        Returns:
            趋势一致性评分（0-1）
        """
        # 检查周线和月线趋势是否一致
        if weekly_trend == monthly_trend:
            weekly_monthly_alignment = 1.0
        elif (weekly_trend == 'bullish' and monthly_trend == 'neutral') or \
             (weekly_trend == 'neutral' and monthly_trend == 'bullish'):
            weekly_monthly_alignment = 0.7
        elif (weekly_trend == 'bearish' and monthly_trend == 'neutral') or \
             (weekly_trend == 'neutral' and monthly_trend == 'bearish'):
            weekly_monthly_alignment = 0.7
        else:
            weekly_monthly_alignment = 0.3

        # 检查日线阶段与更长周期趋势的一致性
        daily_phase_trend = self._extract_trend_from_phase(daily_phase)

        if daily_phase_trend == weekly_trend:
            daily_weekly_alignment = 1.0
        elif daily_phase_trend == 'neutral' or weekly_trend == 'neutral':
            daily_weekly_alignment = 0.6
        else:
            daily_weekly_alignment = 0.2

        # 综合评分
        return weekly_monthly_alignment * 0.6 + daily_weekly_alignment * 0.4

    def _extract_trend_from_phase(self, phase: str) -> str:
        """从阶段中提取趋势方向"""
        if 'Accumulation' in phase or 'Markup' in phase:
            return 'bullish'
        elif 'Distribution' in phase or 'Markdown' in phase:
            return 'bearish'
        else:
            return 'neutral'

    def _detect_volume_resonance_enhanced(self) -> float:
        """
        🔧 v1.3新增：增强版量能共振检测

        Returns:
            量能共振评分（0-1）
        """
        if self.data is None or len(self.data) < 60:
            return 0.0

        try:
            # 检查日线量能
            daily_vol_ma = self.data['Volume'].rolling(20).mean().iloc[-1]
            daily_vol_ratio = self.data['Volume'].iloc[-1] / daily_vol_ma if daily_vol_ma > 0 else 1.0

            # 检查周线量能
            weekly_data = self.data.resample('W-FRI').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).ffill().dropna()

            if len(weekly_data) < 10:
                return min(1.0, daily_vol_ratio / 2)  # 仅基于日线量能

            weekly_vol_ma = weekly_data['Volume'].rolling(5).mean().iloc[-1]
            weekly_vol_ratio = weekly_data['Volume'].iloc[-1] / weekly_vol_ma if weekly_vol_ma > 0 else 1.0

            # 量能共振评分
            if daily_vol_ratio > 1.5 and weekly_vol_ratio > 1.3:
                return 1.0
            elif daily_vol_ratio > 1.3 and weekly_vol_ratio > 1.2:
                return 0.8
            elif daily_vol_ratio > 1.5:
                return 0.6
            elif daily_vol_ratio > 1.2:
                return 0.4
            else:
                return 0.2

        except Exception as e:
            logger.warning(f"量能共振检测失败: {e}")
            return 0.0

    def _generate_mtf_trading_advice(self, resonance_level: str, strength: float, trend_score: float) -> str:
        """
        🔧 v1.3新增：生成多时间框架交易建议

        Args:
            resonance_level: 共振等级
            strength: 共振强度
            trend_score: 趋势一致性评分

        Returns:
            交易建议文本
        """
        if resonance_level == 'strong_resonance':
            return (f"🎯 多时间框架强共振（强度{strength:.1f}），信号可信度极高。"
                   f"趋势一致性强（{trend_score:.1%}），建议积极建仓，"
                   f"止损可相对宽松，目标可看高一线。")
        elif resonance_level == 'moderate_resonance':
            return (f"✅ 多时间框架中等共振（强度{strength:.1f}），信号可信度较高。"
                   f"建议适量建仓，注意风险控制，止损设在关键支撑位。")
        elif resonance_level == 'weak_resonance':
            return (f"⚠️ 多时间框架弱共振（强度{strength:.1f}），信号可信度一般。"
                   f"建议谨慎操作，等待更明确的信号或减少仓位。")
        else:
            return (f"❌ 多时间框架无共振（强度{strength:.1f}），信号可信度低。"
                   f"建议观望为主，避免盲目操作，等待共振出现。")

    def _calculate_confidence_boost(self, resonance_strength: float) -> float:
        """
        🔧 v1.3新增：计算置信度加成

        Args:
            resonance_strength: 共振强度

        Returns:
            置信度加成（-0.2 到 +0.4）
        """
        if resonance_strength >= 8:
            return 0.4  # 强共振显著提高置信度
        elif resonance_strength >= 5:
            return 0.2  # 中等共振适度提高置信度
        elif resonance_strength >= 2:
            return 0.0  # 弱共振不影响置信度
        else:
            return -0.2  # 无共振降低置信度

    def _check_signal_resonance(self, timeframe: str) -> Dict:
        """检查特定时间框架的信号"""
        if self.data is None or len(self.data) < 60: return {}
        try:
            if timeframe == 'weekly':
                resampled = self.data.resample('W-FRI').agg({
                    'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                }).ffill().dropna()
                min_periods = 20
            else:
                resampled = self.data.resample('ME').agg({
                    'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                }).ffill().dropna()
                min_periods = 12

            if len(resampled) < min_periods: return {'insufficient_data': True}

            recent_data = resampled.tail(10).copy()
            low_min = recent_data['Low'].min()
            recent_low = recent_data['Low'].iloc[-1]
            has_spring = (recent_low <= low_min * 1.02) and (recent_data['Close'].iloc[-1] > recent_data['Open'].iloc[-1])

            recent_data['Volume_MA'] = recent_data['Volume'].rolling(5, min_periods=1).mean()
            vol_ma_val = recent_data['Volume_MA'].iloc[-1]
            latest_vol_ratio = recent_data['Volume'].iloc[-1] / vol_ma_val if vol_ma_val > 0 else 1.0
            price_change = recent_data['Close'].pct_change().iloc[-1]
            has_sos = (latest_vol_ratio > 1.3) and (price_change > 0.03)
            
            high_max = recent_data['High'].max()
            has_upthrust = (recent_data['High'].iloc[-1] >= high_max * 0.98) and (recent_data['Close'].iloc[-1] < recent_data['Open'].iloc[-1])

            return {'has_spring': has_spring, 'has_sos': has_sos, 'has_upthrust': has_upthrust}
        except Exception as e:
            logger.error(f"Error in {timeframe} resonance: {e}")
            raise PatternDetectionError("多时间框架共振", str(e)) from e
