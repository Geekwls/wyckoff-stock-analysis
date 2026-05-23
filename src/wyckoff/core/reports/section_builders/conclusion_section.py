import logging
from typing import Dict, Any
from .base_builder import BaseSectionBuilder
from ...sos_sow_analyzer import SOSSOWAnalyzer

logger = logging.getLogger(__name__)

class ConclusionSection(BaseSectionBuilder):
    """构建报告结论、因果测算、冲突警告及证伪区块"""
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

    def build(self, phase_result: dict, trading_range: dict, cause_effect: dict, conflict: dict,
              quality_data: dict, joc: dict, spring: dict, sos: dict, lps: dict, fti: dict,
              upthrust: dict, sow: dict, lpsy: dict, mtf: dict, boring_res: dict,
              dead_corner: dict, market_env: dict, arbitration_result: dict = None,
              breakout_analysis: dict = None, sos_sow_analysis: dict = None,
              wie3_market_state = None) -> str:

        phase_str = phase_result.get('phase', 'Unknown')
        phase_conf = phase_result.get('confidence', 0.0)
        self._phase_result = phase_result
        current_price = self.data['Close'].iloc[-1]

        report = ""

        # === WIE 3.0 MVP 机构级微观结构状态 ===
        if wie3_market_state:
            report += self._build_wie3_mvp_section(wie3_market_state)

        #  新增：计算健康回测区间（用于后续推荐）
        retest_zone = None
        if trading_range and trading_range.get('is_broken'):
            breakout_level = self._get_tr_value(trading_range, 'high', current_price * 0.9)
            #  修复：LPS返回结构中price字段在latest里
            lps_price = 0
            if lps:
                latest = self._latest(lps) or lps
                lps_price = self._num(self._get(latest, 'price', 0))
            retest_zone = self._calculate_healthy_retest_zone(current_price, breakout_level, lps_price)

        # === 事件仲裁结果 ===
        if arbitration_result:
            report += self._build_arbitration_section(arbitration_result)

        # === SOS-SOW矛盾分析 ===
        if sos_sow_analysis and sos_sow_analysis.get('has_conflict'):
            report += SOSSOWAnalyzer.format_conflict_report(sos_sow_analysis)

        #  新增：TR突破后的重新评估
        if trading_range and trading_range.get('is_broken'):
            report += self._build_tr_breakdown_reassessment(trading_range, phase_result, breakout_analysis)

            #  新增：显示突破质量分析
            if breakout_analysis and breakout_analysis.get('is_breakout'):
                report += self._build_breakout_quality_section(breakout_analysis, trading_range)

        # Cause & Effect
        report += self._build_cause_effect(cause_effect, trading_range, sos_sow_analysis)
        
        # Conflict Warning
        if conflict.get('has_conflict'):
            report += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【跨周期冲突警告】
[!] 日线方向与周/月趋势冲突，已触发仲裁降级
   日线: {conflict.get('daily_side')} | 周线: {conflict.get('weekly_trend')} | 月线: {conflict.get('monthly_trend')}
   仲裁动作: 延迟执行，等待跨周期一致后再开仓。
"""

        # Market Context (P0 Optimization)
        report += self._build_market_context_section(market_env)

        # 增加信号冲突自检逻辑 (JOC/Spring/SOS 与 Upthrust/SOW/FTI 共存时)
        has_bullish_signal = self._detected(joc) or self._detected(spring) or self._detected(sos)
        has_bearish_signal = self._detected(upthrust) or self._detected(sow) or self._detected(fti)
        if has_bullish_signal and has_bearish_signal:
            report += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【⚠️ 信号冲突警示：市场多空分歧剧烈】
💡 威科夫提醒：当前盘面在相同周期内同时检测到了强烈的多头信号与空头信号，反映出大资金 (Composite Operator) 内部多空分歧极其剧烈，或者市场正处于诱多/诱空的敏感过渡带。
建议：
- 严格遵循观望纪律，绝对不可轻举妄动。
- 等待价格突破或跌破关键防守轴并确认后再作右侧跟随。
"""

        # Core Conclusion
        report += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【核心结论】\n"
        
        # 信号质量检查
        quality_score = quality_data.score if hasattr(quality_data, 'score') else quality_data.get('score', 0)
        max_score = quality_data.max_score if hasattr(quality_data, 'max_score') else quality_data.get('max_score', 10)
        
        post_breakout = self._check_post_breakout_state(trading_range, joc, current_price)

        #  修复矛盾三：检查突破覆盖 - 向上突破应该否决派发判断
        breakout_override = False
        if breakout_analysis and trading_range:
            is_broken = False
            if isinstance(trading_range, dict):
                is_broken = trading_range.get('is_broken', False)
            elif hasattr(trading_range, 'is_broken'):
                is_broken = trading_range.is_broken

            if is_broken:
                direction = breakout_analysis.get('direction', '')
                is_upthrust = breakout_analysis.get('is_upthrust', False)
                # 向上突破 + 非Upthrust = 真实突破，覆盖派发判断
                if direction == 'up' and not is_upthrust:
                    breakout_override = True
                    logger.info(f"Conclusion: Using breakout override - upward breakout negates Distribution phase")

        #  基于高时间框架优先原则的仲裁逻辑
        is_weekly_bullish = conflict.get('weekly_trend') == 'bullish'
        # 安全地检查fti是否为模型对象或dict
        fti_detected = self._detected(fti)
        is_daily_bearish = ('Distribution' in phase_str or 'Markdown' in phase_str or fti_detected) and not breakout_override

        #  新增：检查SOW信号，判断区间是否被破坏
        sow_broke_tr = False
        if sow is not None:
            sow_detected = self._detected(sow)
            if sow_detected:
                latest_sow = self._latest(sow) or sow
                signal_type = self._get(latest_sow, 'signal_type', self._get(sow, 'signal_type', ''))
                sow_price = self._num(self._get(latest_sow, 'price', self._get(sow, 'price', 0)))
                sow_low = self._num(self._get(latest_sow, 'low', self._get(sow, 'low', sow_price)))
                tr_low = self._get_tr_value(trading_range, 'low', 0)

                # 判断SOW是否跌破区间下沿
                if signal_type == 'true_sow' or (sow_low > 0 and sow_low < tr_low):
                    sow_broke_tr = True

        # 如果SOW破坏了区间，显示威科夫逻辑警告
        if sow_broke_tr and trading_range and trading_range.get('is_consolidation'):
            tr_low = self._get_tr_value(trading_range, 'low', 0)
            tr_high = self._get_tr_value(trading_range, 'high', 0)

            report += f"""
【⚠️ 威科夫逻辑警告：区间结构已破坏】

原交易区间({tr_low:.2f}-{tr_high:.2f}元)已被SOW破坏：

1. **区间边界神圣性原则**
   - 4月22日放量跌破区间下沿{tr_low:.2f}元
   - 威科夫理论：区间边界被放量跌破 = 区间结构失效
   - 结论：不能再称为"再吸筹区间"

2. **当前真实状态**
   - 价格{current_price:.2f}元是"区间破位后的反弹测试"
   - 不是再吸筹，而是在测试原区间的压力
   - 可能是下跌趋势的中继反弹（"死猫跳"）

3. **三种可能情景**
   情况A：下跌中继 - 在25-26元遇阻后继续下跌
   情况B：新结构形成 - 在22.26-25.11元形成新区间
   情况C：Spring陷阱 - 缺少完整吸筹前置结构

4. **严格观望策略**
   ❌ 当前{current_price:.2f}元不是入场点
   ✅ 等待市场明确信号：
      - 若情况A：跌破22.26元后的新底部
      - 若情况B：新区间结构完整
      - 若情况C：完整Phase A（SC→AR→ST）

5. **威科夫理论核心原则**
   "一旦区间被放量跌破，原区间即失效。
   不能简单下移区间边界，必须重新观察结构形成。"

"""

            return report

        if conflict.get('has_conflict') and is_weekly_bullish and is_daily_bearish:
            #  修复：严格派发逻辑 - 绝不在派发阶段建议做多
            if ('Distribution' in phase_str or '派发' in phase_str) and not breakout_override:
                report += f"""
⏸️ 严格观望（派发阶段确认）:
   当前状态: 日线确认{phase_str}，表明主力正在出货。
   尽管周/月线大趋势看多，但派发阶段的定义是主力资金流出。

   ⛔ 禁止操作:
   - 绝对禁止在此位置做多（避免接主力筹码）
   - 谨慎做空（除非AR/ST结构完整）

   ✅ 推荐策略:
   - 严格观望，等待派发结束确认
   - 关注关键支撑: {self._get_tr_value(trading_range, 'low'):.2f}元
   - 等待明确的LPS（最后支撑点）或新的Spring信号
   - 确认派发结束后再考虑入场
"""
            else:
                # 非派发阶段的跨周期冲突处理
                report += f"""
⏸️ 战略观望（等待趋势一致）:
   当前状态: 日线出现{phase_str}信号，但周/月线大趋势仍然看多。
   建议: 等待日线止跌迹象或跨周期趋势一致后再做决策。
"""
        #  新增：优先检查突破质量和JOC测试状态（连接突破质量与交易决策）
        # 如果有STRONG突破，优先使用突破决策逻辑，即使整体信号质量低
        if breakout_analysis and breakout_analysis.get('is_breakout'):
            # 检查突破质量是否为STRONG
            breakout_quality = breakout_analysis.get('quality', 'unknown')
            quality_score_val = breakout_analysis.get('quality_score', 0)
            if isinstance(quality_score_val, dict):
                score = quality_score_val.get('score', 0)
            else:
                score = quality_score_val

            # STRONG突破（评分>=80）优先使用突破决策逻辑
            if breakout_quality in ['strong', 'very_strong'] or score >= 80:
                report += self._build_breakout_decision(breakout_analysis, current_price, trading_range, quality_score, max_score)
                # Falsification
                report += self._build_falsification(phase_str, trading_range)
                return report
            # 其他情况继续使用原有逻辑
            elif quality_score < 4 or phase_conf < 0.5:
                report += f"⏸️ 观望等待（信号质量不足）:\n   当前评分: {quality_score}/{max_score} | 置信度: {phase_conf*100:.0f}%\n   结论: 信号强度或可靠性低于执行阈值，建议继续观察。\n"
                if post_breakout:
                    report += f"\n{post_breakout}"

        # 检查单边向下破位寻底模式
        tr_low = self._get_tr_value(trading_range, 'low', 0)
        tr_high = self._get_tr_value(trading_range, 'high', 0)
        is_breakdown = False
        if tr_low > 0:
            tr_height = tr_high - tr_low
            if current_price < tr_low - 0.1 * tr_height or current_price < tr_low * 0.97:
                is_breakdown = True

        # 如果处于单边下行破位寻底状态，直接给出单边观望结论
        if is_breakdown:
            min_52w = self.data['Low'].tail(250).min() if len(self.data) >= 50 else current_price * 0.88
            report += f"""⏸️ 机构级战略观望 (弱趋势衰退带 / 波动率塌缩磨底前夜):
   当前定性: 现价 {current_price:.2f} 元处于前期中继盘整下沿 {tr_low:.2f} 元下方，定性为大级别派发后的弱趋势衰退带 (Markdown 尾段 → 波动压缩 → 空头效率下降 → 长期再平衡前夜)。特别提示：“前夜”绝不等于“已经见底”。
   操盘纪律: 杀跌动能虽大幅衰竭钝化，但在未见主力放量重夺关键位 (SOS) 前严禁重仓抢反弹。所有上涨绝对优先按 LPSY 对待。牢记远端低位 ({min_52w:.2f}元附近) 仅为大资金需求观察区而非必达目标，大底建构乃漫长“时间事件”，需严格等待建筹五要件 (SC+AR+ST+Spring+带量重夺SOS) 齐备。
"""
            report += self._build_falsification(phase_str, trading_range)
            return report

        # 原有逻辑
        if conflict.get('has_conflict') and is_weekly_bullish and is_daily_bearish:
            #  修复：严格派发逻辑 - 绝不在派发阶段建议做多
            if 'Distribution' in phase_str or '派发' in phase_str:
                report += f"""
⏸️ 严格观望（派发阶段确认）:
   当前状态: 日线确认{phase_str}，表明主力正在出货。
   尽管周/月线大趋势看多，但派发阶段的定义是主力资金流出。

   ⛔ 禁止操作:
   - 绝对禁止在此位置做多（避免接主力筹码）
   - 谨慎做空（除非AR/ST结构完整）

   ✅ 推荐策略:
   - 严格观望，等待派发结束确认
   - 关注关键支撑: {self._get_tr_value(trading_range, 'low'):.2f}元
   - 等待明确的LPS（最后支撑点）或新的Spring信号
   - 确认派发结束后再考虑入场
"""
            else:
                # 非派发阶段的跨周期冲突处理
                report += f"""
⏸️ 战略观望（等待趋势一致）:
   当前状态: 日线出现{phase_str}信号，但周/月线大趋势仍然看多。
   建议: 等待日线止跌迹象或跨周期趋势一致后再做决策。
"""
        elif quality_score < 4 or phase_conf < 0.5:
            report += f"⏸️ 观望等待（信号质量不足）:\n   当前评分: {quality_score}/{max_score} | 置信度: {phase_conf*100:.0f}%\n   结论: 信号强度或可靠性低于执行阈值，建议继续观察。\n"
            if post_breakout:
                report += f"\n{post_breakout}"
        else:
            # 详细结论逻辑
            is_distribution = 'Distribution' in phase_str or '派发' in phase_str
            if post_breakout:
                report += post_breakout

            if self._detected(joc) and self._get(joc, 'test_detected') and not is_distribution:
                joc_entry = self._num(self._get(joc, 'creek_level', current_price), current_price)
                target2 = cause_effect.get('targets', {}).get('target_2', current_price * 1.15)
                report += f"🚀 趋势跟踪买入（JOC 突破确认）:\n   参考入场区间: {joc_entry:.2f} ~ {joc_entry * 1.02:.2f}\n   止损: {joc_entry * 0.96:.2f} | 目标2: {target2:.2f}\n"
            elif self._detected(lps) and not is_distribution:
                #  修复：LPS返回结构中price字段在latest里，且需要检查signal_type
                latest = self._latest(lps) or lps
                signal_type = self._get(latest, 'signal_type', 'unknown')
                lp = self._num(self._get(latest, 'price', current_price), current_price)

                # 只有正式LPS（signal_type='lps'）才显示为"做多机会"
                if signal_type == 'lps':
                    report += f"[YES] 做多机会（LPS 最后支撑）:\n   入场价格: {lp:.2f} | 止损: {lp * 0.95:.2f}\n"
                elif signal_type == 'support_test':
                    report += f"[?] 观察支撑测试:\n   价格: {lp:.2f}（非正式LPS，需等待确认）\n"
                else:
                    report += f"⏸️ 观察过渡回踩 ({signal_type}):\n   价格: {lp:.2f}（非标准买点信号，建议继续观望）\n"
            elif self._detected(fti) and self._get(fti, 'test_detected'):
                report += f"🔻 做空/减仓警示（FTI 跌破确认）\n"
            elif trading_range.get('is_consolidation'):
                report += "⏳ 观望等待: 横盘整理阶段，等待信号。\n"
            else:
                report += "⏸️ 无明显信号: 建议继续观察。\n"

        # Falsification
        report += self._build_falsification(phase_str, trading_range)

        return report

    def _build_breakout_decision(
        self,
        breakout_analysis: dict,
        current_price: float,
        trading_range: dict,
        quality_score: int,
        max_score: int
    ) -> str:
        """
        基于突破质量和JOC测试状态给出交易决策

        连接"突破质量评估"和"交易建议"的逻辑链条
        """
        direction = breakout_analysis.get('direction', 'unknown')
        quality = breakout_analysis.get('quality', 'unknown')
        is_upthrust = breakout_analysis.get('is_upthrust', False)
        joc_test = breakout_analysis.get('joc_test_status', {})
        breakout_level = self._get_tr_value(trading_range, 'high', current_price * 0.9)

        report = ""

        if direction == 'up' and not is_upthrust:
            # 向上突破情况
            test_status = joc_test.get('interpretation', 'unknown')

            if test_status == 'healthy_test':
                #  STRONG突破 + 已确认Test of JOC → 做多信号
                test_price = joc_test.get('test_price', 0)
                report += f"""✅ 强势突破 + 回测确认 → 做多信号:
   【交易路径】
   1. ✓ 突破质量：{quality.upper()}（突破有效）
   2. ✓ Test of JOC：已确认（回测至{test_price:.2f}元后企稳）
   3. ✓ 威科夫逻辑：原阻力转为支撑，需求守稳

   【操作建议】
   • 入场时机：当前（回测已确认，需求确认）
   • 参考价位：{current_price:.2f}元附近
   • 止损位：{breakout_level * 0.95:.2f}元（跌破突破位5%）
   • 理由：STRONG突破后的健康回测是最佳入场点

   【风险提示】
   当前评分: {quality_score}/{max_score}（关注其他信号质量）
"""
            elif test_status == 'no_test_yet':
                # ⏳ STRONG突破 + 未回测 → 策略选择
                distance_pct = joc_test.get('current_distance_from_breakout', 0)

                #  修复：计算策略B的合理止损位（基于次级支撑）
                # 威科夫风控原则：止损应基于最近的支撑结构
                rally_range = current_price - breakout_level
                secondary_support = current_price - (rally_range * 0.382)  # 斐波那契38.2%回调

                # 策略A的止损：基于原突破位
                stop_loss_a = breakout_level * 0.95
                risk_a = (breakout_level * 1.02 - stop_loss_a) / (breakout_level * 1.02)

                # 策略B的止损：基于次级支撑
                stop_loss_b = secondary_support * 0.95  # 次级支撑下方5%
                risk_b = (current_price - stop_loss_b) / current_price

                report += f"""⏳ 强势突破，等待回测确认:
   【突破状态】
   1. ✓ 突破质量：{quality.upper()}（需求主导）
   2. ⏳ Test of JOC：尚未发生
   3. 📊 当前距离突破位：+{distance_pct:.1f}%

   【交易路径选择】

   策略A - 保守等待（威科夫正统）⭐⭐⭐⭐⭐:
   • 入场时机：回测{breakout_level:.2f}元附近
   • 确认条件：缩量企稳 + 需求承接
   • 止损位：{stop_loss_a:.2f}元（突破位下方5%）
   • 风险幅度：约{risk_a*100:.1f}%
   • 优势：最佳风险收益比，止损明确
   • 风险：可能踏空（若不回测直接上涨）

   策略B - 激进入场（严格风控）⭐⭐⭐:
   • 入场时机：当前价位{current_price:.2f}元小仓试探
   • 建仓位：20-30%（严格控仓）
   • 止损位：{stop_loss_b:.2f}元（次级支撑{secondary_support:.2f}元下方5%）
   • 风险幅度：{risk_b*100:.1f}%（可接受）
   • 加仓位：回测{breakout_level:.2f}元附近加至70-80%
   • 优势：不错过行情，风险可控
   • 风险：若出现UT需果断止损

   【止损逻辑对比】
   策略A止损：{stop_loss_a:.2f}元（基于原突破位{breakout_level:.2f}元）
            → 风险{risk_a*100:.1f}% ✓ 优秀

   策略B止损：{stop_loss_b:.2f}元（基于次级支撑{secondary_support:.2f}元）
            → 风险{risk_b*100:.1f}% ✓ 合理

   ❌ 错误做法：策略B止损设为{breakout_level * 0.95:.2f}元
             → 风险{(current_price - breakout_level * 0.95) / current_price * 100:.1f}% ✗ 过大！

   【威科夫风控原则】
   • 止损必须基于"最近的支撑结构"
   • 策略A：原突破位转为支撑（最强）
   • 策略B：次级支撑（斐波那契回调位）
   • 避免"一刀切"的止损设置

   【UT风险监控】⚠️
   当前处于高位区域（+{distance_pct:.1f}%），需警惕：
   • 放量滞涨：上涨乏力，需求耗尽
   • 快速回落+放量：供应涌出
   • 跌破次级支撑{secondary_support:.2f}元：UT确认
   → 出现上述信号，策略B应立即止损

   【建议】
   威科夫理论偏好Test of JOC确认后的入场点。当前突破质量为{quality.upper()}，
   但无回测确认的突破存在两种可能：
   1. 直接上涨（踏空风险）
   2. 高位需求耗尽回落（UT风险）

   推荐策略A：等待回测至{breakout_level:.2f}元附近并缩量企稳。
   若选择策略B：必须严格执行{stop_loss_b:.2f}元止损，不可放宽！
"""
            elif test_status == 'approaching_test':
                #  正在接近回测区间
                target_zone = joc_test.get('target_zone', '')
                report += f"""🔔 价格接近回测区间，准备入场:
   【当前状态】
   1. ✓ 突破质量：{quality.upper()}
   2. 🔔 Test of JOC：正在进行
   3. 📍 回测目标区：{target_zone}元

   【操作建议】
   • 密切关注价格在{target_zone}元的表现
   • 理想情况：缩量回测 + 快速企稳
   • 入场时机：回测企稳后，出现需求承接信号
   • 止损位：跌破回测区间下沿

   【威科夫逻辑】
   突破后的回测是对"原阻力→支撑"的验证，是最佳入场时机。
"""
            elif test_status == 'risky_test':
                # ⚠️ 回测但量价不健康
                test_price = joc_test.get('test_price', 0)
                report += f"""⚠️ 突破后回测，但信号质量欠佳:
   【当前状态】
   1. ✓ 突破质量：{quality.upper()}
   2. ⚠️ Test of JOC：{test_price:.2f}元，但放量或疲弱

   【风险提示】
   回测时成交量未能萎缩，或价格表现疲弱，可能是：
   - 供应持续流出
   - 突破缺乏有效需求支撑

   【建议】
   • 观望等待更明确的企稳信号
   • 或等待价格重新站上{breakout_level:.2f}元
   • 当前不适合入场
"""
        elif is_upthrust:
            # ⚠️ Upthrust（假突破）
            report += f"""⚠️ 疑似Upthrust（假突破），不建议追涨:
   【突破分析】
   • 突破质量：{quality.upper()}（但被判定为Upthrust）
   • 威科夫判断：可能是冲高诱多

   【建议】
   • 等待回测原TR上沿{breakout_level:.2f}元确认
   • 若快速回落跌破{breakout_level:.2f}元，确认Upthrust
   • 警惕高位追涨被套
"""

        return report

    def _build_tr_breakdown_reassessment(
        self,
        trading_range: dict,
        phase_result: dict,
        breakout_analysis: dict = None
    ) -> str:
        """
        构建TR突破后的重新评估区块

        当价格突破原交易区间时，需要重新评估市场状态
        """
        direction = trading_range.get('breakout_direction', 'unknown')
        current_price = trading_range.get('current_price', 0)
        tr_low = trading_range.get('low', 0)
        tr_high = trading_range.get('high', 0)

        report = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        report += "【⚠️ 交易区间突破 - 重新评估】\n\n"

        if direction == 'up':
            report += f"原交易区间（{tr_low:.2f}-{tr_high:.2f}）已向上突破至{current_price:.2f}元\n\n"

            # 如果有突破质量分析，整合进来
            if breakout_analysis and not breakout_analysis.get('is_upthrust', False):
                quality = breakout_analysis.get('quality', 'unknown')
                report += f"突破质量：{quality.upper()}（{breakout_analysis.get('quality_score', 0)}/100）\n\n"

            #  新增：计算并显示健康回测区间
            breakout_level = tr_high
            lps_price = 0  # We don't have LPS info here, could be passed as parameter
            retest_zone = self._calculate_healthy_retest_zone(current_price, breakout_level, lps_price)

            report += "原区间逻辑失效，需要重新评估市场状态：\n\n"
            report += "1. **原区间内的'派发'判断被价格行为否决**\n"
            report += f"   - 向上突破{((current_price - tr_high) / tr_high * 100):.1f}%至{current_price:.2f}元\n"
            report += "   - 派发阶段的特征应是向下突破，实际相反\n\n"

            if breakout_analysis and breakout_analysis.get('is_upthrust', False):
                report += "2. **当前状态：疑似Upthrust（冲高诱多）**\n"
                report += "   - 突破可能是假信号，需警惕快速回落\n"
                report += f"   - 建议等待回测原区间上沿{tr_high:.2f}元确认\n\n"
            else:
                report += "2. **当前状态：趋势推进（可能为Reaccumulation Phase C/D）**\n"
                report += "   - 价格行为支持上升趋势延续\n"
                report += "   - 原TR可能是上升趋势中的再吸筹区间\n\n"

            report += "3. **策略调整**：\n"
            report += "   ❌ 撤销基于'派发阶段'的所有交易建议\n"

            #  新增：显示健康回测区间（基于威科夫理论）
            if retest_zone:
                explanation = retest_zone.get('explanation', '')
                target_range = retest_zone.get('target_range', f"{retest_zone['healthy_low']:.2f} - {retest_zone['healthy_high']:.2f}")

                report += f"\n4. **威科夫Test of JOC（回测目标）**：\n"
                report += f"   📍 回测目标区间：{target_range}元\n"
                report += f"   💡 威科夫逻辑：{explanation}\n"

                if retest_zone.get('is_deep_pullback_warning'):
                    report += f"   ⚠️ 警告：若价格跌破{retest_zone['breakdown_level']:.2f}元，突破失效\n"
                else:
                    report += f"   ✓ 突破失效位：{retest_zone['breakdown_level']:.2f}元（跌破此位趋势破坏）\n"

            report += "\n5. **下一步行动**：\n"
            report += "   ✅ 等待价格回测至上述区间\n"
            report += "   ✅ 确认回测时缩量（健康回测特征）\n"
            report += "   ✅ 回测企稳后考虑做多入场\n\n"

        elif direction == 'down':
            report += f"原交易区间（{tr_low:.2f}-{tr_high:.2f}）已向下突破\n\n"

            #  新增：判断当前价格是否反弹回区间内
            has_reentered = tr_low < current_price < tr_high

            if has_reentered:
                # 区间破位后反弹回到区间内
                report += f"当前状态：价格在{current_price:.2f}元，已反弹回原区间内\n\n"

                if breakout_analysis:
                    quality = breakout_analysis.get('quality', 'unknown')
                    quality_score = breakout_analysis.get('quality_score', 0)
                    #  修复：quality_score可能是int或dict
                    if isinstance(quality_score, dict):
                        score_val = quality_score.get('score', 0)
                    else:
                        score_val = quality_score
                    report += f"突破质量：{quality.upper()}（{score_val}/100）\n\n"

                report += "【⚠️ 威科夫逻辑警告】\n\n"
                report += "1. **原区间结构已被破坏**\n"
                report += f"   - 放量跌破区间下沿{tr_low:.2f}元（SOW）\n"
                report += f"   - 区间{tr_low:.2f}-{tr_high:.2f}元的结构已失效\n"
                report += f"   - 不能再称为'再吸筹区间'\n\n"

                report += "2. **当前状态：区间破位后的反弹测试**\n"
                report += f"   - 价格从低位反弹至{current_price:.2f}元\n"
                report += "   - 这是在测试原区间下沿的压力\n"
                report += "   - 可能是'死猫跳'或新的震荡区开始\n\n"

                report += "3. **三种可能情况**\n\n"

                report += "   情况A - 下跌趋势的中继反弹：\n"
                report += "   • 特征：在25-26元遇阻，后续继续下跌\n"
                report += "   • 概率：需观察成交量（放量滞涨是警告信号）\n"
                report += f"   • 确认：价格跌破22.26元，继续下跌\n\n"

                report += "   情况B - 新的吸筹结构形成：\n"
                report += "   • 特征：在22.26-25.11元形成新的区间\n"
                report += "   • 需要：多次测试22.26元不破，形成明确支撑\n"
                report += "   • 确认：新的区间结构完整，且放量突破上沿\n\n"

                report += "   情况C - Spring陷阱：\n"
                report += "   • 特征：4月22日跌破，在22.26元快速反弹\n"
                report += "   • ⚠️ 但Spring必须有完整吸筹前置结构\n"
                report += "   • 当前缺少Phase A（SC/AR/ST）\n"
                report += "   • 结论：这不是Spring，只是破位后的反弹\n\n"

                report += "4. **策略建议**：\n"
                report += "   ❌ 当前{current_price:.2f}元不是入场点（区间中部，风险收益比差）\n"
                report += "   ✅ 严格观望，等待市场给出明确信号\n"
                report += "   ✅ 若情况A（下跌中继）：等待跌破22.26元后的新底部\n"
                report += "   ✅ 若情况B（新结构）：等待新区间完整后再入场\n\n"

                report += "5. **威科夫理论核心原则**\n\n"
                report += "   区间边界的神圣性：\n"
                report += "   • 一旦区间边界被放量跌破 → 原区间结构失效\n"
                report += "   • 不能再称为'再吸筹区间' → 需要重新定义阶段\n"
                report += "   • 不能简单地下移区间下沿 → 需要观察新结构形成\n\n"

            else:
                # 价格仍在区间下方，未反弹回区间内
                if breakout_analysis:
                    quality = breakout_analysis.get('quality', 'unknown')
                    quality_score = breakout_analysis.get('quality_score', 0)
                    #  修复：quality_score可能是int或dict
                    if isinstance(quality_score, dict):
                        score_val = quality_score.get('score', 0)
                    else:
                        score_val = quality_score
                    report += f"突破质量：{quality.upper()}（{score_val}/100）\n\n"

                report += "向下突破确认原区间逻辑或进入下跌趋势：\n\n"
                report += "1. **当前状态：确认派发或进入Markdown**\n"
                report += "   - 向下突破否决了'吸筹'假设\n"
                report += "   - 市场可能进入下跌趋势\n\n"

                report += "2. **策略建议**：\n"
                report += "   ❌ 严禁做多\n"
                report += "   ✅ 等待底部信号（新的SC、PS等Phase A事件）\n"
                report += "   ✅ 关注是否有新的吸筹结构形成\n\n"

        else:
            report += "原交易区间已被突破，方向不明确\n\n"
            report += "建议等待更多确认信号\n\n"

        return report

    def _build_breakout_quality_section(
        self,
        breakout_analysis: dict,
        trading_range: dict
    ) -> str:
        """
        构建突破质量分析区块
        """
        report = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        report += "【📊 突破质量分析】\n\n"

        direction = breakout_analysis.get('direction', 'unknown')
        quality = breakout_analysis.get('quality', 'unknown')
        quality_score = breakout_analysis.get('quality_score', 0)

        if direction == 'up':
            is_upthrust = breakout_analysis.get('is_upthrust', False)
            report += f"突破方向: 向上突破\n"
            #  修复：quality_score可能是int或dict
            if isinstance(quality_score, dict):
                score_val = quality_score.get('score', 0)
            else:
                score_val = quality_score
            report += f"突破质量: {quality.upper()}（评分：{score_val}/100）\n\n"

            # 成交量分析
            vol_analysis = breakout_analysis.get('volume_analysis', {})
            if vol_analysis:
                report += f"📈 成交量特征：{vol_analysis.get('strength', 'unknown').upper()}\n"
                report += f"   突破量比：{vol_analysis.get('volume_ratio', 0):.1f}x\n"
                report += f"   信号解读：{vol_analysis.get('signal', 'neutral').upper()}\n\n"

            # 回测分析
            pullback = breakout_analysis.get('pullback_analysis', {})
            if pullback.get('has_pullback'):
                report += f"🔄 回测行为：{pullback.get('interpretation', 'unknown')}\n"
                report += f"   回测价格：{pullback.get('pullback_price', 0):.2f}元\n"
                report += f"   健康度：{'✓ 健康（缩量）' if pullback.get('is_healthy') else '⚠️ 警惕（放量）'}\n\n"
            else:
                report += f"🔄 回测行为：无回测（强势特征）\n\n"

            # 判断结论
            if is_upthrust:
                report += "⚠️ 突破性质：疑似Upthrust（冲高诱多）\n"
                report += "   特征：缩量突破 + 快速回落\n"
                report += "   风险：可能重新测试原区间\n\n"
            else:
                report += f"✓ 突破性质：真实突破（{quality}）\n"
                report += "   威科夫判断：需求主导，趋势延续概率高\n\n"

        elif direction == 'down':
            report += f"突破方向: 向下突破\n"
            #  修复：quality_score可能是int或dict
            if isinstance(quality_score, dict):
                score_val = quality_score.get('score', 0)
            else:
                score_val = quality_score
            report += f"突破质量: {quality.upper()}（评分：{score_val}/100）\n\n"

            vol_analysis = breakout_analysis.get('volume_analysis', {})
            if vol_analysis:
                report += f"📉 成交量特征：{vol_analysis.get('strength', 'unknown').upper()}\n"
                report += f"   突破量比：{vol_analysis.get('volume_ratio', 0):.1f}x\n\n"

        return report

    def _build_cause_effect(self, cause_effect, trading_range, sos_sow_analysis=None) -> str:
        """
        构建因果测算部分 (待激活模式与核心防守轴聚焦)
        """
        if not cause_effect or 'targets' not in cause_effect:
            return ''

        if cause_effect.get('method') == 'invalidated_tr':
            tr_low = cause_effect.get('tr_low', trading_range.get('low', 0.0))
            tr_high = cause_effect.get('tr_high', trading_range.get('high', 0.0))
            current_price = cause_effect.get('current_price', self.data['Close'].iloc[-1])
            return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【🎯 点数图 (P&F) 因果测算目标推演 - 暂停测算】

🚨 **原交易区间参考性已下降（已失效）**

当前盘面特征：支撑位 {tr_low:.2f} 元曾被跌破，但当前价格已强劲收回至 {current_price:.2f} 元（大幅站回区间下沿上方）。
这表明市场在原交易区间下方找到了新的强力需求，主力资金正在试图重建结构（可能正在形成新的 TR）。

根据威科夫原则，原交易区间 ({tr_low:.2f} - {tr_high:.2f}元) 边界参考点的有效性已经大幅下降。在没有新的有效交易区间（TR）以及完整的积累/派发结构重新形成前，基于旧失效区间进行任何点数图目标测算均是不科学的，因此**系统已自适应暂停目标测算，等待新的有效 TR 形成**。

✅ **后续观察指南**：
1. 密切观察近期收盘价是否在新的波动范围内收敛，确认新 TR 的上限与下限边界。
2. 严密追踪主力资金的建筹五要件（SC+AR+ST+Spring+SOS）在新结构中的表现，等待新的确认信号。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        tr_high, tr_low = trading_range.get('high', 0), trading_range.get('low', 0)
        current_price = self.data['Close'].iloc[-1]
        cause_bars = cause_effect.get('cause_bars', 0)
        breakout_dir = cause_effect.get('breakout_direction', 'up')

        # 破位寻底模式判定：现价低于下沿且超过箱体幅度的10%或绝对跌幅超3%
        is_breakdown = False
        if tr_low > 0:
            tr_height = tr_high - tr_low
            if current_price < tr_low - 0.1 * tr_height or current_price < tr_low * 0.97:
                is_breakdown = True

        # 针对单边向下破位寻底模式专项处理
        if is_breakdown:
            min_52w = self.data['Low'].tail(250).min() if len(self.data) >= 50 else current_price * 0.88
            report = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            report += "【🎯 机构级点数图 (P&F) 宏观视野与复合操作手行为深度剖析】\n\n"
            report += f"【大局观结构重构】 针对前期盘整 ({tr_low:.2f}-{tr_high:.2f}元) 下破后的特征，威科夫机构视角不再将其粗略定性为“瀑布式崩塌”，而是精准定性为**【大级别派发后的弱趋势衰退带 (Markdown 衰退尾段 → 波动率压缩 → 空头效率下降 → 长期再平衡前夜)】**。特别提示：“前夜”绝不等于“已经见底”。\n\n"
            report += f"【大尺度观察区界定】 威科夫理论明确反对“整数关口锚定或市场共识支撑必到论”。远端情绪冰点带 ({min_52w:.2f}元附近) 仅为大资金真实成本与长期需求的【潜在大需求观察区】，绝非机械的必达到位目标。大资金 (Composite Man) 经常拒绝给予大众预期的恐慌极点，而是采取横盘耗时或快速洗盘来重构筹码。\n\n"
            report += "根据威科夫因果法则，大尺度筹码推演呈现如下分层架构：\n\n"
            report += "• **已激活目标**: 无 (前期中继箱体已破位失效，当前无有效多头起动 TR 结构)。\n"
            report += f"• **待重构下行边界**: 市场已进入长期耗时磨底阶段。大底从来不是纯粹的价格事件，而是伴随数月至一两年的极度冷清与无人问津的“时间事件”。\n"
            report += f"• **多头极限中轴**: 需带量强力越过中轴阻力 ({tr_high:.2f}元)，当前多头胜率极低，仅作长远期多空生命线基准。\n\n"
            report += "【📊 波动率塌缩与需求控制权双向深度剖析 (Demand vs Supply)】\n"
            report += "1. **供给端特征 (Effort vs Result 衰竭)**：当前盘面呈现明显的波动率塌缩与向下推动效率衰弱 (大阴线减少、量比渐小)。反映出当前卖压虽占优，但机构做空效能正呈递减规律，此乃供给衰竭的前置表征。\n"
            report += "2. **需求端特征 (需求缺位与弱平衡陷阱)**：威科夫机构级核心公式为 `Supply exhausted + Demand takes control = 真实右侧`。当前盘面仅有供给衰减，但尚未观察到任何主动性需求扩散、连续性跟随买盘以及带量越过阻力的 SOS 级别动作。必须警惕标的步入“低波动时间消耗型横盘陷阱”。\n\n"
            report += "【⚠️ 机构操盘心理学与分级实战策略】\n"
            report += "1. **防范分析师一致预期底部**：大资金极其厌恶共识支撑位。未来极可能通过“不破底直接收敛成底”或“极速砸穿后强势拉回 (Spring + Reclaim)”来完成终极震仓。\n"
            report += "2. **牢记威科夫核心戒律**：`Never buy because price is low. Buy because supply is exhausted.` (永远不因价格低而抄底，只因供给耗尽而介入)。\n"
            report += "3. **分级交易指南**：\n"
            report += "   • **短线资金**：严禁幻想价值投资闭眼长拿。当前标的属性为大震荡衰退资产，仅适用区间网格与高抛低吸波段。\n"
            report += "   • **中线资金**：密切跟踪波动压缩与利空钝化，捕捉 Composite Operator 重新吸筹的痕迹。\n"
            report += "   • **长线右侧标准**：在未见 **SC (情绪冰点) + AR (强力反弹) + ST (缩量回踩) + Spring (洗盘) + SOS (放量带量重夺关键位)** 五大建构要件齐备前，**所有反弹一律绝对优先按 LPSY 或技术性反抽处理**！\n"
            return report

        if trading_range.get('is_broken'):
            direction = trading_range.get('breakout_direction', 'unknown')
            return f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【因果测算 - 待重新锚定】\n原区间: {tr_low:.2f} - {tr_high:.2f}（已被{direction}突破至{current_price:.2f}）\n状态: 原TR已失效，旧因果目标不再适用\n"

        targets = cause_effect.get('targets', {})
        t1_raw = targets.get('target_1', 0)
        t2_raw = targets.get('target_2', 0)

        # 动态推导多头与空头理论目标（基于因果法则：列数 * 步长 * 3翻转）
        box_size = current_price * 0.015
        total_move = cause_bars * box_size if cause_bars > 0 else current_price * 0.25

        if breakout_dir == 'up' and t1_raw > current_price:
            t1_up, t2_up = t1_raw, t2_raw
        else:
            t1_up = (tr_high if tr_high > 0 else current_price) + total_move * 0.6
            t2_up = (tr_high if tr_high > 0 else current_price) + total_move

        if breakout_dir == 'down' and 0 < t1_raw < current_price:
            t1_down, t2_down = t1_raw, t2_raw
        else:
            t1_down = (tr_low if tr_low > total_move * 0.6 else current_price) - total_move * 0.6
            t2_down = (tr_low if tr_low > total_move else current_price) - total_move
            if t1_down <= 0:
                t1_down = current_price * 0.8
            if t2_down <= 0:
                t2_down = current_price * 0.7

        report = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        report += "【🎯 点数图 (P&F) 因果测算目标推演】\n\n"
        report += f"长期箱体盘整带共计积累了 {cause_bars} 列的水平因果筹码。在绝对中轴 {tr_high:.2f} 元分出多空胜负前，所有测算目标均处于【待激活（Pending）】状态：\n\n"

        trigger_up = (tr_high if tr_high > 0 else current_price) * 1.025

        report += "### 🚀 向上突破情景（多头终极目标）\n\n"
        report += f"基于 {cause_bars} 列因果筹码扩展，若**带量站稳 {tr_high:.2f} 元颈线上方**：\n\n"
        report += "| 目标位 | 价格 | 涨幅 | 激活与达成条件 |\n"
        report += "|--------|------|------|----------------|\n"
        report += f"| **T1 (首要目标)** | {t1_up:.2f} | {(t1_up/current_price - 1)*100:+.1f}% | 放量越过 {trigger_up:.2f} 元并出现 LPS 缩量回踩 |\n"
        report += f"| **T2 (终极目标)** | {t2_up:.2f} | {(t2_up/current_price - 1)*100:+.1f}% | T1 达成后展开大周期主升浪 |\n"

        report += f"\n### ⚠️ 向下防守极限情景（仅供极端防守参考）\n\n"
        report += f"• **极限防守位**: {t1_down:.2f} 元 ({(t1_down/current_price - 1)*100:+.1f}%)\n"
        report += f"• **激活门槛**: 需放量跌破绝对下沿 {tr_low:.2f} 元且连续 3 周无法收复。在未跌破 {tr_high:.2f} 元前，发生概率极低。\n"
        report += f"• **操作防守轴**: 重点聚焦于 **{tr_high:.2f} 元**。若价格突破后再度放量跌回其下方，确认为 Upthrust 诱多陷阱，需无条件执行离场纪律。\n"

        if sos_sow_analysis and sos_sow_analysis.get('has_conflict'):
            interpretation = sos_sow_analysis.get('interpretation')
            if interpretation in ['trap_bearish', 'suspected_trap']:
                conf = sos_sow_analysis.get('confidence', 0) * 100
                report += f"\n⚠️ **SOS-SOW分析警示：盘面近期存在疑似诱多迹象（{conf:.0f}%置信度）**，请高度提防假突破。\n"
            elif interpretation in ['shakeout_bullish', 'suspected_shakeout']:
                conf = sos_sow_analysis.get('confidence', 0) * 100
                report += f"\n✅ **SOS-SOW分析提示：缩量回落属于健康震仓洗盘（{conf:.0f}%置信度）**，支持多头爆发。\n"
        report += "\n"
        return report

    def _check_post_breakout_state(self, trading_range, joc, current_price) -> str:
        if not self._get(trading_range, 'is_broken'): return ''
        direction = self._get(trading_range, 'breakout_direction', 'unknown')
        tr_high = self._num(self._get(trading_range, 'high', 0))
        tr_low = self._num(self._get(trading_range, 'low', 0))
        if direction == 'up':
            if self._get(joc, 'test_detected'): return f"【突破后状态 - 回测确认】\n   价格已突破TR上沿{tr_high:.2f}至{current_price:.2f}，且回测已确认。\n"
            return f"【突破后状态 - JOC推进中】\n   价格已突破TR上沿{tr_high:.2f}至{current_price:.2f}，JOC已触发。\n"
        return f"【突破后状态 - 向下突破】\n   价格已跌破TR下沿{tr_low:.2f}至{current_price:.2f}。\n"

    def _build_falsification(self, phase_str, trading_range) -> str:
        tr_high, tr_low = trading_range.get('high', 0), trading_range.get('low', 0)
        current_price = self.data['Close'].iloc[-1]

        report = f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【逻辑证伪点】\n💡 顶级交易计划不仅告诉你什么情况下你对了，更明确告诉你什么情况下你判断错了。\n"

        #  新增：如果已突破，显示更相关的支撑位（基于威科夫理论）
        if trading_range.get('is_broken'):
            breakout_level = tr_high if trading_range.get('breakout_direction') == 'up' else tr_low
            retest_zone = self._calculate_healthy_retest_zone(current_price, breakout_level, 0)

            if trading_range.get('breakout_direction') == 'up':
                wyckoff_logic = retest_zone.get('explanation', '')
                report += "[!] 关键观察点位（威科夫Test of JOC）:\n"
                report += f"   • 主回测目标: {breakout_level:.2f}元（原TR上沿）\n"
                if retest_zone:
                    report += f"   • 回测区间: {retest_zone.get('target_range', f'{breakout_level * 0.95:.2f} - {breakout_level * 1.05:.2f}')}元\n"
                    report += f"   • 突破失效位: {retest_zone['breakdown_level']:.2f}元（跌破则趋势破坏）\n"
                report += f"\n   💡 威科夫逻辑: {wyckoff_logic}\n"
                report += f"   • 原TR下沿（远端支撑）: {tr_low:.2f}元\n"
            else:
                report += f"[!] 关键观察点位:\n   • 突破位: {breakout_level:.2f}元\n   • 原TR上沿: {tr_high:.2f}元\n"
        else:
            #  修复格式化bug：使用f-string正确格式化
            report += f"[!] 观察要点:\n   • 关键阻力位: {tr_high:.2f}元\n   • 关键支撑位: {tr_low:.2f}元\n"

        #  新增：BC警示下的特殊止损纪律
        try:
            # 从主链 phase_result 读取 climax（避免二次 collect_all_events）
            bc_detected = False
            bc_type = None

            phase_result = getattr(self, '_phase_result', None)
            if phase_result:
                try:
                    from ....signal_extractor import get_events_from_phase
                    events = get_events_from_phase(phase_result)
                    climax = self._get(events, 'climax') if events else None
                    if climax:
                        bc_detected = self._detected(climax)
                        bc_type = self._get(climax, 'type')
                except Exception as e:
                    logger.debug(f"Failed to get climax from phase_result: {e}")

            # 方法2：检查阶段字符串（备用）
            if not bc_detected:
                has_bc_keywords = any(keyword in phase_str for keyword in [
                    'Buying Climax', '买入高潮', 'BC Warning', 'BC警示',
                    '潜在派发初期', '派发初期'
                ])
                if has_bc_keywords:
                    bc_detected = True
                    bc_type = 'buying_climax'

            # 如果检测到Buying Climax
            if bc_detected and bc_type == 'buying_climax':
                report += f"\n\n【⚠️ 买入高潮（BC）警示】\n\n"
                report += "威科夫铁律：派发/BC阶段的止损纪律\n\n"
                report += "若止损触发（跌破上述关键位）：\n"
                report += "  ✅ **必须无条件离场**\n"
                report += "  ❌ **不可补仓摊平**\n"
                report += "  ❌ **不可等待反弹**\n\n"
                report += "原因：\n"
                report += "  • BC后止损触发 = 确认派发结构成立\n"
                report += "  • 派发期抄底 = 接飞刀\n"
                report += "  • 威科夫原则：永不对抗趋势，尤其在派发期\n\n"
                logger.info(f"BC warning added: type={bc_type}")
        except Exception as e:
            logger.debug(f"Failed to add BC warning: {e}")

        return report

    def _build_arbitration_section(self, arbitration_result: dict) -> str:
        """
        构建事件仲裁结果区块

        当检测到冲突信号（如Spring vs LPSY）时，显示仲裁结果和理由
        """
        if not arbitration_result:
            return ""

        # 处理Pydantic模型和dict两种格式
        if hasattr(arbitration_result, 'has_conflict'):
            has_conflict = arbitration_result.has_conflict
            conflicting_signals = arbitration_result.conflicting_signals
            dominant_signal = arbitration_result.dominant_signal
            rejected_signals = arbitration_result.rejected_signals
            reason = arbitration_result.arbitration_reason
            suggested_phase = arbitration_result.suggested_phase
            phase_adjustment = arbitration_result.phase_adjustment
            confidence_adj = arbitration_result.confidence_adjustment
        else:
            has_conflict = arbitration_result.get('has_conflict', False)
            conflicting_signals = arbitration_result.get('conflicting_signals', [])
            dominant_signal = arbitration_result.get('dominant_signal')
            rejected_signals = arbitration_result.get('rejected_signals', [])
            reason = arbitration_result.get('arbitration_reason', '')
            suggested_phase = arbitration_result.get('suggested_phase')
            phase_adjustment = arbitration_result.get('phase_adjustment')
            confidence_adj = arbitration_result.get('confidence_adjustment', 1.0)

        if not has_conflict:
            return ""

        report = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        report += "【⚠️ 事件仲裁结果】\n\n"

        # 显示冲突信号
        if conflicting_signals:
            conflicting_names = []
            for sig in conflicting_signals:
                if hasattr(sig, 'signal_type'):
                    name = sig.signal_type
                    date_str = sig.date.strftime('%Y-%m-%d') if hasattr(sig.date, 'strftime') else str(sig.date)
                    conflicting_names.append(f"{name} ({date_str})")
                elif isinstance(sig, dict):
                    name = sig.get('signal_type', 'Unknown')
                    date_str = sig.get('date')
                    conflicting_names.append(f"{name} ({date_str})")

            report += f"📊 检测到的冲突信号:\n"
            for name in conflicting_names:
                report += f"   • {name}\n"
            report += "\n"

        # 显示主导信号
        if dominant_signal:
            if hasattr(dominant_signal, 'signal_type'):
                sig_type = dominant_signal.signal_type
                sig_date = dominant_signal.date.strftime('%Y-%m-%d') if hasattr(dominant_signal.date, 'strftime') else str(dominant_signal.date)
                sig_conf = dominant_signal.confidence
            else:
                sig_type = dominant_signal.get('signal_type', 'Unknown')
                sig_date = dominant_signal.get('date')
                sig_conf = dominant_signal.get('confidence', 0)

            report += f"✅ 主导信号: {sig_type}\n"
            report += f"   日期: {sig_date}\n"
            report += f"   置信度: {sig_conf:.2f}\n\n"

        # 显示被拒绝的信号
        if rejected_signals:
            rejected_names = []
            for sig in rejected_signals:
                if hasattr(sig, 'signal_type'):
                    rejected_names.append(sig.signal_type)
                elif isinstance(sig, dict):
                    rejected_names.append(sig.get('signal_type', 'Unknown'))

            report += f"❌ 被拒绝的信号: {', '.join(rejected_names)}\n\n"

        # 显示仲裁理由
        report += f"📝 仲裁理由:\n   {reason}\n\n"

        # 显示阶段调整
        if suggested_phase:
            report += f"🎯 建议阶段: {suggested_phase}\n"
            if phase_adjustment:
                report += f"   {phase_adjustment}\n"
            report += "\n"

        # 显示置信度调整
        if confidence_adj < 1.0:
            report += f"⚠️ 置信度调整: ×{confidence_adj:.2f}（由于信号冲突）\n\n"

        return report

    def _build_market_context_section(self, market_env: dict) -> str:
        """构建市场环境背景区块 (v2.6.0 P0)"""
        if not market_env:
            return ""
        
        env_label = market_env.get('environment', 'Unknown')
        desc = market_env.get('description', '未知环境')
        index_symbol = market_env.get('index_symbol', '')
        
        # 获取量能信息
        evr_info = market_env.get('volume_energy', {})
        breadth_info = market_env.get('breadth', {})
        pf_targets = market_env.get('pf_targets', {})
        warning = market_env.get('warning')
        vol_ratio = evr_info.get('vol_ratio', 1.0)
        
        report = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        report += "【🌍 市场环境背景】\n"
        report += f"基准指数: {index_symbol}\n"
        report += f"当前状态: **{env_label}**\n"
        report += f"环境描述: {desc}\n"
        
        if evr_info:
            report += f"量能状态: {evr_info.get('interpretation', 'NORMAL')} (波段量比: {vol_ratio:.2f}x)\n"

        if breadth_info and breadth_info.get('status') != 'SKIPPED':
            adr = breadth_info.get('adr', 1.0)
            adv = breadth_info.get('advance_count', 0)
            dec = breadth_info.get('decline_count', 0)
            ratio = breadth_info.get('advance_ratio_pct', 0)
            report += f"市场广度: ADR {adr:.2f} (上涨 {adv} | 下跌 {dec} | 占比 {ratio}%)\n"

        if pf_targets and pf_targets.get('targets'):
            targets = pf_targets['targets']
            direction = "🚀 上涨目标" if pf_targets.get('breakout_direction') == 'up' else "📉 下跌目标"
            t1 = targets.get('target_1', 0)
            t2 = targets.get('target_2', 0)
            report += f"指数因果预测: {direction} T1: {t1:.0f} | T2: {t2:.0f}\n"
            
        if warning:
            report += f"\n⚠️ **大盘风险提示**: {warning}\n"
            
        report += "\n💡 威科夫提醒：优秀的交易者永远在大盘'顺风'时积极操作，在'逆风'时收紧仓位。\n"
        return report

    def _get_tr_value(self, trading_range, key: str, default=0):
        """
        安全地从trading_range获取值（兼容dict和Pydantic模型）

        Args:
            trading_range: 交易区间（dict或Pydantic模型）
            key: 键名
            default: 默认值

        Returns:
            对应的值
        """
        if isinstance(trading_range, dict):
            return trading_range.get(key, default)
        elif hasattr(trading_range, key):
            val = getattr(trading_range, key)
            return val if val is not None else default
        else:
            return default

    def _calculate_healthy_retest_zone(
        self,
        current_price: float,
        breakout_level: float,
        recent_lps: float = 0
    ) -> Dict[str, Any]:
        """
        计算健康的回测区域（基于威科夫Test of JOC理论）

        威科夫理论：JOC突破后，价格应该回测原突破位（TR上沿），
        因为那里是最强的阻力位，突破后转为支撑。

        Args:
            current_price: 当前价格
            breakout_level: 突破位（原TR上沿）
            recent_lps: 最近的LPS价格

        Returns:
            健康回测区间字典
        """
        #  修复：基于威科夫理论的Test of JOC回测目标
        # 主目标：原TR上沿（突破位）
        # 威科夫逻辑：原最强阻力转为支撑，价格应回测验证
        primary_target_high = breakout_level * 1.05  # 突破位上方5%
        primary_target_low = breakout_level * 0.95    # 突破位下方5%

        # 检查当前价格距离突破位的距离
        distance_pct = (current_price / breakout_level - 1) * 100

        # 如果当前价远高于突破位（>15%），可能需要考虑次级支撑
        if distance_pct > 15:
            # 寻找中间支撑位
            # 1. 如果有LPS，优先使用LPS
            if recent_lps and recent_lps > breakout_level:
                # LPS在突破位之上，可能是更近的支撑
                secondary_support = recent_lps
            else:
                # 使用斐波那契回调位计算次级支撑
                # 38.2%回调位通常是强支撑
                rally_range = current_price - breakout_level
                secondary_support = current_price - (rally_range * 0.382)

            # 回测区间 = [突破位, 次级支撑] 的交集
            healthy_retest_high = max(primary_target_high, secondary_support * 1.02)
            healthy_retest_low = primary_target_low

            return {
                'primary_target': breakout_level,
                'target_range': f"{primary_target_low:.2f} - {primary_target_high:.2f}",
                'healthy_high': healthy_retest_high,
                'healthy_low': healthy_retest_low,
                'is_deep_pullback_warning': False,
                'breakdown_level': breakout_level * 0.95,
                'logic': 'Wyckoff Test of JOC + Fibonacci secondary support',
                'explanation': f'主回测目标：原突破位{breakout_level:.2f}元（威科夫理论），次级支撑：{secondary_support:.2f}元'
            }

        # 正常情况：回测目标就是突破位附近
        return {
            'primary_target': breakout_level,
            'target_range': f"{primary_target_low:.2f} - {primary_target_high:.2f}",
            'healthy_high': primary_target_high,
            'healthy_low': primary_target_low,
            'is_deep_pullback_warning': False,
            'breakdown_level': breakout_level * 0.95,
            'logic': 'Wyckoff Test of JOC',
            'explanation': f'经典Test of JOC：回测原突破位{breakout_level:.2f}元（最强阻力转为支撑）'
        }

    def _build_wie3_mvp_section(self, market_state) -> str:
        """
        构建 WIE 3.0 机构级贝叶斯微观结构状态区块
        """
        if market_state is None:
            return ""
            
        from src.wyckoff.core.market_state import RegimeState

        report = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【WIE 3.0 机构级贝叶斯状态估计器】
   威科夫自适应行为动力学操作系统 v3.0 - 贝叶斯后验推演

"""

        # 基础状态信息
        report += f"📊 最高概率状态标签: {market_state.regime}\n"
        report += f"   当前价格: {market_state.close:.2f}\n"
        report += f"   系统信息熵: {market_state.state_entropy:.4f}"

        if market_state.is_confidence_degraded:
            report += " ⚠️ (高熵模糊带 - 状态混沌，建议降权观望)"
        else:
            report += " ✓ (信息熵稳定 - 状态收敛)"

        report += "\n\n"
        
        # 概率分布展示
        if market_state.state_probs:
            report += "📈 贝叶斯后验状态分布 (State Probability Distribution):\n"
            sorted_probs = sorted(market_state.state_probs.items(), key=lambda x: x[1], reverse=True)
            for state, prob in sorted_probs:
                if prob > 0.01:
                    bar_length = int(prob * 40)
                    bar = "█" * bar_length
                    report += f"   {state.split('(')[0].strip():40s} [{bar}] {prob*100:.1f}%\n"
            report += "\n"
            
        # 转移路径预测
        if hasattr(market_state, 'transition_paths') and market_state.transition_paths:
            report += "🛣️ HMM 转移路径演化预测 (Next-Step Path Dependency):\n"
            sorted_paths = sorted(market_state.transition_paths.items(), key=lambda x: x[1], reverse=True)
            path_count = 0
            for state, prob in sorted_paths:
                if prob > 0.05 and path_count < 3: # 仅展示最高概率的Top 3路径
                    report += f"   👉 预计转向 -> {state.split('(')[0].strip()}: {prob*100:.1f}%\n"
                    path_count += 1
            report += "\n"

        # 核心微观指标
        report += "🔬 核心微观指标:\n"
        report += f"   APS (吸收分): {market_state.aps:.2f}"
        if market_state.aps > 15:
            report += " ✅ (强劲吸收)"
        elif market_state.aps > 8:
            report += " (中等吸收)"
        else:
            report += " (吸收不足)"
        report += "\n"

        report += f"   CDS (换手记忆): {market_state.cds} 天"
        if market_state.cds > 20:
            report += " ✅ (充分换手)"
        elif market_state.cds > 10:
            report += " (中度换手)"
        else:
            report += " (换手不足)"
        report += "\n"

        report += f"   LCS (死票甄别): {market_state.lcs:.2f}"
        if market_state.lcs < 3:
            report += " ⚠️ (可能为死票)"
        else:
            report += " ✓ (活跃度正常)"
        report += "\n"

        report += f"   VPOC (筹码峰): {market_state.vpoc_price:.2f}"
        current_price = market_state.close
        if current_price > market_state.vpoc_price:
            report += f" ✅ (价格企稳于筹码峰之上 {((current_price / market_state.vpoc_price - 1) * 100):.1f}%)"
        else:
            report += f" (价格在筹码峰之下 {((1 - current_price / market_state.vpoc_price) * 100):.1f}%)"
        report += "\n"

        report += f"   推动效率: {market_state.expansion_eff:.2f}"
        if market_state.expansion_eff > 2.0:
            report += " ✅ (供给真空突破)"
        elif market_state.expansion_eff > 1.0:
            report += " (效率正常)"
        else:
            report += " ⚠️ (推动乏力)"
        report += "\n"

        report += f"   CLV (吃单效率): {market_state.clv:.2f}"
        if market_state.clv > 0.5:
            report += " ✅ (机构强势吸单)"
        elif market_state.clv < -0.5:
            report += " ⚠️ (机构派发砸盘)"
        else:
            report += " (中性)"
        report += "\n\n"

        # 相对强度分析
        report += "🔄 相对强度分析:\n"
        report += f"   流动性留存率: {market_state.liquidity_retention:.2f}x"
        if market_state.liquidity_retention > 1.2:
            report += " ✅ (资金相对大盘净流入)\n"
        elif market_state.liquidity_retention < 0.8:
            report += " ⚠️ (资金相对大盘净流出)\n"
        else:
            report += " (与大盘同步)\n"

        report += f"   暗藏强势: {'✅ 是 - 大盘跌个股抗跌' if market_state.hidden_strength else '❌ 否'}\n"
        report += f"   暗藏弱势: {'⚠️ 是 - 大盘涨个股滞涨' if market_state.hidden_weakness else '❌ 否'}\n\n"

        # 事件标志
        if market_state.event_flags:
            report += "🚩 事件标志:\n"
            for flag in market_state.event_flags:
                if 'SPRING' in flag:
                    report += f"   🎯 {flag} - 瞬态震仓破底翻,起跳前兆!\n"
                elif 'HIDDEN STRENGTH' in flag:
                    report += f"   💪 {flag} - 机构锁仓拒绝下跌\n"
                elif 'HIDDEN WEAKNESS' in flag:
                    report += f"   ⚠️ {flag} - 机构暗中撤退\n"
                else:
                    report += f"   📌 {flag}\n"
            report += "\n"

        # 风险敞口调整 (取代判决式)
        report += "🛡️ 机构级风险加权敞口建议 (Risk-weighted Exposure):\n"
        s0_prob = market_state.state_probs.get(RegimeState.S0_PANIC_LIQUIDATION.value, 0)
        s1_prob = market_state.state_probs.get(RegimeState.S1_ABSORPTION.value, 0)
        s5_prob = market_state.state_probs.get(RegimeState.S5_DISTRIBUTION.value, 0)
        s3_s4_prob = market_state.state_probs.get(RegimeState.S3_DEMAND_EMERGENCE.value, 0) + market_state.state_probs.get(RegimeState.S4_MARKUP.value, 0)
        
        if s0_prob > 0.4:
            report += "   ⚠️ 【高频下行/信息发散带】当前盘面呈现高下行动能与高不确定性。威科夫理论中此为机会生成的前置区（潜在SC），但吸收概率目前仍偏低。\n"
            report += "   策略建议：绝不进行左侧摸底，**建议将风险敞口严格压缩至 0%-10%**，密切等待 S1(吸收) 概率显著上升。\n"
        elif s5_prob > 0.4:
            report += "   🎣 【高位派发危险带】微观结构显示机构资金正在系统性流出，筹码松动明显。\n"
            report += "   策略建议：保护利润为第一要务，**建议将多头风险敞口迅速降至 0%-10%**，严防断头铡刀。\n"
        elif s1_prob > 0.35:
            report += "   🧽 【吸收沉淀带】微观结构显示筹码正在被密集承接，系统进入耗时磨底阶段。\n"
            report += "   策略建议：底座初步构筑中，可进行防御性试探，**建议配置风险敞口 10%-30%**，耐心等待 VPOC 突破。\n"
        elif s3_s4_prob > 0.35:
            report += "   🚀 【需求接管/主升带】多头动力学特征极其显著，带量穿越核心阻力位。\n"
            report += "   策略建议：右侧确认，趋势已成。**建议提升风险敞口至 60%-100%**，顺势持仓。\n"
        else:
            report += "   ⏳ 【中性震荡带】多空动力学进入均势，未见明显单边结构。\n"
            report += "   策略建议：维持网格或波段策略，**建议风险敞口控制在 30%-50%**。\n"

        report += "\n" + "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" + "\n\n"

        return report
