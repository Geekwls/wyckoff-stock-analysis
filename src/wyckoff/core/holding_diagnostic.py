"""
持仓健康诊断

复用已有的 TR/Phase/Events 检测能力，对持仓个股做结构化诊断。
"""
from typing import Dict, List, Optional, Any
import pandas as pd
from .signal_extractor import SignalExtractor, get_events_from_phase


class HoldingDiagnostic:
    """单只持仓的结构化诊断"""

    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.pd = analyzer.pattern_detector

    def diagnose(self, cost: Optional[float] = None) -> Dict[str, Any]:
        """输出持仓诊断结果"""
        if not self.pd:
            return {"status": "data_not_ready"}

        price = self.analyzer.data['Close'].iloc[-1]
        pnl = ((price - cost) / cost * 100) if cost and cost > 0 else None

        phase_res = self.pd.identify_phase()
        events = get_events_from_phase(phase_res)
        tr = SignalExtractor.get_event_dict(events, 'trading_range')
        spring_res = SignalExtractor.get_event_dict(events, 'spring')
        sos_res = SignalExtractor.get_event_dict(events, 'sos')
        joc_res = SignalExtractor.get_event_dict(events, 'joc')
        lps_res = SignalExtractor.get_event_dict(events, 'lps')
        lpsy_res = SignalExtractor.get_event_dict(events, 'lpsy')

        spring = spring_res.get('detected', False)
        sos = sos_res.get('detected', False)
        has_joc = joc_res.get('detected', False)
        spring_failed = SignalExtractor._spring_lifecycle_failed(spring_res) if spring else False

        ma20 = self.analyzer.data['MA20'].iloc[-1] if 'MA20' in self.analyzer.data.columns else None
        ma50 = self.analyzer.data['MA50'].iloc[-1] if 'MA50' in self.analyzer.data.columns else None
        ma200 = self.analyzer.data['MA200'].iloc[-1] if 'MA200' in self.analyzer.data.columns else None

        if all(x is not None for x in [ma20, ma50, ma200]):
            if price > ma20 > ma50 > ma200:
                ma_pattern = "多头排列(强势)"
            elif ma20 > ma50:
                ma_pattern = "短期向上(中期承压)"
            elif ma20 < ma50 < ma200:
                ma_pattern = "空头排列"
            else:
                ma_pattern = "均线交织"
        else:
            ma_pattern = "数据不足"

        phase = SignalExtractor.get_effective_phase(phase_res)

        if 'Markup' in phase:
            channel = "主升通道"
            action = "持有或逢回调加仓"
        elif 'Accumulation' in phase:
            channel = "吸筹通道"
            action = "低位持有，等待Spring/SOS确认"
            if spring_failed:
                action = "Spring失效，减仓或观望"
            elif has_joc:
                action = "JOC突破确认，持有或逢LPS加仓"
            elif 'Phase C' in phase and spring:
                action = "Spring震仓已现，等待JOC突破确认"
            elif 'Phase D' in phase:
                action = "突破确认，持有为主"
        elif 'Distribution' in phase:
            channel = "派发通道"
            action = "减仓或离场"
            if lpsy_res.get('detected'):
                action = "LPSY出现，必须减仓"
        else:
            channel = "趋势通道"
            action = "按趋势方向操作"

        exit_signals = []
        if spring:
            latest = SignalExtractor._latest(spring_res)
            spring_low = None
            if isinstance(latest, dict):
                spring_low = latest.get('breakdown_price') or latest.get('support_level')
            if spring_low and price < float(spring_low) * 0.97:
                exit_signals.append("Spring失效，跌破Spring低点")
            elif spring_failed:
                exit_signals.append("Spring lifecycle 已失效")
            elif tr and price < tr.get('low', 0) * 0.97:
                exit_signals.append("跌破TR下沿，结构弱化")
        if lpsy_res.get('detected'):
            exit_signals.append("检测到LPSY")
        if phase_res.get('divergence', {}).get('detected'):
            exit_signals.append("顶背离")

        return {
            "price": round(price, 2),
            "pnl_pct": round(pnl, 2) if pnl is not None else None,
            "phase": phase,
            "channel": channel,
            "ma_pattern": ma_pattern,
            "tr_support": round(tr.get('low', 0), 2) if tr else None,
            "tr_resistance": round(tr.get('high', 0), 2) if tr else None,
            "tr_quality": tr.get('_quality', None) if tr else None,
            "tr_method": tr.get('_method', None) if tr else None,
            "tr_atr_threshold": tr.get('_atr_threshold', None) if tr else None,
            "signals": {
                "spring": spring,
                "sos": sos,
                "joc": has_joc,
                "lps": lps_res.get('detected', False),
                "lpsy": lpsy_res.get('detected', False),
            },
            "exit_signals": exit_signals,
            "action": action,
            "position_in_tr": round(tr.get('position', 0.5), 3) if tr else None,
        }
