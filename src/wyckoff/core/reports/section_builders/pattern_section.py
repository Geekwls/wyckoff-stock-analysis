from .base_builder import BaseSectionBuilder

class PatternSection(BaseSectionBuilder):
    """构建形态检测区块 (TR, Spring, SOS/SOW, LPS)"""
    def build(self, trading_range: dict, spring: dict, upthrust: dict, sos: dict, sow: dict, lps: dict, lpsy: dict, phase_str: str) -> str:
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
        if 'filters_passed' in spring:
            return f"""
[YES] 检测到Spring（孟洪涛5滤网）:
   日期: {spring.get('date', 'N/A')}
   最低价: {spring.get('low', 0):.2f}
   收盘价: {spring.get('close', 0):.2f}
   成交量倍数: {spring.get('volume_ratio', 0):.1f}x
   通过滤网: {spring.get('filters_passed', 0)}/5
   置信度: {spring.get('confidence', 0):.0f}%
"""
        latest = spring['latest_spring']
        return f"""
[YES] 检测到Spring:
   日期: {latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else latest['date']}
   跌破价: {latest['breakdown_price']:.2f}
   支撑位: {latest['support_level']:.2f}
   收回价: {latest['recovery_price']:.2f}
"""

    def _fmt_upthrust(self, upthrust) -> str:
        latest = upthrust['latest_upthrust']
        return f"""
[YES] 检测到Upthrust:
   日期: {latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else latest['date']}
   突破价: {latest['breakout_price']:.2f}
   回落价: {latest['rejection_price']:.2f}
   收盘距高点: {latest['close_from_high']*100:.1f}%
"""

    def _fmt_sos(self, sos) -> str:
        # 安全地获取latest数据
        if hasattr(sos, 'latest'):
            latest = sos.latest
        elif isinstance(sos, dict) and 'latest' in sos:
            latest = sos['latest']
        else:
            latest = sos

        # 安全地获取类型和其他属性
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

        if st == 'ut':
            return f"""
[!] 检测到UT/UTAD（派发阶段的向上突破）:
   日期: {date}
   价格: {price:.2f}
   成交量倍数: {volume_ratio:.1f}x
   警告：这是派发阶段的假突破，通常会回落
"""
        return f"""
[YES] 检测到SOS（Sign of Strength）:
   日期: {date}
   价格: {price:.2f}
   成交量倍数: {volume_ratio:.1f}x
   涨幅: {price_change*100:.1f}%
"""

    def _fmt_sow(self, sow) -> str:
        # 安全地获取latest数据
        if hasattr(sow, 'latest'):
            latest = sow.latest
        elif isinstance(sow, dict) and 'latest' in sow:
            latest = sow['latest']
        else:
            latest = sow

        # 安全地获取属性
        if hasattr(latest, 'get'):
            date = latest.get('date', 'N/A')
            price = latest.get('price', 0)
            price_change = latest.get('price_change', 0)
        else:
            date = getattr(latest, 'date', 'N/A')
            price = getattr(latest, 'price', 0)
            price_change = getattr(latest, 'price_change', 0)

        return f"""
[YES] 检测到SOW（Sign of Weakness）:
   日期: {date}
   价格: {price:.2f}
   跌幅: {price_change*100:.1f}%
"""

    def _fmt_lps(self, lps) -> str:
        return f"""
[YES] 检测到LPS（Last Point of Support）:
   价格: {lps.get('price', 0):.2f}
   建议做多入场点
"""

    def _fmt_lpsy(self, lpsy) -> str:
        return f"""
[!] 检测到LPSY（Last Point of Supply）:
   价格: {lpsy.get('price', 0):.2f}
   弱势反弹信号：价格已跌破支撑后的反弹回测
"""
