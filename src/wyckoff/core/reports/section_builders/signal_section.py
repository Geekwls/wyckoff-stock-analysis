from .base_builder import BaseSectionBuilder

class SignalSection(BaseSectionBuilder):
    """构建新威科夫高级信号区块 (JOC, FTI, VSA, 枯燥区)"""
    def build(self, joc: dict, fti: dict, vsa: dict, boring_res: dict, dead_corner: dict) -> str:
        report = ""
        
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
        has_advanced = joc.get('detected') or fti.get('detected') or any(
            vsa.get(k, {}).get('detected') for k in ('no_supply', 'no_demand', 'stopping_vol')
        )
        if has_advanced:
            report += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【新威科夫信号（孟洪涛）】\n"

        if joc.get('detected'):
            joc_date = joc['date'].strftime('%Y-%m-%d') if hasattr(joc['date'], 'strftime') else str(joc['date'])
            test_info = ""
            if joc.get('test_detected') and joc.get('test_date') is not None:
                td = joc['test_date'].strftime('%Y-%m-%d') if hasattr(joc['test_date'], 'strftime') else str(joc['test_date'])
                test_info = f"\n   回测确认: {td}（缩量{joc.get('test_vol_ratio', 0):.2f}x） ✓"
            else:
                test_info = "\n   回测确认: 等待回测（Test of JOC）中"
            
            confidence = joc.get('confidence', 0) * 100 if isinstance(joc.get('confidence'), (int, float)) else 75
            report += f"""
🚀 检测到JOC（跃过小溪 / Jump Across the Creek）:
   日期: {joc_date}
   小溪阻力位: {joc['creek_level']:.2f}
   突破收盘: {joc['close_price']:.2f} (+{joc['breakout_pct']:.1f}%)
   成交量: {joc['volume_ratio']:.1f}x 均量{test_info}
   置信度: {confidence:.0f}%
   趋势跟踪买入信号（等待缩量回测 JOC 位入场）
"""

        if fti.get('detected'):
            fti_date = fti['date'].strftime('%Y-%m-%d') if hasattr(fti['date'], 'strftime') else str(fti['date'])
            test_info = ""
            if fti.get('test_detected') and fti.get('test_date') is not None:
                td = fti['test_date'].strftime('%Y-%m-%d') if hasattr(fti['test_date'], 'strftime') else str(fti['test_date'])
                test_info = f"\n   回测确认: {td}（无需求反弹 {fti.get('test_vol_ratio', 0):.2f}x） ✓ 最佳做空点"
            else:
                test_info = "\n   回测确认: 等待无需求反弹（Test of Ice）中"
            report += f"""
🔻 检测到FTI（跌破冰层 / Fall Through the Ice）:
   日期: {fti_date}
   冰层支撑位: {fti['ice_level']:.2f}
   跌破收盘: {fti['close_price']:.2f} ({fti['breakdown_pct']:.1f}%)
   成交量: {fti['volume_ratio']:.1f}x 均量{test_info}
   置信度: {fti['confidence']*100:.0f}%
   做空警示信号（等待缩量回测冰层位入场）
"""

        vsa_lines = []
        for k, icon, label in [('no_supply', '[OK]', 'No Supply（无供应）'), ('no_demand', '[ERR]', 'No Demand（无需求）'), ('stopping_vol', '[WARN]', 'Stopping Volume（停止行为）')]:
            sig = vsa.get(k, {})
            if sig.get('detected'):
                d = sig['date'].strftime('%Y-%m-%d') if hasattr(sig.get('date'), 'strftime') else str(sig.get('date', ''))
                vsa_lines.append(f"   {icon} {label}: {d} 量比{sig.get('vol_ratio', 0):.2f}x → 辅助确认")
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
        return report
