import logging
from typing import Dict, Any
from .base_builder import BaseSectionBuilder

logger = logging.getLogger(__name__)

class ConclusionSection(BaseSectionBuilder):
    """构建报告结论、因果测算、冲突警告及证伪区块"""
    def build(self, phase_result: dict, trading_range: dict, cause_effect: dict, conflict: dict,
              quality_data: dict, joc: dict, spring: dict, sos: dict, lps: dict, fti: dict,
              upthrust: dict, sow: dict, lpsy: dict, mtf: dict, boring_res: dict,
              dead_corner: dict, market_env: str, arbitration_result: dict = None,
              breakout_analysis: dict = None) -> str:

        phase_str = phase_result.get('phase', 'Unknown')
        phase_conf = phase_result.get('confidence', 0.0)
        current_price = self.data['Close'].iloc[-1]

        report = ""

        # 🔧 新增：计算健康回测区间（用于后续推荐）
        retest_zone = None
        if trading_range and trading_range.get('is_broken'):
            breakout_level = self._get_tr_value(trading_range, 'high', current_price * 0.9)
            # 🔧 修复：LPS返回结构中price字段在latest里
            lps_price = 0
            if lps:
                latest = lps.get('latest', {}) if isinstance(lps, dict) else lps
                lps_price = latest.get('price', 0) if isinstance(latest, dict) else 0
            retest_zone = self._calculate_healthy_retest_zone(current_price, breakout_level, lps_price)

        # === 事件仲裁结果 ===
        if arbitration_result:
            report += self._build_arbitration_section(arbitration_result)

        # 🔧 新增：TR突破后的重新评估
        if trading_range and trading_range.get('is_broken'):
            report += self._build_tr_breakdown_reassessment(trading_range, phase_result, breakout_analysis)

            # 🔧 新增：显示突破质量分析
            if breakout_analysis and breakout_analysis.get('is_breakout'):
                report += self._build_breakout_quality_section(breakout_analysis, trading_range)

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

        # 🔧 修复矛盾三：检查突破覆盖 - 向上突破应该否决派发判断
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

        # 🔧 基于高时间框架优先原则的仲裁逻辑
        is_weekly_bullish = conflict.get('weekly_trend') == 'bullish'
        # 安全地检查fti是否为模型对象或dict
        fti_detected = False
        if fti is not None:
            if hasattr(fti, 'detected'):
                fti_detected = fti.detected
            elif isinstance(fti, dict):
                fti_detected = fti.get('detected', False)
        is_daily_bearish = ('Distribution' in phase_str or 'Markdown' in phase_str or fti_detected) and not breakout_override

        if conflict.get('has_conflict') and is_weekly_bullish and is_daily_bearish:
            # 🔧 修复：严格派发逻辑 - 绝不在派发阶段建议做多
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
        # 🔧 新增：优先检查突破质量和JOC测试状态（连接突破质量与交易决策）
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
                if post_breakout: report += f"\n{post_breakout}"

        # 原有逻辑
        if conflict.get('has_conflict') and is_weekly_bullish and is_daily_bearish:
            # 🔧 修复：严格派发逻辑 - 绝不在派发阶段建议做多
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
            if post_breakout: report += f"\n{post_breakout}"
        else:
            # 详细结论逻辑
            is_distribution = 'Distribution' in phase_str or '派发' in phase_str
            if post_breakout: report += post_breakout

            if joc.get('detected') and joc.get('test_detected') and not is_distribution:
                joc_entry = joc.get('creek_level', current_price)
                target2 = cause_effect.get('targets', {}).get('target_2', current_price * 1.15)
                report += f"🚀 趋势跟踪买入（JOC 突破确认）:\n   参考入场区间: {joc_entry:.2f} ~ {joc_entry * 1.02:.2f}\n   止损: {joc_entry * 0.96:.2f} | 目标2: {target2:.2f}\n"
            elif lps.get('detected') and not is_distribution:
                # 🔧 修复：LPS返回结构中price字段在latest里，且需要检查signal_type
                latest = lps.get('latest', {}) if isinstance(lps, dict) else lps
                signal_type = latest.get('signal_type', 'unknown') if isinstance(latest, dict) else 'unknown'
                lp = latest.get('price', current_price) if isinstance(latest, dict) else current_price

                # 只有正式LPS（signal_type='lps'）才显示为"做多机会"
                if signal_type == 'lps':
                    report += f"[YES] 做多机会（LPS 最后支撑）:\n   入场价格: {lp:.2f} | 止损: {lp * 0.95:.2f}\n"
                elif signal_type == 'support_test':
                    report += f"[?] 观察支撑测试:\n   价格: {lp:.2f}（非正式LPS，需等待确认）\n"
                # 其他signal_type（pullback等）不显示在核心结论中
            elif fti.get('detected') and fti.get('test_detected'):
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
                # ✅ STRONG突破 + 已确认Test of JOC → 做多信号
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

                # 🔧 修复：计算策略B的合理止损位（基于次级支撑）
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
                # 🔔 正在接近回测区间
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

            # 🔧 新增：计算并显示健康回测区间
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

            # 🔧 新增：显示健康回测区间（基于威科夫理论）
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
            report += f"原交易区间（{tr_low:.2f}-{tr_high:.2f}）已向下突破至{current_price:.2f}元\n\n"

            if breakout_analysis:
                quality = breakout_analysis.get('quality', 'unknown')
                quality_score = breakout_analysis.get('quality_score', 0)
                # 🔧 修复：quality_score可能是int或dict
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
            # 🔧 修复：quality_score可能是int或dict
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
            # 🔧 修复：quality_score可能是int或dict
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
        current_price = self.data['Close'].iloc[-1]

        report = f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【逻辑证伪点】\n💡 顶级交易计划不仅告诉你什么情况下你对了，更明确告诉你什么情况下你判断错了。\n"

        # 🔧 新增：如果已突破，显示更相关的支撑位（基于威科夫理论）
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
            report += "[!] 观察要点:\n   • 关键阻力位: {tr_high:.2f}元\n   • 关键支撑位: {tr_low:.2f}元\n"

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
        # 🔧 修复：基于威科夫理论的Test of JOC回测目标
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
