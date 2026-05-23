from .base_builder import BaseSectionBuilder

class SignalSection(BaseSectionBuilder):
    """构建新威科夫高级信号区块 (JOC, FTI, VSA, 枯燥区)"""
    def build(self, joc: dict, fti: dict, vsa: dict, boring_res: dict, dead_corner: dict) -> str:
        report = ""
        vsa = vsa or {}
        boring_res = boring_res or {}
        dead_corner = dead_corner or {}

        def _get(obj, key, default=None):
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        def _detected(obj):
            return bool(_get(obj, 'detected', False))

        def _latest(obj):
            for key in ('latest', 'latest_spring', 'latest_upthrust'):
                val = _get(obj, key)
                if val:
                    return val
            signals = _get(obj, 'signals', []) or []
            return signals[-1] if signals else None

        def _date_str(value):
            return value.strftime('%Y-%m-%d') if hasattr(value, 'strftime') else str(value)

        def _num(value, default=0.0):
            if isinstance(value, dict):
                value = value.get('value', default)
            elif hasattr(value, 'value'):
                value = getattr(value, 'value')
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        
        # Boring Zone Warning
        if boring_res.get('detected') or boring_res.get('score', 0) >= 70:
            status = "🔥 高能预警" if boring_res.get('high_alert') else "⚡ 深度关注"
            report += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【{status}：孟洪涛枯燥区】
   状态: 检测到显著枯燥区
   评分: {boring_res['score']}/100
   量能萎缩: {boring_res['vol_contraction']*100:.0f}%
   波动收敛: {boring_res['atr_contraction']*100:.0f}%
   预警等级: {"死角突破临界" if boring_res.get('high_alert') else "能量积蓄中"}
"""
            if dead_corner.get('detected'):
                report += f"""
   >>> 🎯 [实战确认] 死角突破已发生！
       突破价: {dead_corner['breakout_price']}
       量比: {dead_corner['breakout_volume_ratio']:.1f}x
"""

        # Advanced Signals (JOC, FTI, VSA)
        # 安全地检查FTI和JOC
        joc_detected = _detected(joc)
        fti_detected = _detected(fti)

        has_advanced = joc_detected or fti_detected or any(
            _detected(vsa.get(k, {})) for k in ('no_supply', 'no_demand', 'stopping_vol')
        )
        if has_advanced:
            report += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【新威科夫信号（孟洪涛）】\n"

        # 安全地获取JOC信息
        if joc is not None:
            if _detected(joc):
                joc_data = _latest(joc) or joc
                joc_date = _date_str(_get(joc_data, 'date', 'N/A'))
                test_info = ""
                if _get(joc_data, 'test_detected') and _get(joc_data, 'test_date') is not None:
                    td = _date_str(_get(joc_data, 'test_date'))
                    test_info = f"\n   回测确认: {td}（缩量{_num(_get(joc_data, 'test_vol_ratio')):.2f}x） ✓"
                else:
                    test_info = "\n   回测确认: 等待回测（Test of JOC）中"

                confidence = _num(_get(joc_data, 'confidence'), 0.75) * 100
                report += f"""
🚀 检测到JOC（跃过小溪 / Jump Across the Creek）:
   日期: {joc_date}
   小溪阻力位: {_num(_get(joc_data, 'creek_level')):.2f}
   突破收盘: {_num(_get(joc_data, 'close_price')):.2f} (+{_num(_get(joc_data, 'breakout_pct')):.1f}%)
   成交量: {_num(_get(joc_data, 'volume_ratio')):.1f}x 均量{test_info}
   回测质量: {_get(joc_data, 'test_quality', 'N/A')} ({_num(_get(joc_data, 'test_score')):.0f}分)
   置信度: {confidence:.0f}%
   操作建议: {'🎯 质量极佳，可在回测确认后积极入场。' if _get(joc_data, 'test_quality')=='HIGH' else '趋势跟踪买入信号（等待缩量回测 JOC 位入场）。'}
"""

        # 安全地获取FTI信息
        if fti is not None:
            if _detected(fti):
                fti_data = _latest(fti) or fti
                fti_date = _date_str(_get(fti_data, 'date', 'N/A'))
                test_info = ""
                if _get(fti_data, 'test_detected') and _get(fti_data, 'test_date') is not None:
                    td = _date_str(_get(fti_data, 'test_date'))
                    test_info = f"\n   回测确认: {td}（无需求反弹 {_num(_get(fti_data, 'test_vol_ratio')):.2f}x） ✓ 最佳做空点"
                else:
                    test_info = "\n   回测确认: 等待无需求反弹（Test of Ice）中"
                report += f"""
🔻 检测到FTI（跌破冰层 / Fall Through the Ice）:
   日期: {fti_date}
   冰层支撑位: {_num(_get(fti_data, 'ice_level')):.2f}
   跌破收盘: {_num(_get(fti_data, 'close_price')):.2f} ({_num(_get(fti_data, 'breakdown_pct')):.1f}%)
   成交量: {_num(_get(fti_data, 'volume_ratio')):.1f}x 均量{test_info}
   置信度: {_num(_get(fti_data, 'confidence'))*100:.0f}%
   做空警示信号（等待缩量回测冰层位入场）
"""

        vsa_lines = []
        for k, icon, label in [('no_supply', '[OK]', 'No Supply（无供应）'), ('no_demand', '[ERR]', 'No Demand（无需求）'), ('stopping_vol', '[WARN]', 'Stopping Volume（停止行为）')]:
            sig = vsa.get(k, {})
            if _detected(sig):
                sig_detail = _latest(sig) or sig
                d = _date_str(_get(sig_detail, 'date', ''))
                quality = _get(sig, 'quality') or _get(sig_detail, 'quality')
                note = _get(sig, 'note') or _get(sig_detail, 'note')
                vol_ratio = _get(sig_detail, 'vol_ratio', _get(sig_detail, 'volume_ratio', _get(sig, 'vol_ratio', 0)))
                quality_note = f" [{quality.upper()}]" if quality else ""
                vsa_lines.append(f"   {icon} {label}: {d} 量比{_num(vol_ratio):.2f}x{quality_note}")
                if note:
                    vsa_lines.append(f"      └─ {note}")

        # Bag Holding (接盘) 信号
        bag = vsa.get('bag_holding', {})
        if bag.get('detected'):
            d = bag['date'].strftime('%Y-%m-%d') if hasattr(bag.get('date'), 'strftime') else str(bag.get('date', ''))
            vsa_lines.append(f"   [🔥] Bag Holding（接盘）: {d} 量比{bag.get('vol_ratio', 0):.2f}x → 大资金全力进场接盘")

        # Shakeout (震仓) 信号
        shakeout = vsa.get('shakeout', {})
        if shakeout.get('detected'):
            d = shakeout['date'].strftime('%Y-%m-%d') if hasattr(shakeout.get('date'), 'strftime') else str(shakeout.get('date', ''))
            depth = shakeout.get('depth', 0)
            vsa_lines.append(f"   [⚡] Shakeout（震仓）: {d} 深度{depth:.1f}% → 剧烈洗盘后快速回收")

        # Divergence (背离) 信号
        divergence = vsa.get('divergence', {})
        if divergence.get('detected'):
            dtype = divergence.get('type', 'unknown')
            d_label = '顶背离' if dtype == 'top_divergence' else '底背离' if dtype == 'bottom_divergence' else '背离'
            conf = divergence.get('confidence', 0) * 100
            vsa_lines.append(f"   [🔄] Divergence（{d_label}）: 置信度{conf:.0f}% → 趋势减弱信号")

        # Volume Trend (成交量趋势)
        vol_trend = vsa.get('volume_trend', {})
        if vol_trend and vol_trend.get('trend') != 'unknown':
            trend_labels = {
                'expanding': ('📈', '放量趋势', '资金积极参与'),
                'contracting': ('📉', '缩量趋势', '市场观望情绪'),
                'stable': ('➡️', '成交量平稳', '市场处于平衡状态')
            }
            icon, tlabel, meaning = trend_labels.get(vol_trend.get('trend'), ('❓', vol_trend.get('trend', ''), ''))
            strength = vol_trend.get('strength', 0)
            vsa_lines.append(f"   {icon} {tlabel}: 强度{strength:.0f}/100 → {meaning}")

        # WIE 3.0 微观结构信号
        wie3_summary = vsa.get('wie3_summary', {})
        if wie3_summary:
            if wie3_summary.get('is_hidden_absorption'):
                vsa_lines.append(f"   [🔍] Hidden Absorption（隐藏吸收）: EvR={wie3_summary.get('evr_divergence', 0):.2f}, CLV={wie3_summary.get('clv', 0):.2f} → 主力暗中吸收")
            if wie3_summary.get('is_supply_dominance'):
                vsa_lines.append(f"   [⚠️] Supply Dominance（供应主导）: Spread-Z={wie3_summary.get('spread_zscore', 0):.2f}, CLV={wie3_summary.get('clv', 0):.2f} → 供应占优")

        if vsa_lines:
            report += "\n📊 VSA辅助信号（量价微观分析）:\n" + "\n".join(vsa_lines) + "\n"

        # Boring Analysis Detailed
        report += f"""
【枯燥区分析】
枯燥区评分: {boring_res.get('score', 0)}/100 
量能收缩比: {boring_res.get('vol_contraction', 1.0)*100:.1f}%
波动收敛比: {boring_res.get('atr_contraction', 1.0)*100:.1f}%
整理持续: {boring_res.get('duration', 0)} 天
结论: {'🔥 检测到高价值枯燥区，系统已进入高能预警状态。' if boring_res.get('detected') else '暂未形成典型枯燥区。'}
"""
        # RVS Integration (P2 #5)
        rvs = vsa.get('rvs', {})
        if rvs and rvs.get('status') == 'ok':
            report += f"""
【成交量相对强度 (RVS)】
强度等级: {rvs.get('label')}
个股/指数比: {rvs.get('rvs_score')}
核心解读: {rvs.get('meaning')}
"""
        return report
