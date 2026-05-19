"""
突破分析器 - Breakout Analyzer

分析价格突破交易区间后的质量评估：
1. 真突破 vs 假突破（Upthrust）
2. 突破时的成交量特征
3. 突破后的回测行为
4. 突破置信度评分
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BreakoutAnalyzer:
    """突破分析器"""

    def __init__(self, data: pd.DataFrame):
        """
        初始化突破分析器

        Args:
            data: 价格数据，需要包含OHLCV
        """
        self.data = data

    def analyze_breakout(self, trading_range: Dict) -> Dict:
        """
        分析突破质量

        Args:
            trading_range: 交易区间信息
                {
                    'low': 区间下沿,
                    'high': 区间上沿,
                    'is_broken': 是否突破,
                    'breakout_direction': 突破方向 ('up'/'down'),
                    'current_price': 当前价格
                }

        Returns:
            突破分析结果
        """
        if not trading_range.get('is_broken'):
            return {
                'is_breakout': False,
                'reason': '交易区间未被突破'
            }

        direction = trading_range.get('breakout_direction', 'unknown')

        if direction == 'up':
            return self._analyze_upside_breakout(trading_range)
        elif direction == 'down':
            return self._analyze_downside_breakout(trading_range)
        else:
            return {
                'is_breakout': True,
                'direction': 'unknown',
                'quality': 'unknown',
                'reason': '突破方向无法确定'
            }

    def _analyze_upside_breakout(self, tr: Dict) -> Dict:
        """分析向上突破"""
        tr_high = tr.get('high', 0)
        tr_low = tr.get('low', 0)
        current_price = tr.get('current_price', 0)

        # 找到突破点（首次收盘价高于区间上沿）
        breakout_data = self.data[self.data['Close'] > tr_high]
        if len(breakout_data) == 0:
            return {
                'is_breakout': True,
                'direction': 'up',
                'quality': 'unknown',
                'reason': '无法找到突破点'
            }

        breakout_point = breakout_data.index[0]
        breakout_bar = self.data.loc[breakout_point]

        # 1. 分析突破时的成交量
        vol_analysis = self._analyze_breakout_volume(breakout_bar, tr_high)

        # 2. 分析突破后的回测行为
        pullback_analysis = self._analyze_pullback(breakout_point, tr_high)

        # 3. 分析突破后的价格行为
        post_breakout_analysis = self._analyze_post_breakout_behavior(
            breakout_point, current_price, tr_high
        )

        # 4. 综合评分
        quality_score = self._calculate_breakout_quality(
            vol_analysis, pullback_analysis, post_breakout_analysis
        )

        # 5. 判断是否为Upthrust（假突破）
        is_upthrust = self._is_upthrust(vol_analysis, post_breakout_analysis, quality_score)

        #  新增：检测Test of JOC（突破后的回测确认）
        joc_test_status = self._detect_joc_test(
            breakout_point, tr_high, current_price, pullback_analysis
        )

        return {
            'is_breakout': True,
            'direction': 'up',
            'breakout_date': breakout_point,
            'breakout_price': float(breakout_bar['Close']),
            'breakout_volume': float(breakout_bar['Volume']),
            'quality': quality_score['rating'],  # 'strong'/'weak'/'unknown'
            'quality_score': quality_score['score'],  # 0-100
            'is_upthrust': is_upthrust,
            'volume_analysis': vol_analysis,
            'pullback_analysis': pullback_analysis,
            'post_breakout_analysis': post_breakout_analysis,
            'joc_test_status': joc_test_status,  #  新增：JOC测试状态
            'conclusion': self._format_upside_conclusion(
                quality_score, is_upthrust, vol_analysis, pullback_analysis
            )
        }

    def _analyze_downside_breakout(self, tr: Dict) -> Dict:
        """分析向下突破"""
        tr_low = tr.get('low', 0)
        current_price = tr.get('current_price', 0)

        # 找到突破点（首次收盘价低于区间下沿）
        breakout_data = self.data[self.data['Close'] < tr_low]
        if len(breakout_data) == 0:
            return {
                'is_breakout': True,
                'direction': 'down',
                'quality': 'unknown',
                'reason': '无法找到突破点'
            }

        breakout_point = breakout_data.index[0]
        breakout_bar = self.data.loc[breakout_point]

        # 向下突破分析（与向上类似，但逻辑相反）
        vol_analysis = self._analyze_breakout_volume(breakout_bar, tr_low, direction='down')

        # 向下突破后的反弹测试
        rally_test = self._analyze_downside_rally_test(breakout_point, tr_low)

        quality_score = self._calculate_downside_breakout_quality(vol_analysis, rally_test)

        return {
            'is_breakout': True,
            'direction': 'down',
            'breakout_date': breakout_point,
            'breakout_price': float(breakout_bar['Close']),
            'breakout_volume': float(breakout_bar['Volume']),
            'quality': quality_score['rating'],
            'quality_score': quality_score['score'],
            'volume_analysis': vol_analysis,
            'rally_test': rally_test,
            'conclusion': self._format_downside_conclusion(quality_score, vol_analysis)
        }

    def _analyze_breakout_volume(
        self,
        breakout_bar: pd.Series,
        tr_level: float,
        direction: str = 'up'
    ) -> Dict:
        """分析突破时的成交量"""
        # 计算20日成交量均值
        breakout_idx = self.data.index.get_loc(breakout_bar.name)
        if breakout_idx < 20:
            vol_ma = self.data['Volume'].iloc[:breakout_idx].mean()
        else:
            vol_ma = self.data['Volume'].iloc[breakout_idx-20:breakout_idx].mean()

        if vol_ma == 0:
            vol_ma = self.data['Volume'].mean()

        vol_ratio = breakout_bar['Volume'] / vol_ma if vol_ma > 0 else 1.0

        # 评估成交量强度
        if direction == 'up':
            if vol_ratio >= 2.0:
                vol_strength = 'very_strong'
                vol_signal = 'bullish'
            elif vol_ratio >= 1.5:
                vol_strength = 'strong'
                vol_signal = 'bullish'
            elif vol_ratio >= 1.2:
                vol_strength = 'moderate'
                vol_signal = 'neutral'
            elif vol_ratio >= 0.8:
                vol_strength = 'weak'
                vol_signal = 'bearish'  # 缩量突破不好
            else:
                vol_strength = 'very_weak'
                vol_signal = 'very_bearish'
        else:  # direction == 'down'
            if vol_ratio >= 2.0:
                vol_strength = 'very_strong'
                vol_signal = 'bearish'
            elif vol_ratio >= 1.5:
                vol_strength = 'strong'
                vol_signal = 'bearish'
            elif vol_ratio >= 1.2:
                vol_strength = 'moderate'
                vol_signal = 'neutral'
            else:
                vol_strength = 'weak'
                vol_signal = 'neutral'  # 向下突破缩量可能是抛压枯竭

        return {
            'volume_ratio': round(vol_ratio, 2),
            'volume_ma': round(vol_ma, 0),
            'strength': vol_strength,
            'signal': vol_signal,
            'is_adequate': vol_ratio >= 1.2 if direction == 'up' else vol_ratio >= 1.0
        }

    def _analyze_pullback(
        self,
        breakout_point: pd.Timestamp,
        tr_high: float
    ) -> Dict:
        """分析突破后的回测行为（仅向上突破）"""
        # 突破后20天内的数据
        post_breakout_idx = self.data.index.get_loc(breakout_point)
        post_data = self.data.iloc[post_breakout_idx:post_breakout_idx+20]

        if len(post_data) < 3:
            return {
                'has_pullback': False,
                'reason': '突破后数据不足'
            }

        # 检查是否有回测到原区间上沿附近（±2%容差）
        pullback_zone_high = tr_high * 1.02
        pullback_zone_low = tr_high * 0.98

        has_pullback = (post_data['Low'].min() <= pullback_zone_high).any() and \
                      (post_data['Low'].min() >= pullback_zone_low).any()

        if has_pullback:
            # 找到回测点
            pullback_point = post_data[post_data['Low'] <= pullback_zone_high].iloc[0]
            pullback_vol = pullback_point['Volume']

            # 回测时的成交量应该萎缩（好迹象）
            breakout_vol = self.data.loc[breakout_point, 'Volume']
            pullback_vol_ratio = pullback_vol / breakout_vol if breakout_vol > 0 else 1.0

            return {
                'has_pullback': True,
                'pullback_date': pullback_point.name,
                'pullback_price': float(pullback_point['Low']),
                'pullback_volume_ratio': round(pullback_vol_ratio, 2),
                'is_healthy': pullback_vol_ratio < 0.8,  # 缩量回测是健康的
                'interpretation': '缩量回测' if pullback_vol_ratio < 0.8 else '放量回测'
            }
        else:
            return {
                'has_pullback': False,
                'interpretation': '无回测',
                'strength': 'strong'  # 强势突破不需要回测
            }

    def _analyze_post_breakout_behavior(
        self,
        breakout_point: pd.Timestamp,
        current_price: float,
        tr_high: float
    ) -> Dict:
        """分析突破后的价格行为"""
        breakout_idx = self.data.index.get_loc(breakout_point)
        breakout_price = self.data.loc[breakout_point, 'Close']

        # 计算突破后的涨幅
        gain_pct = (current_price - breakout_price) / breakout_price * 100 if breakout_price > 0 else 0

        # 计算突破幅度（相对于区间）
        breakout_pct = (breakout_price - tr_high) / tr_high * 100 if tr_high > 0 else 0

        # 检查是否有回吐（突破后涨幅回落）
        post_high = self.data.loc[breakout_point:, 'Close'].max()
        drawdown = (post_high - current_price) / post_high * 100 if post_high > 0 else 0

        return {
            'breakout_gain_pct': round(gain_pct, 2),
            'breakout_pct': round(breakout_pct, 2),
            'post_high': float(post_high),
            'drawdown_from_high': round(drawdown, 2),
            'is_maintaining': current_price >= breakout_price * 0.95  # 保持在突破位附近
        }

    def _is_upthrust(
        self,
        vol_analysis: Dict,
        post_breakout_analysis: Dict,
        quality_score: Dict
    ) -> bool:
        """
        判断是否为Upthrust（向上冲高诱多）

        Upthrust特征：
        1. 突破时成交量不足（缩量）
        2. 突破后快速回落
        3. 回吐大部分涨幅
        4. 质量评分低
        """
        # 特征1：缩量突破
        weak_volume = not vol_analysis.get('is_adequate', False)

        # 特征2：快速回吐（如果有足够数据）
        drawdown = post_breakout_analysis.get('drawdown_from_high', 0)
        severe_drawdown = drawdown > 50  # 回吐超过50%

        # 特征3：质量评分低
        low_quality = quality_score['score'] < 40

        # 综合判断
        upthrust_score = sum([
            weak_volume,
            severe_drawdown if drawdown > 0 else False,
            low_quality
        ])

        return upthrust_score >= 2  # 至少满足2个特征

    def _calculate_breakout_quality(
        self,
        vol_analysis: Dict,
        pullback_analysis: Dict,
        post_breakout_analysis: Dict
    ) -> Dict:
        """计算向上突破的质量评分"""
        score = 50  # 基础分

        # 成交量贡献（0-30分）
        if vol_analysis['strength'] == 'very_strong':
            score += 30
        elif vol_analysis['strength'] == 'strong':
            score += 25
        elif vol_analysis['strength'] == 'moderate':
            score += 15
        elif vol_analysis['strength'] == 'weak':
            score += 5
        else:  # very_weak
            score += 0

        # 回测行为贡献（0-20分）
        if pullback_analysis.get('has_pullback'):
            if pullback_analysis.get('is_healthy'):
                score += 20  # 缩量回测很好
            else:
                score += 10  # 放量回测一般
        else:
            score += 15  # 无回测的强势突破也不错

        # 后续行为贡献（0-20分）
        if post_breakout_analysis.get('is_maintaining'):
            score += 20  # 保持在突破位上方
        elif post_breakout_analysis.get('drawdown_from_high', 0) < 20:
            score += 15  # 回吐小于20%
        elif post_breakout_analysis.get('drawdown_from_high', 0) < 40:
            score += 10
        else:
            score += 0

        # 评级
        if score >= 80:
            rating = 'strong'
        elif score >= 60:
            rating = 'moderate'
        elif score >= 40:
            rating = 'weak'
        else:
            rating = 'very_weak'

        return {
            'score': min(100, max(0, score)),
            'rating': rating
        }

    def _analyze_downside_rally_test(
        self,
        breakout_point: pd.Timestamp,
        tr_low: float
    ) -> Dict:
        """分析向下突破后的反弹测试"""
        breakout_idx = self.data.index.get_loc(breakout_point)
        post_data = self.data.iloc[breakout_idx:breakout_idx+20]

        if len(post_data) < 3:
            return {
                'has_rally': False,
                'reason': '突破后数据不足'
            }

        # 检查是否有反弹到原区间下沿附近
        rally_zone_high = tr_low * 1.02
        rally_zone_low = tr_low * 0.98

        has_rally = (post_data['High'].max() >= rally_zone_low).all() and \
                    (post_data['High'].max() <= rally_zone_high).all()

        return {
            'has_rally': has_rally,
            'interpretation': '有反弹测试' if has_rally else '无反弹'
        }

    def _calculate_downside_breakout_quality(
        self,
        vol_analysis: Dict,
        rally_test: Dict
    ) -> Dict:
        """计算向下突破的质量评分"""
        score = 50

        # 向下突破时放量是好的（恐慌抛售）
        if vol_analysis['signal'] == 'bearish':
            score += 30
        elif vol_analysis['signal'] == 'neutral':
            score += 15
        else:
            score += 0

        # 反弹测试
        if rally_test.get('has_rally'):
            score += 20  # 有反弹测试是正常的
        else:
            score += 25  # 无反弹说明抛压强

        if score >= 80:
            rating = 'strong'
        elif score >= 60:
            rating = 'moderate'
        elif score >= 40:
            rating = 'weak'
        else:
            rating = 'very_weak'

        return {
            'score': min(100, max(0, score)),
            'rating': rating
        }

    def _format_upside_conclusion(
        self,
        quality_score: Dict,
        is_upthrust: bool,
        vol_analysis: Dict,
        pullback_analysis: Dict
    ) -> str:
        """格式化向上突破的结论"""
        lines = []

        if is_upthrust:
            lines.append("⚠️ 突破性质：疑似Upthrust（冲高诱多）")
            lines.append(f"   特征：{vol_analysis['strength']}成交量")
            if not pullback_analysis.get('has_pullback'):
                lines.append("   快速回落，突破未能维持")
        else:
            lines.append(f"✓ 突破性质：{quality_score['rating'].upper()}突破")
            lines.append(f"   成交量：{vol_analysis['strength']}（量比{vol_analysis['volume_ratio']:.1f}x）")

            if pullback_analysis.get('has_pullback'):
                lines.append(f"   回测：{pullback_analysis['interpretation']}")
            else:
                lines.append("   回测：无回测（强势特征）")

        return "\n".join(lines)

    def _detect_joc_test(
        self,
        breakout_point: pd.Timestamp,
        breakout_level: float,
        current_price: float,
        pullback_analysis: Dict
    ) -> Dict:
        """
        检测Test of JOC（JOC回测确认）

        威科夫理论：突破后的回测到突破位附近，是最佳买入点

        Args:
            breakout_point: 突破发生的时间点
            breakout_level: 突破位（原TR上沿）
            current_price: 当前价格
            pullback_analysis: 回测分析结果

        Returns:
            JOC测试状态
        """
        # 已经有回测分析
        if pullback_analysis.get('has_pullback'):
            pullback_price = pullback_analysis.get('pullback_price', 0)
            is_healthy = pullback_analysis.get('is_healthy', False)

            # 回测到突破位附近（±5%容差）
            test_zone_high = breakout_level * 1.05
            test_zone_low = breakout_level * 0.95

            if test_zone_low <= pullback_price <= test_zone_high:
                # 成功的Test of JOC
                return {
                    'tested': True,
                    'test_price': float(pullback_price),
                    'test_date': str(pullback_analysis.get('pullback_date', '')),
                    'is_healthy': is_healthy,
                    'interpretation': 'healthy_test' if is_healthy else 'risky_test',
                    'confidence': 'high' if is_healthy else 'medium'
                }

        # 检查当前价格是否接近回测区间（正在发生回测）
        if current_price < breakout_level * 1.08:  # 在突破位上方8%以内
            distance_pct = (current_price / breakout_level - 1) * 100
            return {
                'tested': False,
                'in_progress': True,
                'current_distance_pct': round(distance_pct, 1),
                'target_zone': f"{breakout_level * 0.95:.2f} - {breakout_level * 1.05:.2f}",
                'interpretation': 'approaching_test',
                'recommendation': f'价格接近回测区间({breakout_level:.2f}元附近)，密切关注'
            }

        # 尚未回测
        return {
            'tested': False,
            'in_progress': False,
            'interpretation': 'no_test_yet',
            'current_distance_from_breakout': round((current_price / breakout_level - 1) * 100, 1),
            'recommendation': '等待回测突破位(原阻力区)以确认突破有效性'
        }

    def _format_downside_conclusion(
        self,
        quality_score: Dict,
        vol_analysis: Dict
    ) -> str:
        """格式化向下突破的结论"""
        lines = []

        lines.append(f"✓ 突破性质：{quality_score['rating'].upper()}突破")
        lines.append(f"   成交量：{vol_analysis['strength']}（量比{vol_analysis['volume_ratio']:.1f}x）")

        return "\n".join(lines)

    def get_override_recommendation(
        self,
        trading_range: Dict,
        current_phase: str
    ) -> Tuple[str, str, float]:
        """
        基于突破分析获取阶段覆盖建议

        Returns:
            (新阶段, 理由, 置信度调整系数)
        """
        if not trading_range.get('is_broken'):
            return current_phase, "", 1.0

        direction = trading_range.get('breakout_direction')

        # 向上突破 + 派发判断 → 强制否决
        if direction == 'up' and 'Distribution' in current_phase:
            return (
                "Trending / Reaccumulation",
                f"TR向上突破至{trading_range['current_price']:.2f}元，否决了'派发'假设",
                0.6  # 降低置信度
            )

        # 向下突破 + 吸筹判断 → 强制否决
        if direction == 'down' and 'Accumulation' in current_phase:
            return (
                "Markdown / Trending Down",
                f"TR向下突破至{trading_range['current_price']:.2f}元，否决了'吸筹'假设",
                0.6
            )

        # 其他情况
        return current_phase, "", 1.0
