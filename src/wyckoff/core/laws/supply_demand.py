import pandas as pd
import logging
from typing import Any
from ...config.settings import WyckoffConfig
from ..signal_extractor import SignalExtractor, get_events_from_phase, get_cached_phase_result

logger = logging.getLogger(__name__)


class SupplyDemandMixin:
    """第一定律：供求定律"""

    def analyze_supply_demand_law(self) -> dict:
        if self.data is None or len(self.data) < 60:
            from ...exceptions import InsufficientDataError
            raise InsufficientDataError("供求分析", required=60, actual=len(self.data) if self.data is not None else 0)

        df = self.data
        phase_result = get_cached_phase_result(self.pattern_detector)
        phase_obj = phase_result.get('phase_enum') or phase_result.get('phase', 'Unknown')
        from ..utils import PhaseAdapter
        is_accumulation = PhaseAdapter.is_accumulation(phase_obj)
        is_distribution = PhaseAdapter.is_distribution(phase_obj)

        # 第一定律与报告共用 events_detected；TR 缺失时才 fallback 到 detect_trading_range
        events = get_events_from_phase(phase_result)
        trading_range = SignalExtractor.get_event_dict(events, 'trading_range')
        if not trading_range.get('high') or not trading_range.get('low'):
            trading_range = self.pattern_detector.detect_trading_range()
        in_range = trading_range.get("is_consolidation", False)

        current_price = df['Close'].iloc[-1]
        current_vol = df['Volume'].iloc[-1]
        vol_ma20 = df['Volume_MA20'].iloc[-1]

        spring = SignalExtractor.get_event_dict(events, 'spring')
        upthrust = SignalExtractor.get_event_dict(events, 'upthrust')
        sos = SignalExtractor.get_event_dict(events, 'sos')
        sow = SignalExtractor.get_event_dict(events, 'sow')
        joc = SignalExtractor.get_event_dict(events, 'joc')
        fti = SignalExtractor.get_event_dict(events, 'fti')

        supply_demand_analysis = {
            "current_phase": phase_obj,
            "trading_range_status": "in_consolidation" if in_range else "trending",
            "volume_analysis": {
                "current_volume_ratio": round(current_vol / max(vol_ma20, 1), 2),
                "volume_trend": "increasing" if df['Volume'].iloc[-20:].mean() > df['Volume'].iloc[-60:-20].mean() else "decreasing"
            }
        }

        if is_accumulation:
            accumulation_stages = {
                "preliminary_support": self._detect_preliminary_support(),
                "accumulation_range": in_range,
                "absorption_pattern": self._analyze_absorption_pattern(),
                "spring_status": "detected" if spring.get('detected') else "not_detected",
                "sos_status": "detected" if sos.get('detected') else "not_detected"
            }
            if spring.get('detected') and sos.get('detected') and joc.get('detected'):
                stage = "Phase D-E (准备突破)"
                supply_demand_balance = "需求主导，准备进入上涨期"
            elif spring.get('detected') and sos.get('detected'):
                stage = "Phase C+ (SOS待JOC确认)"
                supply_demand_balance = "SOS出现，等待JOC突破小溪确认"
            elif in_range:
                stage = "Phase B-C (积累震荡)"
                supply_demand_balance = "供求平衡，主力吸筹中"
            else:
                #  缺陷11修复：加入趋势过滤，避免在下跌趋势中错误归类为 Phase A
                _df = self.data
                _recent_high = _df['High'].tail(30).max()
                _current_price = _df['Close'].iloc[-1]
                _decline_pct = (_recent_high - _current_price) / _recent_high if _recent_high > 0 else 0
                if _decline_pct > 0.15:
                    # 从近期高点下跌超过15%，仍处于下跌趋势而非 Phase A
                    stage = "Markdown (下跌趋势中)"
                    supply_demand_balance = "供应主导，尚未形成支撑区间"
                else:
                    stage = "Phase A (初步支撑)"
                    supply_demand_balance = "需求开始出现，但未确立"
            supply_demand_analysis["accumulation_analysis"] = {
                "current_stage": stage,
                "supply_demand_balance": supply_demand_balance,
                "details": accumulation_stages
            }
        elif is_distribution:
            distribution_stages = {
                "preliminary_supply": self._detect_preliminary_supply(),
                "distribution_range": in_range,
                "exhaustion_pattern": self._analyze_exhaustion_pattern(),
                "upthrust_status": "detected" if upthrust.get('detected') else "not_detected",
                "sow_status": "detected" if sow.get('detected') else "not_detected"
            }
            if upthrust.get('detected') and sow.get('detected') and fti.get('detected'):
                stage = "Phase D-E (准备下跌)"
                supply_demand_balance = "供应主导，准备进入下跌期"
            elif upthrust.get('detected') and sow.get('detected'):
                stage = "Phase C+ (SOW待FTI确认)"
                supply_demand_balance = "SOW出现，等待FTI跌破冰层确认"
            elif in_range:
                stage = "Phase B-C (派发震荡)"
                supply_demand_balance = "供求平衡，主力出货中"
            else:
                stage = "Phase A (初步阻力)"
                supply_demand_balance = "供应开始出现，但未确立"
            supply_demand_analysis["distribution_analysis"] = {
                "current_stage": stage,
                "supply_demand_balance": supply_demand_balance,
                "details": distribution_stages
            }
        else:
            current_trend = "uptrend" if df['Close'].iloc[-1] > df['MA200'].iloc[-1] else "downtrend"
            supply_demand_analysis["trend_analysis"] = {
                "current_trend": current_trend,
                "trend_strength": "strong" if current_vol / vol_ma20 > 1.5 else "moderate",
                "supply_demand_balance": "需求主导" if current_trend == "uptrend" else "供应主导"
            }
        return supply_demand_analysis

    def analyze_supply_demand_law_enhanced(self, market_context: dict = None) -> dict:
        from ...exceptions import InsufficientDataError
        if self.data is None or len(self.data) < 20:
            raise InsufficientDataError("供需定律分析", required=20, actual=len(self.data) if self.data is not None else 0)

        df = self.data
        events = None
        try:
            trading_range = self.pattern_detector.detect_trading_range()
        except Exception as e:
            logger.warning(f"检测交易区间失败: {e}")
            trading_range = {'low': df['Low'].tail(60).min(), 'high': df['High'].tail(60).max()}

        try:
            phase_result = get_cached_phase_result(self.pattern_detector)
            current_phase = phase_result.get('phase', 'Unknown') if isinstance(phase_result, dict) else str(phase_result)
            events = get_events_from_phase(phase_result)
            # 增强版供求分析同样优先读主链 TR，保证与报告展示区间一致
            tr_from_events = SignalExtractor.get_event_dict(events, 'trading_range')
            if tr_from_events:
                trading_range = tr_from_events
        except Exception as e:
            logger.warning(f"获取当前阶段失败: {e}")
            current_phase = 'Unknown'
            events = None

        enhanced_analysis = {'current_phase': current_phase, 'trading_range': trading_range}
        if 'Accumulation' in current_phase:
            enhanced_analysis['accumulation_analysis'] = self._analyze_accumulation_enhanced(
                df, trading_range, events=events
            )
        elif 'Distribution' in current_phase:
            enhanced_analysis['distribution_analysis'] = self._analyze_distribution_enhanced(
                df, trading_range, events=events
            )
        else:
            enhanced_analysis['trend_analysis'] = self._analyze_trend_enhanced(df)
        return enhanced_analysis

    def _detect_preliminary_support(self) -> dict:
        if self.data is None or len(self.data) < 20:
            return {"detected": False}
        df = self.data.tail(60)
        price_dropped = df['Close'].pct_change(5).min() < -0.08
        high_vol_on_low = (
            (df['Volume'] > df['Volume_MA20'] * 1.5) &
            (df['Close'] < df['Close'].rolling(20).mean())
        ).any()
        detected = bool(price_dropped and high_vol_on_low)
        return {
            "detected": detected,
            "description": "检测到初步支撑：急跌后出现放量承接" if detected else "未检测到明显初步支撑"
        }

    def _detect_preliminary_supply(self) -> dict:
        if self.data is None or len(self.data) < 20:
            return {"detected": False}
        df = self.data.tail(60)
        price_rallied = df['Close'].pct_change(5).max() > 0.08
        high_vol_on_high = (
            (df['Volume'] > df['Volume_MA20'] * 1.5) &
            (df['Close'] > df['Close'].rolling(20).mean())
        ).any()
        detected = bool(price_rallied and high_vol_on_high)
        return {
            "detected": detected,
            "description": "检测到初步阻力：急涨后出现放量抛售" if detected else "未检测到明显初步阻力"
        }

    def _analyze_absorption_pattern(self) -> dict:
        if self.data is None or len(self.data) < 40:
            return {"pattern": "unknown", "strength": "unknown"}
        df = self.data.tail(40)
        up_days = df[df['Close'] > df['Close'].shift(1)]
        down_days = df[df['Close'] < df['Close'].shift(1)]
        if up_days.empty or down_days.empty:
            return {"pattern": "insufficient_data", "strength": "unknown"}

        avg_up_vol = up_days['Volume'].mean()
        avg_down_vol = down_days['Volume'].mean()
        vol_ratio = avg_up_vol / avg_down_vol if avg_down_vol > 0 else 1.0

        #  缺陗10修复：加入价差(spread)同向分析
        # 真正的吸筎：上涨日量大且价差大（需求主导）+ 下跌日量小且价差小（供应耗尽）
        avg_up_spread = (up_days['High'] - up_days['Low']).mean() if len(up_days) > 0 else 1.0
        avg_down_spread = (down_days['High'] - down_days['Low']).mean() if len(down_days) > 0 else 1.0
        spread_ratio = avg_up_spread / avg_down_spread if avg_down_spread > 0 else 1.0

        # 双重确认：量和价差都需要同时满足才是真正的吸筎
        if vol_ratio > 1.3 and spread_ratio > 1.2:
            pattern, strength = "absorption", "strong"
        elif vol_ratio > 1.1 or spread_ratio > 1.1:
            pattern, strength = "mild_absorption", "medium"
        else:
            pattern, strength = "no_absorption", "weak"
        return {
            "pattern": pattern, "strength": strength,
            "up_down_vol_ratio": round(vol_ratio, 2),
            "up_down_spread_ratio": round(spread_ratio, 2)
        }

    def _analyze_exhaustion_pattern(self) -> dict:
        if self.data is None or len(self.data) < 40:
            return {"pattern": "unknown", "strength": "unknown"}
        df = self.data.tail(40)
        recent_high = df['High'].max()
        older_high = self.data.iloc[-80:-40]['High'].max() if len(self.data) >= 80 else recent_high * 0.95
        new_high = recent_high > older_high
        recent_vol = df['Volume'].mean()
        older_vol = self.data.iloc[-80:-40]['Volume'].mean() if len(self.data) >= 80 else recent_vol
        vol_declining = recent_vol < older_vol * 0.85
        if new_high and vol_declining:
            pattern, strength = "exhaustion", "strong"
        elif vol_declining:
            pattern, strength = "mild_exhaustion", "medium"
        else:
            pattern, strength = "no_exhaustion", "weak"
        return {"pattern": pattern, "strength": strength,
                "new_high": new_high, "volume_declining": vol_declining}

    def _analyze_accumulation_enhanced(self, df: pd.DataFrame, trading_range: dict, events: Any = None) -> dict:
        try:
            tr_low = trading_range.get('low', df['Low'].min())
            tr_high = trading_range.get('high', df['High'].max())
            in_tr = df[(df['Close'] >= tr_low) & (df['Close'] <= tr_high)].copy()
            if len(in_tr) == 0:
                return {'error': '无TR内数据'}
            total_vol = in_tr['Volume'].sum()
            vwap = (in_tr['Volume'] * in_tr['Close']).sum() / total_vol if total_vol > 0 else in_tr['Close'].mean()
            cumulative_volume = in_tr['Volume'].sum()
            cumulative_amount = (in_tr['Volume'] * in_tr['Close']).sum()
            vwap_position = (vwap - tr_low) / (tr_high - tr_low) if tr_high > tr_low else 0.5
            if 0.4 < vwap_position < 0.6:
                quality = 'HIGH'
                quality_description = '优质吸筹：VWAP位于TR中部，主力吸筹充分'
            elif 0.3 < vwap_position < 0.7:
                quality = 'MEDIUM'
                quality_description = '中等吸筹：VWAP位于TR中上部'
            else:
                quality = 'LOW'
                quality_description = '劣质吸筹：VWAP偏离TR中心'
            in_tr['price_range'] = pd.cut(in_tr['Close'], bins=5, labels=['底部', '中下部', '中部', '中上部', '顶部'])
            volume_by_price = in_tr.groupby('price_range', observed=True)['Volume'].sum()
            if events is None:
                events = get_events_from_phase(get_cached_phase_result(self.pattern_detector))
            spring = SignalExtractor.get_event_dict(events, 'spring')
            sos = SignalExtractor.get_event_dict(events, 'sos')
            if spring.get('detected') and sos.get('detected'):
                stage = 'Phase D-E (准备突破)'
                stage_description = '吸筹接近尾声，准备进入上涨期'
            elif spring.get('detected'):
                stage = 'Phase C (震仓确认)'
                stage_description = '震仓完成，主力控盘'
            else:
                stage = 'Phase A-B (吸筹初期)'
                stage_description = '主力吸筹阶段'
            return {
                'vwap': round(vwap, 2),
                'cumulative_volume': round(cumulative_volume, 0),
                'cumulative_amount': round(cumulative_amount, 0),
                'vwap_position': round(vwap_position, 3),
                'quality': quality,
                'quality_description': quality_description,
                'volume_distribution_by_price': {k: round(v, 0) for k, v in volume_by_price.items()},
                'accumulation_stage': stage,
                'stage_description': stage_description,
                'spring_detected': spring.get('detected', False),
                'sos_detected': sos.get('detected', False)
            }
        except Exception as e:
            logger.error(f"吸筹期分析失败: {e}")
            return {'error': str(e)}

    def _analyze_distribution_enhanced(self, df: pd.DataFrame, trading_range: dict, events: Any = None) -> dict:
        try:
            tr_low = trading_range.get('low', df['Low'].min())
            tr_high = trading_range.get('high', df['High'].max())
            in_tr = df[(df['Close'] >= tr_low) & (df['Close'] <= tr_high)].copy()
            if len(in_tr) == 0:
                return {'error': '无TR内数据'}
            total_vol = in_tr['Volume'].sum()
            vwap = (in_tr['Volume'] * in_tr['Close']).sum() / total_vol if total_vol > 0 else in_tr['Close'].mean()
            cumulative_volume = in_tr['Volume'].sum()
            vwap_position = (vwap - tr_low) / (tr_high - tr_low) if tr_high > tr_low else 0.5
            if vwap_position > 0.6:
                quality = 'HIGH'
                quality_description = '优质派发：VWAP位于TR上部，主力高位出货'
            elif vwap_position > 0.4:
                quality = 'MEDIUM'
                quality_description = '中等派发：VWAP位于TR中部'
            else:
                quality = 'LOW'
                quality_description = '劣质派发：VWAP位于TR下部'
            if events is None:
                events = get_events_from_phase(get_cached_phase_result(self.pattern_detector))
            upthrust = SignalExtractor.get_event_dict(events, 'upthrust')
            sow = SignalExtractor.get_event_dict(events, 'sow')
            if upthrust.get('detected') and sow.get('detected'):
                stage = 'Phase D-E (准备下跌)'
                stage_description = '派发接近尾声，准备进入下跌期'
            elif upthrust.get('detected'):
                stage = 'Phase C (假突破确认)'
                stage_description = '假突破完成，主力出货'
            else:
                stage = 'Phase A-B (派发初期)'
                stage_description = '主力派发阶段'
            return {
                'vwap': round(vwap, 2),
                'cumulative_volume': round(cumulative_volume, 0),
                'vwap_position': round(vwap_position, 3),
                'quality': quality,
                'quality_description': quality_description,
                'distribution_stage': stage,
                'stage_description': stage_description,
                'upthrust_detected': upthrust.get('detected', False),
                'sow_detected': sow.get('detected', False)
            }
        except Exception as e:
            logger.error(f"派发期分析失败: {e}")
            return {'error': str(e)}

    def _analyze_trend_enhanced(self, df: pd.DataFrame) -> dict:
        try:
            current_price = df['Close'].iloc[-1]
            ma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else None
            ma50 = df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else None
            if ma200:
                trend = 'uptrend' if current_price > ma200 else 'downtrend'
            else:
                trend = 'unknown'
            recent_vol = df['Volume'].tail(20).mean()
            historical_vol = df['Volume'].tail(60).mean()
            volume_ratio = recent_vol / historical_vol if historical_vol > 0 else 1
            strength = 'strong' if volume_ratio > 1.5 else 'moderate' if volume_ratio > 1.0 else 'weak'
            return {
                'current_trend': trend,
                'trend_strength': strength,
                'volume_ratio': round(volume_ratio, 2),
                'current_price': round(current_price, 2),
                'ma200': round(ma200, 2) if ma200 else None,
                'ma50': round(ma50, 2) if ma50 else None
            }
        except Exception as e:
            logger.error(f"趋势分析失败: {e}")
            return {'error': str(e)}
