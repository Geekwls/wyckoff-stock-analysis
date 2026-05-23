"""
多时间框架协调器 (Multi-Timeframe Coordinator)

孟洪涛《新威科夫操盘法》核心原则：
- 周线：判断大趋势和主要方向
- 日线：识别威科夫形态和交易机会
- 小时线：精确入场点和出场点

三级共振是高胜率交易的关键：
1. 周线确定主趋势方向
2. 日线识别交易信号
3. 小时线寻找最佳入场点
"""
import logging
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MultiTimeframeCoordinator:
    """
    多时间框架协调器

    职责：
    1. 协调不同时间框架的分析结果
    2. 验证信号在不同时间框架上的共振
    3. 提供基于多时间框架的交易建议
    """

    def __init__(self):
        self.timeframes = {
            'weekly': None,   # 周线数据
            'daily': None,    # 日线数据
            'hourly': None,   # 小时线数据
        }
        self.timeframe_analyzers = {
            'weekly': None,
            'daily': None,
            'hourly': None,
        }

    def set_timeframe_data(self, timeframe: str, data: pd.DataFrame) -> None:
        """
        设置指定时间框架的数据

        Args:
            timeframe: 'weekly', 'daily', 'hourly'
            data: 价格数据
        """
        if timeframe not in self.timeframes:
            raise ValueError(f"不支持的时间框架: {timeframe}")

        self.timeframes[timeframe] = data
        logger.info(f"多时间框架协调器: 已设置 {timeframe} 数据 ({len(data)} 条)")

    def verify_signal_resonance(self, signal_type: str, direction: str, pattern_results: Optional[Dict] = None) -> Dict:
        """
        孟洪涛原则：验证信号在不同时间框架上的共振

        三级共振标准：
        1. 周线：趋势方向与信号方向一致
        2. 日线：明确的威科夫形态（Spring, JOC, SOS等）
        3. 小时线：最佳的入场时机（缩量回踩，突破确认等）

        Args:
            signal_type: 信号类型 (spring, joc, sos, etc.)
            direction: 方向 ('long' or 'short')
            pattern_results: 真实的日线威科夫信号包 (Optional)

        Returns:
            {
                'has_resonance': bool,
                'resonance_level': 'strong' | 'medium' | 'weak' | 'none',
                'weekly_trend': str,
                'daily_signal': dict,
                'hourly_entry': dict,
                'recommendation': str,
            }
        """
        # 获取各时间框架的分析结果
        weekly_analysis = self._analyze_weekly_trend()
        daily_analysis = self._analyze_daily_signal(signal_type, direction, pattern_results)
        hourly_analysis = self._analyze_hourly_entry(direction)

        # 验证共振
        resonance_checks = {
            'weekly_daily_aligned': self._check_weekly_daily_alignment(weekly_analysis, daily_analysis),
            'daily_hourly_aligned': self._check_daily_hourly_alignment(daily_analysis, hourly_analysis),
            'all_aligned': False,
        }

        resonance_checks['all_aligned'] = (
            resonance_checks['weekly_daily_aligned'] and
            resonance_checks['daily_hourly_aligned']
        )

        # 计算共振强度
        resonance_level = self._calculate_resonance_level(resonance_checks)

        # 生成建议
        recommendation = self._generate_resonance_recommendation(
            resonance_level, weekly_analysis, daily_analysis, hourly_analysis
        )

        return {
            'has_resonance': resonance_level != 'none',
            'resonance_level': resonance_level,
            'weekly_trend': weekly_analysis,
            'daily_signal': daily_analysis,
            'hourly_entry': hourly_analysis,
            'resonance_checks': resonance_checks,
            'recommendation': recommendation,
            'signal_type': signal_type,
            'direction': direction,
            'timestamp': datetime.now(),
        }

    def _analyze_weekly_trend(self) -> Dict:
        """分析周线趋势"""
        if self.timeframes['weekly'] is None or len(self.timeframes['weekly']) < 20:
            return {
                'trend': 'unknown',
                'direction': 'neutral',
                'strength': 0,
                'note': '周线数据不足'
            }

        df = self.timeframes['weekly'].tail(20).copy()

        # 计算周线均线
        ma10 = df['Close'].rolling(10).mean().iloc[-1]
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        current_price = df['Close'].iloc[-1]

        # 判断趋势
        if current_price > ma10 > ma20:
            trend = 'bullish'
            direction = 'long'
            strength = 100
        elif current_price < ma10 < ma20:
            trend = 'bearish'
            direction = 'short'
            strength = 100
        elif current_price > ma20:
            trend = 'weak_bullish'
            direction = 'long'
            strength = 60
        elif current_price < ma20:
            trend = 'weak_bearish'
            direction = 'short'
            strength = 60
        else:
            trend = 'neutral'
            direction = 'neutral'
            strength = 0

        return {
            'trend': trend,
            'direction': direction,
            'strength': strength,
            'ma10': round(ma10, 2),
            'ma20': round(ma20, 2),
            'current_price': round(current_price, 2),
            'note': f'周线趋势: {trend}'
        }

    def _analyze_daily_signal(self, signal_type: str, direction: str, pattern_results: Optional[Dict] = None) -> Dict:
        """分析日线信号"""
        if pattern_results is None:
            if self.timeframes['daily'] is None or len(self.timeframes['daily']) < 40:
                return {
                    'has_signal': False,
                    'signal_quality': 'unknown',
                    'note': '日线数据不足'
                }

            df = self.timeframes['daily'].tail(40).copy()

            # 简单的趋势判断
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            current_price = df['Close'].iloc[-1]

            if direction == 'long':
                has_signal = current_price > ma20
                signal_quality = 'strong' if current_price > ma20 * 1.02 else 'medium'
            else:
                has_signal = current_price < ma20
                signal_quality = 'strong' if current_price < ma20 * 0.98 else 'medium'

            return {
                'has_signal': has_signal,
                'signal_quality': signal_quality,
                'signal_type': signal_type,
                'current_price': round(current_price, 2),
                'ma20': round(ma20, 2),
                'note': f'日线信号: {signal_type} ({signal_quality})' if has_signal else '日线信号不明确'
            }

        # 核心逻辑：从真实的 pattern_results 提取日线威科夫信号并验证
        def _get_signal_status(pt_res, key):
            if not pt_res:
                return False, None
            events = pt_res.get('events_detected') if isinstance(pt_res, dict) else pt_res
            val = pt_res.get(key) if isinstance(pt_res, dict) else getattr(pt_res, key, None)
            if not val and events and isinstance(events, dict):
                val = events.get(key)
            elif not val and events:
                val = getattr(events, key, None)

            # 新 EventsModel 中 spring/sos/sow 等核心事件是单字段存放，
            # 旧调用可能传 spring_upthrust / sos_sow / lps_lpsy 聚合键。
            if not val and events:
                if key == 'spring':
                    val = getattr(events, 'spring', None) if not isinstance(events, dict) else events.get('spring')
                elif key == 'upthrust':
                    val = getattr(events, 'upthrust', None) if not isinstance(events, dict) else events.get('upthrust')
                elif key == 'sos':
                    val = getattr(events, 'sos', None) if not isinstance(events, dict) else events.get('sos')
                elif key == 'sow':
                    val = getattr(events, 'sow', None) if not isinstance(events, dict) else events.get('sow')
                elif key == 'lps':
                    val = getattr(events, 'lps', None) if not isinstance(events, dict) else events.get('lps')
                elif key == 'lpsy':
                    val = getattr(events, 'lpsy', None) if not isinstance(events, dict) else events.get('lpsy')
            
            detected = False
            if isinstance(val, dict):
                detected = val.get('detected', False)
            elif val:
                detected = getattr(val, 'detected', False)
            return detected, val

        has_signal, detail = _get_signal_status(pattern_results, signal_type)
        
        # 模糊同向匹配
        if not has_signal:
            if direction == 'long':
                for k in ['joc', 'spring', 'sos', 'lps']:
                    det, d_detail = _get_signal_status(pattern_results, k)
                    if det:
                        has_signal = True
                        signal_type = k
                        detail = d_detail
                        break
            else:
                for k in ['fti', 'upthrust', 'sow', 'lpsy']:
                    det, d_detail = _get_signal_status(pattern_results, k)
                    if det:
                        has_signal = True
                        signal_type = k
                        detail = d_detail
                        break

        signal_quality = 'medium'
        confidence = 50.0
        if has_signal and detail:
            if isinstance(detail, dict):
                confidence = detail.get('confidence', 50.0)
            else:
                confidence = getattr(detail, 'confidence', 50.0)
            
            if confidence >= 80:
                signal_quality = 'strong'
            elif confidence >= 50:
                signal_quality = 'medium'
            else:
                signal_quality = 'weak'

        current_price = 0.0
        if self.timeframes['daily'] is not None and len(self.timeframes['daily']) > 0:
            current_price = self.timeframes['daily']['Close'].iloc[-1]

        return {
            'has_signal': has_signal,
            'signal_quality': signal_quality,
            'signal_type': signal_type,
            'current_price': round(current_price, 2),
            'confidence': confidence,
            'note': f'日线信号确认: {signal_type.upper()} ({signal_quality}, 置信度:{confidence}%)' if has_signal else '日线信号未确认'
        }

    def _analyze_hourly_entry(self, direction: str) -> Dict:
        """分析小时线入场点"""
        if self.timeframes['hourly'] is None or len(self.timeframes['hourly']) < 24:
            return {
                'has_entry': False,
                'entry_quality': 'unknown',
                'note': '小时线数据不足'
            }

        df = self.timeframes['hourly'].tail(24).copy()

        # 检查是否有好的入场点
        current_price = df['Close'].iloc[-1]
        recent_low = df['Low'].tail(12).min()
        recent_high = df['High'].tail(12).max()
        vol_ma = df['Volume'].rolling(12).mean().iloc[-1]
        current_vol = df['Volume'].iloc[-1]

        if direction == 'long':
            # 做多入场点：价格接近支撑且缩量
            near_support = current_price < recent_low * 1.01
            low_volume = current_vol < vol_ma * 0.9
            has_entry = near_support and low_volume
            entry_quality = 'excellent' if has_entry else 'fair'
        else:
            # 做空入场点：价格接近阻力且缩量
            near_resistance = current_price > recent_high * 0.99
            low_volume = current_vol < vol_ma * 0.9
            has_entry = near_resistance and low_volume
            entry_quality = 'excellent' if has_entry else 'fair'

        return {
            'has_entry': has_entry,
            'entry_quality': entry_quality,
            'current_price': round(current_price, 2),
            'recent_low': round(recent_low, 2),
            'recent_high': round(recent_high, 2),
            'volume_ratio': round(current_vol / vol_ma, 2) if vol_ma > 0 else 1,
            'note': f'小时线入场: {entry_quality}' if has_entry else '等待更好的入场点'
        }

    def _check_weekly_daily_alignment(self, weekly: Dict, daily: Dict) -> bool:
        """检查周线和日线是否对齐"""
        weekly_dir = weekly.get('direction', 'neutral')
        daily_has_signal = daily.get('has_signal', False)

        if weekly_dir == 'neutral':
            return daily_has_signal

        return daily_has_signal and (
            (weekly_dir == 'long' and daily.get('signal_quality') in ['strong', 'medium']) or
            (weekly_dir == 'short' and daily.get('signal_quality') in ['strong', 'medium'])
        )

    def _check_daily_hourly_alignment(self, daily: Dict, hourly: Dict) -> bool:
        """检查日线和小时线是否对齐"""
        daily_has_signal = daily.get('has_signal', False)
        hourly_has_entry = hourly.get('has_entry', False)

        return daily_has_signal and hourly_has_entry

    def _calculate_resonance_level(self, checks: Dict) -> str:
        """计算共振强度"""
        if checks['all_aligned']:
            return 'strong'
        elif checks['weekly_daily_aligned'] or checks['daily_hourly_aligned']:
            return 'medium'
        else:
            return 'none'

    def _generate_resonance_recommendation(
        self,
        level: str,
        weekly: Dict,
        daily: Dict,
        hourly: Dict
    ) -> str:
        """生成基于共振的交易建议"""
        if level == 'strong':
            return (
                f"三级共振确立！周线{weekly['trend']}，日线{daily['signal_type']}，"
                f"小时线入场质量{hourly['entry_quality']}。建议积极入场。"
            )
        elif level == 'medium':
            missing = []
            if not self._check_weekly_daily_alignment(weekly, daily):
                missing.append("周线日线对齐")
            if not self._check_daily_hourly_alignment(daily, hourly):
                missing.append("日线小时线对齐")

            return f"部分共振（{' + '.join(missing)}缺失）。建议等待更好的时机。"
        else:
            return "无共振信号。建议观望等待。"

    def get_best_entry_point(self, direction: str) -> Dict:
        """
        孟洪涛原则：获取最佳入场点

        结合多时间框架分析，给出最佳入场价格区间

        Returns:
            {
                'entry_zone': (float, float),  # 入场价格区间
                'stop_loss': float,             # 止损位
                'target': float,                # 目标位
                'risk_reward': float,           # 风险收益比
                'confidence': float,            # 置信度 (0-1)
            }
        """
        if self.timeframes['hourly'] is None or self.timeframes['daily'] is None:
            return {'error': '缺少必要的时间框架数据'}

        hourly = self.timeframes['hourly'].tail(24)
        daily = self.timeframes['daily'].tail(40)

        # 计算支撑阻力
        if direction == 'long':
            support = hourly['Low'].tail(12).min()
            resistance = daily['High'].tail(20).max()
            entry_zone = (support * 0.99, support * 1.01)
            stop_loss = support * 0.97
            target = resistance
        else:
            resistance = hourly['High'].tail(12).max()
            support = daily['Low'].tail(20).min()
            entry_zone = (resistance * 0.99, resistance * 1.01)
            stop_loss = resistance * 1.03
            target = support

        # 计算风险收益比
        risk = abs(entry_zone[0] - stop_loss)
        reward = abs(target - entry_zone[0])
        risk_reward = reward / risk if risk > 0 else 0

        # 计算置信度（基于多时间框架对齐）
        weekly_analysis = self._analyze_weekly_trend()
        alignment_score = 1.0 if weekly_analysis.get('direction') == direction else 0.6

        return {
            'entry_zone': (round(entry_zone[0], 2), round(entry_zone[1], 2)),
            'stop_loss': round(stop_loss, 2),
            'target': round(target, 2),
            'risk_reward': round(risk_reward, 2),
            'confidence': round(min(alignment_score, 1.0), 2),
            'direction': direction,
        }
