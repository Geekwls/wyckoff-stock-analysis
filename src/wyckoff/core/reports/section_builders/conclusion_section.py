from .base_builder import BaseSectionBuilder

class ConclusionSection(BaseSectionBuilder):
    """构建报告结论、因果测算、冲突警告及证伪区块"""
    def build(self, phase_result: dict, trading_range: dict, cause_effect: dict, conflict: dict, 
              quality_data: dict, joc: dict, spring: dict, sos: dict, lps: dict, fti: dict, 
              upthrust: dict, sow: dict, lpsy: dict, mtf: dict, boring_res: dict, 
              dead_corner: dict, market_env: str) -> str:
        
        phase_str = phase_result.get('phase', 'Unknown')
        phase_conf = phase_result.get('confidence', 0.0)
        current_price = self.data['Close'].iloc[-1]
        
        report = ""
        
        # Cause & Effect
        report += self._build_cause_effect(cause_effect, trading_range)
        
        # Conflict Warning
        if conflict.get('has_conflict'):
            report += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【跨周期冲突警告】
[!] 日线方向与周/月趋势冲突，已触发仲裁降级
   日线: {conflict.get('daily_side')} | 周线: {conflict.get('weekly_trend')} | 月线: {conflict.get('monthly_trend')}
   仲裁动作: 延迟执行，等待跨周期一致后再开仓。
"""

        # Core Conclusion
        report += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【核心结论】\n"
        
        # 信号质量检查
        quality_score = quality_data.score if hasattr(quality_data, 'score') else quality_data.get('score', 0)
        max_score = quality_data.max_score if hasattr(quality_data, 'max_score') else quality_data.get('max_score', 10)
        
        post_breakout = self._check_post_breakout_state(trading_range, joc, current_price)
        
        if quality_score < 4 or phase_conf < 0.5 or conflict.get('has_conflict'):
            report += f"⏸️ 观望等待（信号质量不足）:\n   当前评分: {quality_score}/{max_score} | 置信度: {phase_conf*100:.0f}%\n   结论: 信号强度或可靠性低于执行阈值，建议继续观察。\n"
            if post_breakout: report += f"\n{post_breakout}"
        else:
            # 详细结论逻辑 (简化版，实际应用中可根据需要扩充)
            is_distribution = 'Distribution' in phase_str or '派发' in phase_str
            if post_breakout: report += post_breakout
            
            if joc.get('detected') and joc.get('test_detected') and not is_distribution:
                joc_entry = joc.get('creek_level', current_price)
                target2 = cause_effect.get('targets', {}).get('target_2', current_price * 1.15)
                report += f"🚀 趋势跟踪买入（JOC 突破确认）:\n   参考入场区间: {joc_entry:.2f} ~ {joc_entry * 1.02:.2f}\n   止损: {joc_entry * 0.96:.2f} | 目标2: {target2:.2f}\n"
            elif lps.get('detected') and not is_distribution:
                lp = lps.get('price', current_price)
                report += f"[YES] 做多机会（LPS 最后支撑）:\n   入场价格: {lp:.2f} | 止损: {lp * 0.95:.2f}\n"
            elif fti.get('detected') and fti.get('test_detected'):
                report += f"🔻 做空/减仓警示（FTI 跌破确认）\n"
            elif trading_range.get('is_consolidation'):
                report += "⏳ 观望等待: 横盘整理阶段，等待信号。\n"
            else:
                report += "⏸️ 无明显信号: 建议继续观察。\n"

        # Falsification
        report += self._build_falsification(phase_str, trading_range)
        
        return report

    def _build_cause_effect(self, cause_effect, trading_range) -> str:
        if not cause_effect or 'targets' not in cause_effect: return ''
        tr_high, tr_low = trading_range.get('high', 0), trading_range.get('low', 0)
        current_price = self.data['Close'].iloc[-1]
        
        if trading_range.get('is_broken'):
            direction = trading_range.get('breakout_direction', 'unknown')
            return f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【因果测算 - 待重新锚定】\n原区间: {tr_low:.2f} - {tr_high:.2f}（已被{direction}突破至{current_price:.2f}）\n状态: 原TR已失效，旧因果目标不再适用\n"

        t1, t2 = cause_effect['targets'].get('target_1', 0), cause_effect['targets'].get('target_2', 0)
        return f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【因果测算】\n交易区间: {tr_low:.2f} - {tr_high:.2f}\n突破方向: {cause_effect.get('breakout_direction', '待定')}\n目标1 (保守 1.0×): {t1:.2f}\n目标2 (正常 1.618×): {t2:.2f}\n"

    def _check_post_breakout_state(self, trading_range, joc, current_price) -> str:
        if not trading_range.get('is_broken'): return ''
        direction = trading_range.get('breakout_direction', 'unknown')
        tr_high, tr_low = trading_range.get('high', 0), trading_range.get('low', 0)
        if direction == 'up':
            if joc.get('test_detected'): return f"【突破后状态 - 回测确认】\n   价格已突破TR上沿{tr_high:.2f}至{current_price:.2f}，且回测已确认。\n"
            return f"【突破后状态 - JOC推进中】\n   价格已突破TR上沿{tr_high:.2f}至{current_price:.2f}，JOC已触发。\n"
        return f"【突破后状态 - 向下突破】\n   价格已跌破TR下沿{tr_low:.2f}至{current_price:.2f}。\n"

    def _build_falsification(self, phase_str, trading_range) -> str:
        tr_high, tr_low = trading_range.get('high', 0), trading_range.get('low', 0)
        return f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【逻辑证伪点】\n💡 顶级交易计划不仅告诉你什么情况下你对了，更明确告诉你什么情况下你判断错了。\n[!] 观察要点:\n   • 关键阻力位: {tr_high:.2f}元\n   • 关键支撑位: {tr_low:.2f}元\n"
