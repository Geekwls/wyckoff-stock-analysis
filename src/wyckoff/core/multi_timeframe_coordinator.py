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

    @classmethod
    def build_from_daily(
        cls,
        daily_data: pd.DataFrame,
        weekly_data: Optional[pd.DataFrame] = None,
        hourly_data: Optional[pd.DataFrame] = None,
    ) -> 'MultiTimeframeCoordinator':
        """从日线数据构建协调器（可选注入周线/小时线）。"""
        coord = cls()
        coord.set_timeframe_data('daily', daily_data)

        if weekly_data is not None and len(weekly_data) > 0:
            coord.set_timeframe_data('weekly', weekly_data)
        elif daily_data is not None and len(daily_data) >= 40:
            try:
                # 无外部周线数据时由日线重采样，保证 Coordinator 三级共振可运行
                weekly = daily_data.resample('W-FRI').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum',
                }).dropna()
                if len(weekly) >= 20:
                    coord.set_timeframe_data('weekly', weekly)
            except Exception as exc:
                logger.debug(f"周线重采样失败: {exc}")

        if hourly_data is not None and len(hourly_data) > 0:
            coord.set_timeframe_data('hourly', hourly_data)

        return coord

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

    def no_signal_resonance(self) -> Dict:
        """无明确日线威科夫信号时的共振占位结果。"""
        weekly_analysis = self._analyze_weekly_trend()
        return {
            'has_resonance': False,
            'resonance_level': 'none',
            'weekly_trend': weekly_analysis,
            'daily_signal': {
                'has_signal': False,
                'signal_type': 'none',
                'direction': 'neutral',
                'signal_quality': 'none',
                'confidence': 0.0,
                'note': '无明确日线威科夫信号',
            },
            'hourly_entry': {
                'has_entry': False,
                'entry_quality': 'none',
                'note': '跳过小时线入场分析',
            },
            'resonance_checks': {
                'weekly_daily_aligned': False,
                'daily_hourly_aligned': False,
                'all_aligned': False,
            },
            'recommendation': '无明确日线威科夫信号，跳过三级共振验证。',
        }

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
        if signal_type in (None, '', 'none') or direction in (None, '', 'neutral'):
            return self.no_signal_resonance()

        # 获取各时间框架的分析结果
        weekly_analysis = self._analyze_weekly_trend()
        daily_analysis = self._analyze_daily_signal(signal_type, direction, pattern_results)
        hourly_analysis = self._analyze_hourly_entry(direction, pattern_results)
        evr_context = self._build_evr_context(pattern_results)
        weekly_evr = self._detect_weekly_evr()
        evr_resonance = self._evaluate_evr_resonance(evr_context, weekly_evr, daily_analysis)

        # 验证共振
        resonance_checks = {
            'weekly_daily_aligned': self._check_weekly_daily_alignment(
                weekly_analysis, daily_analysis, direction=direction
            ),
            'daily_hourly_aligned': self._check_daily_hourly_alignment(daily_analysis, hourly_analysis),
            'all_aligned': False,
        }

        resonance_checks['all_aligned'] = (
            resonance_checks['weekly_daily_aligned'] and
            resonance_checks['daily_hourly_aligned']
        )

        # 计算共振强度
        resonance_level = self._calculate_resonance_level(resonance_checks)
        if evr_resonance.get('boost'):
            if resonance_level == 'medium':
                resonance_level = 'strong'
            elif resonance_level == 'none' and evr_resonance.get('has_co_detection'):
                resonance_level = 'medium'

        # 生成建议
        recommendation = self._generate_resonance_recommendation(
            resonance_level, weekly_analysis, daily_analysis, hourly_analysis,
            direction=direction, pattern_results=pattern_results,
            evr_resonance=evr_resonance,
        )

        return {
            'has_resonance': resonance_level != 'none',
            'resonance_level': resonance_level,
            'weekly_trend': weekly_analysis,
            'daily_signal': daily_analysis,
            'hourly_entry': hourly_analysis,
            'evr_resonance': evr_resonance,
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
        confidence_pct = 50.0
        if has_signal and detail:
            from .signal_extractor import SignalExtractor
            # 统一 0–100 与 0–1 置信度，避免 MTF 共振档位误判
            conf_norm = SignalExtractor.normalize_event_confidence(detail)
            confidence_pct = round(conf_norm * 100, 1)
            if conf_norm >= 0.8:
                signal_quality = 'strong'
            elif conf_norm >= 0.5:
                signal_quality = 'medium'
            else:
                signal_quality = 'weak'

        current_price = 0.0
        if self.timeframes['daily'] is not None and len(self.timeframes['daily']) > 0:
            current_price = self.timeframes['daily']['Close'].iloc[-1]

        bullish_types = {'joc', 'spring', 'sos', 'lps'}
        bearish_types = {'fti', 'upthrust', 'sow', 'lpsy'}
        signal_direction = (
            'long' if signal_type in bullish_types else
            'short' if signal_type in bearish_types else direction
        )

        return {
            'has_signal': has_signal,
            'signal_quality': signal_quality,
            'signal_type': signal_type,
            'direction': signal_direction,
            'current_price': round(current_price, 2),
            'confidence': confidence_pct,
            'note': f'日线信号确认: {signal_type.upper()} ({signal_quality}, 置信度:{confidence_pct}%)' if has_signal else '日线信号未确认'
        }

    def _analyze_hourly_entry(
        self,
        direction: str,
        pattern_results: Optional[Dict] = None,
    ) -> Dict:
        """分析小时线入场点 — 优先对接日线 LPS/LPSY/JOC/FTI 锚点。"""
        if self.timeframes['hourly'] is None or len(self.timeframes['hourly']) < 24:
            return {
                'has_entry': False,
                'entry_quality': 'unknown',
                'note': '小时线数据不足'
            }

        from .signal_extractor import SignalExtractor
        from .intraday_vsa import IntradayVSAService

        df = self.timeframes['hourly'].tail(24).copy()
        current_price = float(df['Close'].iloc[-1])
        vol_ma = float(df['Volume'].rolling(12).mean().iloc[-1])
        current_vol = float(df['Volume'].iloc[-1])
        vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1.0
        low_volume = vol_ratio < 0.85

        # 小时线入场优先对接日线威科夫锚点（LPS/Creek/LPSY/Ice），而非纯 MA 回踩
        anchor = SignalExtractor.extract_entry_anchor(pattern_results, direction) if pattern_results else {}
        anchor_level = anchor.get('level')
        anchor_source = anchor.get('source')

        intraday = IntradayVSAService().analyze_entry_quality(
            self.timeframes['hourly'],
            direction=direction,
            anchor_level=anchor_level,
        )

        if anchor_level and anchor_level > 0:
            tolerance = max(anchor_level * 0.015, 0.01)
            if direction == 'long':
                near_anchor = abs(current_price - anchor_level) <= tolerance or current_price <= anchor_level * 1.01
                anchor_note = f'回踩{anchor_source}@{anchor_level:.2f}'
            else:
                near_anchor = abs(current_price - anchor_level) <= tolerance or current_price >= anchor_level * 0.99
                anchor_note = f'反抽{anchor_source}@{anchor_level:.2f}'
            has_entry = near_anchor and low_volume
            if has_entry:
                entry_quality = 'excellent'
            elif intraday.get('available') and intraday.get('entry_quality') == 'excellent':
                has_entry = True
                entry_quality = 'excellent'
            elif intraday.get('available') and intraday.get('entry_quality') == 'good':
                entry_quality = 'good'
                has_entry = near_anchor and (
                    low_volume or intraday.get('no_supply') or intraday.get('no_demand')
                )
            elif near_anchor:
                entry_quality = 'good'
            else:
                entry_quality = 'fair'
            return {
                'has_entry': has_entry,
                'entry_quality': entry_quality,
                'current_price': round(current_price, 2),
                'anchor_level': round(anchor_level, 2),
                'anchor_source': anchor_source,
                'volume_ratio': round(vol_ratio, 2),
                'intraday_vsa': intraday,
                'note': intraday.get('note') or (
                    f'小时线{anchor_note}，量比{vol_ratio:.2f}x' + (' ✓ 威科夫入场' if has_entry else '，等待缩量确认')
                ),
            }

        # 回退：无日线锚点时用近期高低点 + 缩量
        recent_low = float(df['Low'].tail(12).min())
        recent_high = float(df['High'].tail(12).max())
        if direction == 'long':
            near_support = current_price <= recent_low * 1.01
            has_entry = near_support and low_volume
        else:
            near_resistance = current_price >= recent_high * 0.99
            has_entry = near_resistance and low_volume
        intraday_fallback = IntradayVSAService().analyze_entry_quality(
            self.timeframes['hourly'],
            direction=direction,
            anchor_level=recent_low if direction == 'long' else recent_high,
        )
        if intraday_fallback.get('entry_quality') == 'excellent':
            has_entry = True
            entry_quality = 'excellent'
        elif intraday_fallback.get('entry_quality') == 'good' and entry_quality == 'unknown':
            entry_quality = 'good'
        return {
            'has_entry': has_entry,
            'entry_quality': entry_quality,
            'current_price': round(current_price, 2),
            'recent_low': round(recent_low, 2),
            'recent_high': round(recent_high, 2),
            'volume_ratio': round(vol_ratio, 2),
            'intraday_vsa': intraday_fallback,
            'note': intraday_fallback.get('note') or (
                '小时线通用缩量入场' if has_entry else '等待更好的入场点（无日线LPS/LPSY锚点）'
            ),
        }

    def _check_weekly_daily_alignment(
        self,
        weekly: Dict,
        daily: Dict,
        direction: Optional[str] = None,
    ) -> bool:
        """检查周线和日线是否对齐（含方向一致性）。"""
        weekly_dir = weekly.get('direction', 'neutral')
        daily_has_signal = daily.get('has_signal', False)
        # 除「有信号」外，还要求周线方向与交易方向一致，防止逆大势共振
        daily_dir = daily.get('direction', direction)

        if weekly_dir == 'neutral':
            return daily_has_signal

        if not daily_has_signal:
            return False

        if weekly_dir in ('long', 'short') and daily_dir in ('long', 'short'):
            if weekly_dir != daily_dir:
                return False

        if direction in ('long', 'short') and daily_dir in ('long', 'short'):
            if direction != daily_dir:
                return False

        return daily.get('signal_quality') in ['strong', 'medium']

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

    def _build_evr_context(self, pattern_results: Optional[Dict] = None) -> Dict[str, bool]:
        """从主链 events_detected 提取 EVR 共现事件（与 effort_result 同源）。"""
        from .signal_extractor import SignalExtractor

        if not pattern_results:
            return {
                'spring_detected': False,
                'upthrust_detected': False,
                'joc_detected': False,
                'fti_detected': False,
                'sow_detected': False,
            }

        events = pattern_results.get('events_detected') if isinstance(pattern_results, dict) else {}
        spring = SignalExtractor.get_event_dict(events, 'spring')
        upthrust = SignalExtractor.get_event_dict(events, 'upthrust')
        return {
            'spring_detected': SignalExtractor._detected(spring)
                and not SignalExtractor._spring_lifecycle_failed(spring),
            'upthrust_detected': SignalExtractor._detected(upthrust)
                and not SignalExtractor._upthrust_lifecycle_failed(upthrust),
            'joc_detected': SignalExtractor._detected(SignalExtractor.get_event_dict(events, 'joc')),
            'fti_detected': SignalExtractor._detected(SignalExtractor.get_event_dict(events, 'fti')),
            'sow_detected': SignalExtractor._detected(SignalExtractor.get_event_dict(events, 'sow')),
        }

    def _detect_weekly_evr(self) -> bool:
        """周线 EVR：巨量但窄幅（停止行为）。"""
        weekly = self.timeframes.get('weekly')
        if weekly is None or len(weekly) < 2:
            return False
        try:
            recent = weekly.tail(2)
            if len(recent) < 2:
                return False
            curr, prev = recent.iloc[-1], recent.iloc[-2]
            vol_ratio = curr['Volume'] / max(prev['Volume'], 1e-9)
            spread = curr['High'] - curr['Low']
            prev_spread = prev['High'] - prev['Low']
            spread_ratio = spread / max(prev_spread, 1e-9)
            return vol_ratio > 1.5 and spread_ratio < 0.8
        except Exception as exc:
            logger.debug(f"周线 EVR 检测失败: {exc}")
            return False

    def _evaluate_evr_resonance(
        self,
        evr_context: Dict[str, bool],
        weekly_evr: bool,
        daily_analysis: Dict,
    ) -> Dict[str, Any]:
        """跨周期 EVR + Spring/Upthrust 共现共振（对齐 effort_result._add_weekly_resonance_to_evr）。"""
        has_spring = evr_context.get('spring_detected', False)
        has_upthrust = evr_context.get('upthrust_detected', False)
        co_detected = weekly_evr and (has_spring or has_upthrust)
        tag = None
        if co_detected:
            tag = 'Spring' if has_spring else 'Upthrust'
        return {
            'weekly_evr': weekly_evr,
            'spring_detected': has_spring,
            'upthrust_detected': has_upthrust,
            'has_co_detection': co_detected,
            'boost': co_detected,
            'note': (
                f"周线 EVR + 日线{tag} 共现，信号可靠性提升"
                if co_detected else
                ("周线 EVR 触发" if weekly_evr else "无 EVR 跨周期共振")
            ),
            'daily_signal_type': daily_analysis.get('signal_type'),
        }

    def _generate_resonance_recommendation(
        self,
        level: str,
        weekly: Dict,
        daily: Dict,
        hourly: Dict,
        direction: Optional[str] = None,
        pattern_results: Optional[Dict] = None,
        evr_resonance: Optional[Dict] = None,
    ) -> str:
        """生成基于共振的交易建议"""
        evr_context = self._build_evr_context(pattern_results)
        evr_note = ''
        if evr_resonance and evr_resonance.get('boost'):
            evr_note = f" {evr_resonance.get('note', '')}。"

        # 孟氏 checklist 门控
        if direction == 'long' and evr_context.get('spring_detected') and not evr_context.get('joc_detected'):
            return (
                "日线 Spring 无 JOC 确认，三级共振暂缓。"
                "孟氏 checklist：等待 JOC 突破小溪后再积极入场。"
                + evr_note
            )
        if direction == 'short' and evr_context.get('upthrust_detected'):
            if not evr_context.get('fti_detected') and not evr_context.get('sow_detected'):
                return (
                    "日线 Upthrust 无 FTI/SOW 确认，三级共振暂缓。"
                    "建议等待冰层跌破或 SOW 结构确认。"
                    + evr_note
                )

        if level == 'strong':
            base = (
                f"三级共振确立！周线{weekly['trend']}，日线{daily['signal_type']}，"
                f"小时线入场质量{hourly['entry_quality']}。建议积极入场。"
            )
            if direction == 'long' and not evr_context.get('joc_detected'):
                base = (
                    f"三级结构对齐但缺 JOC 确认。周线{weekly['trend']}，"
                    f"日线{daily['signal_type']}，建议等待 JOC 或 LPS 回测后再入场。"
                )
            return base + evr_note
        elif level == 'medium':
            missing = []
            if not self._check_weekly_daily_alignment(weekly, daily, direction=direction):
                missing.append("周线日线对齐")
            if not self._check_daily_hourly_alignment(daily, hourly):
                missing.append("日线小时线对齐")

            return f"部分共振（{' + '.join(missing)}缺失）。建议等待更好的时机。" + evr_note
        else:
            if evr_resonance and evr_resonance.get('boost'):
                return f"EVR 跨周期共振出现，但三级结构未完全对齐。建议谨慎观察。" + evr_note
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
