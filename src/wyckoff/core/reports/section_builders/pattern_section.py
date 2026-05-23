from .base_builder import BaseSectionBuilder

class PatternSection(BaseSectionBuilder):
    """构建形态检测区块 (TR, PS, PSY, Spring, SOS/SOW, LPS)"""
    @staticmethod
    def _get(obj, key, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @classmethod
    def _detected(cls, obj) -> bool:
        return bool(cls._get(obj, 'detected', False))

    @classmethod
    def _latest(cls, obj, latest_key='latest'):
        latest = cls._get(obj, latest_key)
        if latest:
            return latest
        signals = cls._get(obj, 'signals', []) or []
        return signals[-1] if signals else None

    @staticmethod
    def _num(value, default=0.0) -> float:
        if isinstance(value, dict):
            value = value.get('value', default)
        elif hasattr(value, 'value'):
            value = getattr(value, 'value')
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _date(value):
        return value.strftime('%Y-%m-%d') if hasattr(value, 'strftime') else value

    def build(self, trading_range: dict, spring: dict, upthrust: dict, sos: dict, sow: dict, lps: dict, lpsy: dict, phase_str: str, ps: dict = None, psy: dict = None) -> str:
        text = "【形态检测】\n"
        trading_range = trading_range or {}
        
        # 深度破位寻底检查
        is_deep_breakdown = trading_range.get('position', 0) < -0.05
        
        if is_deep_breakdown:
            text += f"""
[!] 机构级形态定性：原中继交易区间（TR）已跌穿失效
    前期盘整带: {trading_range.get('low', 0):.2f} - {trading_range.get('high', 0):.2f}
    当前价格: {trading_range.get('current_price', 0):.2f} (处于大级别再分配后的弱趋势衰退区)
    状态说明: 威科夫机构视角判定，前期小盘整带有效跌穿，但并未呈现瀑布式崩塌，而是步入杀跌动能衰减钝化的大震荡衰退磨底期。在此长周期下行中，陈旧的 PSY 与前期未能阻击暴跌的 PS 均已宣告失效阵亡。盘面正处于向下方长线冰点支撑带寻求重新平衡的前夜。
"""
        elif trading_range.get('is_broken'):
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
        if not is_deep_breakdown:
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
            if self._detected(spring):
                text += self._fmt_spring(spring)

        if upthrust is not None:
            if self._detected(upthrust):
                text += self._fmt_upthrust(upthrust)

        # SOS & SOW - 安全检查
        if sos is not None:
            if self._detected(sos) and self._latest(sos):
                text += self._fmt_sos(sos)

        if sow is not None:
            if self._detected(sow) and self._latest(sow):
                text += self._fmt_sow(sow)

        # LPS & LPSY
        if self._detected(lps):
            text += self._fmt_lps(lps)
        if self._detected(lpsy):
            text += self._fmt_lpsy(lpsy)
            
        return text

    def _fmt_spring(self, spring) -> str:
        latest = self._latest(spring, 'latest_spring') or spring
        s_type = self._get(latest, 'spring_type', 2)
        s_desc = self._get(latest, 'type_description', f"{s_type}号 Spring")
        status_label = self._get(latest, 'lifecycle_status', 'active')
        status_note = ""
        if status_label == 'failed': status_note = " (⚠️ 信号已证伪)"
        elif status_label == 'confirmed': status_note = " (🚀 强势确认)"
        
        return f"""
[YES] 检测到Spring:
   日期: {self._date(self._get(latest, 'date', 'N/A'))}
   跌破价: {self._num(self._get(latest, 'breakdown_price')):.2f}
   支撑位: {self._num(self._get(latest, 'support_level')):.2f}
   收回价: {self._num(self._get(latest, 'recovery_price')):.2f}
   状态: {status_label}{status_note}
   类型: {s_desc}
"""

    def _fmt_upthrust(self, upthrust) -> str:
        latest = self._latest(upthrust, 'latest_upthrust') or upthrust
        ut_type = self._get(latest, 'upthrust_type', 2)
        ut_desc = self._get(latest, 'type_description', f"{ut_type}号 Upthrust")
        
        is_utad = 'UTAD' in str(ut_desc) or '派发后' in str(ut_desc)
        advice = "🔻 派发阶段终极做空信号 (UTAD)，建议逢高做空。" if is_utad else "中性。"

        return f"""
[YES] 检测到Upthrust:
   日期: {self._date(self._get(latest, 'date', 'N/A'))}
   突破价: {self._num(self._get(latest, 'breakout_price')):.2f}
   回落价: {self._num(self._get(latest, 'rejection_price')):.2f}
   收盘距高点: {self._num(self._get(latest, 'close_from_high'))*100:.1f}%
   类型: {ut_desc}
   操作建议: {advice}
"""

    def _fmt_sos(self, sos) -> str:
        latest = self._latest(sos) or sos
        date = self._get(latest, 'date', 'N/A')
        price = self._num(self._get(latest, 'price'))
        volume_ratio = self._num(self._get(latest, 'volume_ratio'))
        price_change = self._num(self._get(latest, 'price_change'))

        return f"""
[YES] 检测到SOS（Sign of Strength）:
   日期: {date}
   价格: {price:.2f}
   成交量倍数: {volume_ratio:.1f}x
   涨幅: {price_change*100:.1f}%
"""

    def _fmt_sow(self, sow) -> str:
        latest = self._latest(sow) or sow
        signal_type = self._get(latest, 'signal_type', self._get(sow, 'signal_type', 'unknown'))
        interpretation = self._get(sow, 'interpretation', self._get(latest, 'interpretation', ''))
        date = self._get(latest, 'date', 'N/A')
        price = self._num(self._get(latest, 'price'))
        price_change = self._num(self._get(latest, 'price_change'))

        label = "SOW（Sign of Weakness）" if signal_type == 'true_sow' else "区间内弱势"
        icon = "YES" if signal_type == 'true_sow' else "?"

        return f"""
[{icon}] 检测到{label}:
   日期: {date}
   价格: {price:.2f}
   跌幅: {price_change*100:.1f}%
   说明: {interpretation}
"""

    def _fmt_lps(self, lps) -> str:
        latest = self._latest(lps) or lps
        price = self._num(self._get(latest, 'price'))
        signal_type = self._get(latest, 'signal_type', 'unknown')
        note = self._get(latest, 'note', '')

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
        latest = self._latest(lpsy) or lpsy
        return f"""
[!] 检测到LPSY（Last Point of Supply）:
   价格: {self._num(self._get(latest, 'price')):.2f}
   弱势反弹信号：价格已跌破支撑后的反弹回测
"""
