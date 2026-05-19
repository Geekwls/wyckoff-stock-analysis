"""
SOS-SOW矛盾分析模块
解决威科夫分析中SOS（强势信号）与SOW（弱势信号）同时出现的倾向性判断
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)


class SOSSOWAnalyzer:
    """
    SOS-SOW矛盾分析器

    威科夫理论中，SOS后短期内出现SOW有两种解读：
    - 解读A：震仓洗盘（Shakeout）- 看涨
    - 解读B：诱多陷阱（False Breakout）- 看跌

    本模块基于量价关系给出倾向性判断
    """

    @staticmethod
    def analyze_sos_sow_conflict(
        sos: Dict[str, Any],
        sow: Dict[str, Any],
        current_price: float,
        trading_range: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        分析SOS与SOW的矛盾关系，给出倾向性判断

        Args:
            sos: SOS信号字典
            sow: SOW信号字典
            current_price: 当前价格
            trading_range: 交易区间信息

        Returns:
            分析结果字典，包含：
            - has_conflict: 是否存在矛盾
            - interpretation: 倾向性解读 ('shakeout_bullish' 或 'trap_bearish' 或 'no_conflict')
            - confidence: 置信度 (0-1)
            - reasons: 判断理由列表
            - confirmation_criteria: 确认条件
            - breakdown_level: 关键确认位
        """
        result = {
            'has_conflict': False,
            'interpretation': 'no_conflict',
            'confidence': 0.0,
            'reasons': [],
            'confirmation_criteria': [],
            'breakdown_level': None,
            'breakdown_source': None
        }

        # 检查SOS和SOW是否都存在
        if not sos.get('detected') or not sow.get('detected'):
            result['interpretation'] = 'no_conflict'
            result['reasons'].append('SOS或SOW信号缺失，无矛盾')
            return result

        # 获取SOS和SOW的日期
        sos_date_str = sos.get('date', '')
        sow_date_str = sow.get('date', '')

        if not sos_date_str or not sow_date_str:
            result['interpretation'] = 'no_conflict'
            result['reasons'].append('SOS或SOW日期缺失，无法分析')
            return result

        # 解析日期（使用统一工具类）
        from ..core.utils import TypeConverter
        sos_date = TypeConverter.parse_date_naive(sos_date_str)
        sow_date = TypeConverter.parse_date_naive(sow_date_str)
        if sos_date is None or sow_date is None:
            logger.warning(f"Failed to parse SOS/SOW dates: sos={sos_date_str}, sow={sow_date_str}")
            result['interpretation'] = 'no_conflict'
            result['reasons'].append('日期解析失败')
            return result

        # 计算SOS与SOW之间的天数
        days_diff = (sow_date - sos_date).days

        # 获取量比
        sos_vol_ratio = sos.get('volume_ratio', sos.get('vol_ratio', 1.0))
        sow_vol_ratio = sow.get('volume_ratio', sow.get('vol_ratio', 1.0))

        # 获取SOW的信号类型
        sow_signal_type = sow.get('signal_type', '')
        sow_price = sow.get('price', current_price)
        sos_price = sos.get('price', current_price)
        sow_low = sow.get('low', current_price)

        # 获取交易区间信息
        tr_high = trading_range.get('high', 0) if trading_range else 0
        tr_low = trading_range.get('low', 0) if trading_range else 0

        # 核心判断逻辑
        shakeout_score = 0  # 震仓得分（越高越可能是震仓）
        trap_score = 0      # 诱多得分（越高越可能是诱多）

        reasons = []

        # 判断1：时间间隔
        if days_diff <= 3:
            trap_score += 30
            reasons.append(f"SOS后仅{days_diff}天出现SOW，时间间隔过短（诱多信号）")
        elif days_diff <= 7:
            shakeout_score += 10
            reasons.append(f"SOS后{days_diff}天出现SOW，时间间隔适中（可能是震仓）")
        else:
            shakeout_score += 20
            reasons.append(f"SOS后{days_diff}天出现SOW，时间间隔较长（倾向震仓）")

        # 判断2：量能对比（核心判断）
        if sow_vol_ratio > sos_vol_ratio * 1.2:
            trap_score += 40
            reasons.append(
                f"SOW量比({sow_vol_ratio:.2f}) > SOS量比({sos_vol_ratio:.2f})，"
                f"巨量下跌表明真正的卖压在行动（诱多信号）"
            )
        elif sow_vol_ratio < sos_vol_ratio * 0.8:
            shakeout_score += 30
            reasons.append(
                f"SOW量比({sow_vol_ratio:.2f}) < SOS量比({sos_vol_ratio:.2f})，"
                f"缩量下跌符合震仓特征（震仓信号）"
            )
        else:
            reasons.append(
                f"SOW量比({sow_vol_ratio:.2f})与SOS量比({sos_vol_ratio:.2f})相当，"
                f"量能对比不明确"
            )

        # 判断3：SOW是否跌破关键位置
        if tr_high > 0:
            # 检查是否跌破SOS启动位（约等于区间上沿）
            if sow_low < tr_high * 0.97:
                trap_score += 20
                reasons.append(
                    f"SOW跌至{sow_low:.2f}，已跌破SOS启动位({tr_high:.2f})的3%，"
                    f"支持位失效（诱多信号）"
                )
            else:
                shakeout_score += 15
                reasons.append(
                    f"SOW最低{sow_low:.2f}，未有效跌破SOS启动位({tr_high:.2f})，"
                    f"支撑守稳（震仓信号）"
                )

        # 判断4：SOW信号类型
        if sow_signal_type == 'true_sow':
            trap_score += 25
            reasons.append("SOW为真跌破（true_sow），确认弱势（诱多信号）")
        elif sow_signal_type == 'within_range_weakness':
            shakeout_score += 10
            reasons.append("SOW为区间内弱势（within_range），可能是洗盘（震仓信号）")

        # 判断5：当前价格位置
        if tr_high > 0 and tr_low > 0:
            position = (current_price - tr_low) / (tr_high - tr_low)
            if position > 1.2:
                trap_score += 15
                reasons.append(
                    f"当前价格{current_price:.2f}位于区间上方{position*100-100:.0f}%，"
                    f"处于超买区（诱多信号）"
                )
            elif position < 0.8:
                shakeout_score += 10
                reasons.append(
                    f"当前价格{current_price:.2f}位于区间下方，"
                    f"可能是震仓后的低位（震仓信号）"
                )

        # 汇总判断
        total_score = shakeout_score + trap_score

        if total_score < 30:
            result['interpretation'] = 'weak_signal'
            result['confidence'] = 0.3
            result['reasons'] = reasons
            result['reasons'].append("信号强度不足，无法判断")
            return result

        # 计算倾向性
        if trap_score > shakeout_score:
            # 诱多陷阱占优
            result['has_conflict'] = True
            result['interpretation'] = 'trap_bearish'
            result['confidence'] = min(0.95, 0.5 + (trap_score - shakeout_score) / 200)
            
            if tr_high > 0:
                result['breakdown_level'] = {
                    "value": tr_high * 0.97,
                    "derivation": f"0.97 * tr_high_{tr_high:.2f}",
                    "note": "SOS启动位下方3%偏离"
                }
            else:
                result['breakdown_level'] = {
                    "value": sos_price * 0.95,
                    "derivation": f"0.95 * sos_price_{sos_price:.2f}",
                    "note": "SOS信号价位下方5%偏离"
                }

            result['confirmation_criteria'] = [
                f"未来3天内有效跌破{result['breakdown_level']['value']:.2f}且反弹无力",
                f"反弹时量比 < 0.7（需求枯竭）",
                f"继续下跌考验{tr_low:.2f}（区间下沿）"
            ]

            result['reasons'] = reasons + [
                f"【倾向判断】诱多陷阱（解读B）",
                f"  震仓得分: {shakeout_score} | 诱多得分: {trap_score}",
                f"  置信度: {result['confidence']*100:.0f}%",
                f"  解读: SOS可能是主力制造的诱多信号，吸引追高者进场",
                f"  SOW是主力真正的意图——出货",
                f"  巨量下跌（量比{sow_vol_ratio:.2f}）表明真正的卖压在行动"
            ]

        elif shakeout_score > trap_score:
            # 震仓洗盘占优
            result['has_conflict'] = True
            result['interpretation'] = 'shakeout_bullish'
            result['confidence'] = min(0.90, 0.5 + (shakeout_score - trap_score) / 200)
            
            if tr_low > 0:
                result['breakdown_level'] = {
                    "value": tr_low * 0.95,
                    "derivation": f"0.95 * tr_low_{tr_low:.2f}",
                    "note": "SOW低点区域下方5%偏离"
                }
            else:
                result['breakdown_level'] = {
                    "value": sos_price * 0.90,
                    "derivation": f"0.90 * sos_price_{sos_price:.2f}",
                    "note": "SOS信号价位下方10%偏离（保守）"
                }

            result['confirmation_criteria'] = [
                f"价格在{tr_high:.2f}附近快速止跌",
                f"缩量企稳（量比 < 0.7）持续3天以上",
                f"突破{current_price:.2f}创新高"
            ]

            result['reasons'] = reasons + [
                f"【倾向判断】震仓洗盘（解读A）",
                f"  震仓得分: {shakeout_score} | 诱多得分: {trap_score}",
                f"  置信度: {result['confidence']*100:.0f}%",
                f"  解读: SOS是真实的强势突破信号",
                f"  SOW是主力在突破后清洗跟风盘",
                f"  价格不会有效跌破SOS启动位置约{tr_high:.2f}元"
            ]

        else:
            # 分数接近，不确定
            result['has_conflict'] = True
            result['interpretation'] = 'uncertain'
            result['confidence'] = 0.4
            
            if tr_high > 0:
                result['breakdown_level'] = {
                    "value": tr_high * 0.97,
                    "derivation": f"0.97 * tr_high_{tr_high:.2f}",
                    "note": "SOS启动前支撑位"
                }
            else:
                result['breakdown_level'] = {
                    "value": current_price * 0.95,
                    "derivation": f"0.95 * current_price_{current_price:.2f}",
                    "note": "当前价位偏移"
                }

            result['confirmation_criteria'] = [
                f"观察是否跌破{result['breakdown_level']['value']:.2f}",
                f"等待后续3-5天的价格走势确认"
            ]

            result['reasons'] = reasons + [
                f"【倾向判断】不确定",
                f"  震仓得分: {shakeout_score} | 诱多得分: {trap_score}",
                f"  置信度: {result['confidence']*100:.0f}%",
                f"  解读: 震仓和诱多的证据相当，需要等待后续确认"
            ]

        return result

    @staticmethod
    def format_conflict_report(conflict_analysis: Dict[str, Any]) -> str:
        """
        格式化矛盾分析报告

        Args:
            conflict_analysis: analyze_sos_sow_conflict的返回结果

        Returns:
            格式化的报告文本
        """
        if not conflict_analysis.get('has_conflict'):
            return ""

        interpretation = conflict_analysis.get('interpretation', 'uncertain')
        confidence = conflict_analysis.get('confidence', 0.0)
        reasons = conflict_analysis.get('reasons', [])
        confirmation = conflict_analysis.get('confirmation_criteria', [])
        breakdown_level = conflict_analysis.get('breakdown_level')

        report = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        report += "【🚨 SOS-SOW矛盾分析】\n\n"

        # 核心判断
        if interpretation == 'trap_bearish' or interpretation == 'suspected_trap':
            report += f"**倾向判断：疑似诱多陷阱（解读B）- 看跌**\n"
            report += f"置信度：{confidence*100:.0f}%（初步判断，需等待确认）\n"
            if isinstance(breakdown_level, dict):
                report += f"关键确认位：{breakdown_level['value']:.2f} 元（依据：{breakdown_level.get('note', '')}）\n\n"
            else:
                report += f"关键确认位：{breakdown_level:.2f} 元\n\n"
        elif interpretation == 'shakeout_bullish' or interpretation == 'suspected_shakeout':
            report += f"**倾向判断：疑似震仓洗盘（解读A）- 看涨**\n"
            report += f"置信度：{confidence*100:.0f}%（初步判断，需等待确认）\n"
            if isinstance(breakdown_level, dict):
                report += f"关键确认位：{breakdown_level['value']:.2f} 元（依据：{breakdown_level.get('note', '')}）\n\n"
            else:
                report += f"关键确认位：{breakdown_level:.2f} 元\n\n"
        else:
            report += f"**倾向判断：不确定（需观察）**\n"
            report += f"置信度：{confidence*100:.0f}%\n\n"

        # 判断理由
        report += "**判断依据：**\n"
        for reason in reasons:
            if reason.startswith('【倾向判断】'):
                continue
            report += f"  • {reason}\n"

        report += "\n"

        # 确认条件
        report += f"**确认条件（未来3-5天）：**\n"
        for i, criteria in enumerate(confirmation, 1):
            report += f"  {i}. {criteria}\n"

        if breakdown_level:
            source_str = f"（{conflict_analysis.get('breakdown_source', '')}）" if conflict_analysis.get('breakdown_source') else ""
            report += f"\n**关键确认位：** {breakdown_level:.2f}元 {source_str}\n"
            report += f"  - 跌破且3天不收复 → 确认诱多陷阱\n"
            report += f"  - 快速收复并创新高 → 确认震仓洗盘\n"

        report += "\n"

        return report
