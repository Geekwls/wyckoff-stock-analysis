from .base_builder import BaseSectionBuilder

class PatternSection(BaseSectionBuilder):
    """构建形态检测区块 (TR, PS, PSY, Spring, SOS/SOW, LPS)"""
    def build(self, trading_range: dict, spring: dict, upthrust: dict, sos: dict, sow: dict, lps: dict, lpsy: dict, phase_str: str, ps: dict = None, psy: dict = None) -> str:
        text = "【形态检测】\n"
        
        # Trading Range
        if trading_range.get('is_broken'):
            direction = trading_range.get('breakout_direction', 'unknown')
            text += f"""
[!] 原交易区间已被突破（{direction}突破）
    原区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
    幅度: {trading_range['range_pct']*100:.1f}%
    当前价格: {trading_range['current_price']:.2f}（已超出区间边界）
    状态: 原区间已失效，因果目标待重新锚定
"""
        elif trading_range.get('is_consolidation'):
            text += f"""
[YES] 检测到交易区间:
    区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
    幅度: {trading_range['range_pct']*100:.1f}%
    当前位置: {trading_range['position']*100:.0f}% (0%=底部, 100%=顶部)
    成交量趋势: {trading_range['volume_trend']}
"""
        # Climax Confirmation (P1 #6)
        climax = trading_range.get('climax', {})
        if isinstance(climax, dict) and climax.get('detected'):
            status = "✅ 已确认" if climax.get('is_confirmed') else "⏳ 待确认"
            text += f"""
[i] {climax.get('type','Climax')} 检测:
    日期: {climax.get('date')}
    价格: {climax.get('price', 0):.2f}
    确认状态: {status}
    说明: {'反弹已收复实体跌幅50%，确认为底部高潮。' if climax.get('is_confirmed') and climax.get('type')=='selling_climax' else 'AR尚未有效跌破BC前支撑，确认为顶部高潮。' if climax.get('is_confirmed') else '反弹强度不足或尚未回测，需警惕。'}
"""
        # Preliminary Signals (P1 #7)
        if ps and ps.get('detected'):
            text += f"""
[YES] 检测到初次支撑 (PS):
    日期: {ps.get('date')}
    价格: {ps.get('ps_price', 0):.2f}
    信心: {ps.get('confidence')}%
    说明: 出现放量止跌迹象，代表大资金开始尝试抄底。
"""
        if psy and psy.get('detected'):
            text += f"""
[YES] 检测到初次供应 (PSY):
    日期: {psy.get('date')}
    价格: {psy.get('price', 0):.2f}
    信心: {psy.get('confidence')}%
    说明: 出现初步抛压，上涨动力开始受到阻碍。
"""

        # Spring & Upthrust - 安全检查
        if spring is not None:
            spring_detected = spring.detected if hasattr(spring, 'detected') else spring.get('detected', False)
            if spring_detected:
                text += self._fmt_spring(spring)

        if upthrust is not None:
            upthrust_detected = upthrust.detected if hasattr(upthrust, 'detected') else upthrust.get('detected', False)
            if upthrust_detected:
                text += self._fmt_upthrust(upthrust)

        # SOS & SOW - 安全检查
        if sos is not None:
            sos_detected = sos.detected if hasattr(sos, 'detected') else sos.get('detected', False)
            sos_latest = sos.latest if hasattr(sos, 'latest') else sos.get('latest', True)
            if sos_detected and sos_latest:
                text += self._fmt_sos(sos)

        if sow is not None:
            sow_detected = sow.detected if hasattr(sow, 'detected') else sow.get('detected', False)
            sow_latest = sow.latest if hasattr(sow, 'latest') else sow.get('latest', True)
            if sow_detected and sow_latest:
                text += self._fmt_sow(sow)

        # LPS & LPSY
        if lps.get('detected'):
            text += self._fmt_lps(lps)
        if lpsy.get('detected'):
            text += self._fmt_lpsy(lpsy)
            
        return text

    def _fmt_spring(self, spring) -> str:
        latest = spring['latest_spring']
        s_type = latest.get('spring_type', 2)
        s_desc = latest.get('type_description', f"{s_type}号 Spring")
        status_label = latest.get('lifecycle_status', 'active')
        status_note = ""
        if status_label == 'failed': status_note = " (⚠️ 信号已证伪)"
        elif status_label == 'confirmed': status_note = " (🚀 强势确认)"
        
        return f"""
[YES] 检测到Spring:
   日期: {latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else latest['date']}
   跌破价: {latest['breakdown_price']:.2f}
   支撑位: {latest['support_level']:.2f}
   收回价: {latest['recovery_price']:.2f}
   状态: {status_label}{status_note}
   类型: {s_desc}
"""

    def _fmt_upthrust(self, upthrust) -> str:
        latest = upthrust['latest_upthrust']
        ut_type = latest.get('upthrust_type', 2)
        ut_desc = latest.get('type_description', f"{ut_type}号 Upthrust")
        
        is_utad = 'UTAD' in str(ut_desc) or '派发后' in str(ut_desc)
        advice = "🔻 派发阶段终极做空信号 (UTAD)，建议逢高做空。" if is_utad else "中性。"

        return f"""
[YES] 检测到Upthrust:
   日期: {latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else latest['date']}
   突破价: {latest['breakout_price']:.2f}
   回落价: {latest['rejection_price']:.2f}
   收盘距高点: {latest['close_from_high']*100:.1f}%
   类型: {ut_desc}
   操作建议: {advice}
"""

    def _fmt_sos(self, sos) -> str:
        if hasattr(sos, 'latest'):
            latest = sos.latest
        elif isinstance(sos, dict) and 'latest' in sos:
            latest = sos['latest']
        else:
            latest = sos

        if hasattr(latest, 'get'):
            st = latest.get('type', 'sos')
            date = latest.get('date', 'N/A')
            price = latest.get('price', 0)
            volume_ratio = latest.get('volume_ratio', 0)
            price_change = latest.get('price_change', 0)
        else:
            st = getattr(latest, 'type', 'sos')
            date = getattr(latest, 'date', 'N/A')
            price = getattr(latest, 'price', 0)
            volume_ratio = getattr(latest, 'volume_ratio', 0)
            price_change = getattr(latest, 'price_change', 0)

        return f"""
[YES] 检测到SOS（Sign of Strength）:
   日期: {date}
   价格: {price:.2f}
   成交量倍数: {volume_ratio:.1f}x
   涨幅: {price_change*100:.1f}%
"""

    def _fmt_sow(self, sow) -> str:
        if isinstance(sow, dict):
            signal_type = sow.get('signal_type', 'unknown')
            interpretation = sow.get('interpretation', '')
            date = sow.get('date', 'N/A')
            price = sow.get('price', 0)
            price_change = sow.get('price_change', 0)

            label = "SOW（Sign of Weakness）" if signal_type == 'true_sow' else "区间内弱势"
            icon = "YES" if signal_type == 'true_sow' else "?"

            return f"""
[{icon}] 检测到{label}:
   日期: {date}
   价格: {price:.2f}
   跌幅: {price_change*100:.1f}%
   说明: {interpretation}
"""
        return "[?] 检测到弱势信号（格式异常）"

    def _fmt_lps(self, lps) -> str:
        latest = lps.get('latest', {}) if isinstance(lps, dict) else lps
        price = latest.get('price', 0) if isinstance(latest, dict) else 0
        signal_type = latest.get('signal_type', 'unknown') if isinstance(latest, dict) else 'unknown'
        note = latest.get('note', '') if isinstance(latest, dict) else ''

        if signal_type == 'lps':
            return f"""
[YES] 检测到LPS（Last Point of Support）:
   价格: {price:.2f}
   建议做多入场点
"""
        return f"""
[?] 检测到类似LPS信号 ({signal_type}):
   价格: {price:.2f}
   {note}
"""

    def _fmt_lpsy(self, lpsy) -> str:
        return f"""
[!] 检测到LPSY（Last Point of Supply）:
   价格: {lpsy.get('price', 0):.2f}
   弱势反弹信号：价格已跌破支撑后的反弹回测
"""
