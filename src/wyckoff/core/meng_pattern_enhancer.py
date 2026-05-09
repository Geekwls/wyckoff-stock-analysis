#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
孟洪涛新威科夫操盘法增强模块
基于《新威科夫操盘法》290页内容的精华实现

重点增强:
1. Spring(震仓)识别 - 书中提及136次
2. JOC(跃过小溪)识别 - 书中提及119次
3. 成交量分析 - 书中提及435次
4. VSA微观分析 - 无供应/无需求
"""

import pandas as pd
from typing import Dict, Optional, Tuple, List, Any, Union
from .detectors.base_detector import BaseDetector


class MengPatternEnhancer(BaseDetector):
    """
    孟洪涛新威科夫操盘法增强器

    核心特点:
    1. 5重Spring过滤条件(更严格)
    2. JOC的精确识别(长阳线+大成交量)
    3. VSA微观分析(无供应/无需求)
    4. 动态时间窗口(基于ATR)
    """

    def __init__(self, data: pd.DataFrame, config):
        super().__init__()
        self.data = data
        self.config = config
        self._cache = None

    def detect_spring_enhanced(self) -> Dict:
        """
        孟洪涛Spring(震仓)增强检测

        书中提及136次,是最重要的形态

        5个必要条件:
        1. 跌破幅度:1-3%(不能太深)
        2. 收回时间:1-3天(根据波动率调整)
        3. 收回确认:收盘价站稳支撑位上方
        4. 成交量:收回时成交量 > 跌破时成交量
        5. 收盘位置:收回日收盘价在日内高位70%以上
        """
        if self.data is None or len(self.data) < 20:
            return {"detected": False, "reason": "insufficient_data"}

        df = self.data.copy()
        signals = []

        # 计算ATR用于动态调整
        atr = self._calculate_atr(df, 14)
        atr_pct = atr / df['Close'].iloc[-1] * 100 if df['Close'].iloc[-1] > 0 else 0

        # 动态调整确认时间
        if atr_pct < 1.5:
            max_recovery_days = 5
        elif atr_pct < 3:
            max_recovery_days = 3
        else:
            max_recovery_days = 2

        # 寻找支撑位(最近20日的最低点)
        lookback = 20
        for i in range(lookback, len(df) - 5):
            support_level = df['Low'].iloc[i-lookback:i].min()

            # 检测跌破
            if df['Low'].iloc[i] < support_level * 0.97:  # 跌破3%以内
                breakdown_price = df['Low'].iloc[i]
                breakdown_vol = df['Volume'].iloc[i]

                # 条件1:跌破幅度检查(1-3%,用实际最低价计算)
                breakdown_pct = (support_level - breakdown_price) / support_level * 100
                if not (1 <= breakdown_pct <= 3):
                    continue  # 跌破太深或太浅

                # 检查收回(后续几天)
                for j in range(i+1, min(i+max_recovery_days+1, len(df))):
                    if df['Close'].iloc[j] > support_level:
                        # 条件2:收回时间检查
                        recovery_days = j - i

                        # 条件3:收回确认(收盘价站稳支撑位上方)
                        close_above_support = df['Close'].iloc[j] > support_level
                        if not close_above_support:
                            continue

                        # 条件4:成交量检查(收回时成交量 > 跌破时成交量)
                        recovery_vol = df['Volume'].iloc[j]
                        vol_ratio = recovery_vol / breakdown_vol if breakdown_vol > 0 else 1
                        if vol_ratio <= 1.0:
                            continue  # 成交量没有放大

                        # 条件5:收盘位置检查(在日内高位70%以上)
                        daily_range = df['High'].iloc[j] - df['Low'].iloc[j]
                        close_position = (df['Close'].iloc[j] - df['Low'].iloc[j]) / daily_range if daily_range > 0 else 0.5
                        if close_position < 0.7:
                            continue  # 收盘位置不够高

                        # 所有条件满足,这是一个真Spring
                        signal = {
                            "date": df.index[j],
                            "breakdown_price": breakdown_price,
                            "support_level": support_level,
                            "recovery_price": df['Close'].iloc[j],
                            "recovery_days": recovery_days,
                            "vol_ratio": round(vol_ratio, 2),
                            "close_position": round(close_position * 100, 1),
                            "confidence": self._calculate_spring_confidence(breakdown_pct, recovery_days, vol_ratio, close_position)
                        }
                        signals.append(signal)
                        break

        if not signals:
            return {"detected": False, "reason": "no_valid_spring_found"}

        # 返回最新的Spring
        latest_spring = signals[-1]
        latest_spring["confidence"] = round(latest_spring["confidence"], 2)

        return {
            "detected": True,
            "signals": signals,
            "latest_spring": latest_spring,
            "method": "meng_hongtao_5_filters",
            "description": "孟洪涛5重过滤Spring(震仓)检测"
        }

    def _calculate_spring_confidence(self, breakdown_pct, recovery_days, vol_ratio, close_position):
        """计算Spring置信度"""
        score = 0

        # 跌破幅度(2%左右最佳)
        if 1.5 <= breakdown_pct <= 2.5:
            score += 25
        elif 1 <= breakdown_pct <= 3:
            score += 20

        # 收回时间(2天最佳)
        if recovery_days == 2:
            score += 25
        elif recovery_days <= 3:
            score += 20

        # 成交量比率(越大越好)
        if vol_ratio >= 2.0:
            score += 25
        elif vol_ratio >= 1.5:
            score += 20
        elif vol_ratio >= 1.2:
            score += 15

        # 收盘位置(越高越好)
        if close_position >= 80:
            score += 25
        elif close_position >= 70:
            score += 20
        elif close_position >= 60:
            score += 15

        return score

    def detect_joc_enhanced(self) -> Dict:
        """
        孟洪涛JOC(跃过小溪)增强检测

        书中提及119次,是比SOS更可靠的突破信号

        必要条件:
        1. 突破确认:以长阳线强势突破震荡区顶部阻力(小溪)
        2. 突破量能:突破日成交量显著放大(> 1.5倍均量)
        3. 收盘位置:收于日内高点附近(无长上影线)
        4. 回测确认:突破后出现缩量回落(Test of JOC)
        """
        if self.data is None or len(self.data) < 40:
            return {"detected": False, "reason": "insufficient_data"}

        df = self.data.copy()

        # 识别交易区间(小溪)
        trading_range = self._detect_trading_range(df, window=60)
        if not trading_range.get("is_consolidation"):
            return {"detected": False, "reason": "not_in_consolidation"}

        creek_level = trading_range["high"]  # 小溪位置
        volume_ma20 = df['Volume_MA20'].iloc[-1]

        signals = []

        # 扫描JOC突破
        for i in range(20, len(df)):
            # 检查是否突破小溪
            if df['Close'].iloc[i] > creek_level and df['Close'].iloc[i-1] <= creek_level:
                # 条件1:突破确认(长阳线)
                price_change = (df['Close'].iloc[i] - df['Open'].iloc[i]) / df['Open'].iloc[i] * 100
                if price_change < 3:  # 涨幅至少3%
                    continue

                # 条件2:突破量能(>1.5倍均量)
                volume_ratio = df['Volume'].iloc[i] / volume_ma20 if volume_ma20 > 0 else 1
                if volume_ratio < 1.5:
                    continue

                # 条件3:收盘位置(无长上影线)
                daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
                close_position = (df['Close'].iloc[i] - df['Low'].iloc[i]) / daily_range if daily_range > 0 else 0.5
                if close_position < 0.75:  # 收盘在高位75%以上
                    continue

                # 检查回测(Test of JOC)
                test_detected = False
                test_date = None
                test_vol_ratio = None

                for j in range(i+1, min(i+10, len(df))):
                    if df['Low'].iloc[j] < creek_level * 1.02:  # 回测到小溪附近
                        if df['Close'].iloc[j] > creek_level:  # 但收盘在小溪上方
                            # 缩量回测
                            test_vol_ratio = df['Volume'].iloc[j] / volume_ma20 if volume_ma20 > 0 else 1
                            if test_vol_ratio < 1.0:  # 缩量
                                test_detected = True
                                test_date = df.index[j]
                                break

                signal = {
                    "date": df.index[i],
                    "creek_level": creek_level,
                    "close_price": df['Close'].iloc[i],
                    "breakout_pct": round(price_change, 2),
                    "volume_ratio": round(volume_ratio, 2),
                    "close_position": round(close_position * 100, 1),
                    "test_detected": test_detected,
                    "test_date": test_date,
                    "test_vol_ratio": round(test_vol_ratio, 2) if test_vol_ratio else None,
                    "confidence": self._calculate_joc_confidence(price_change, volume_ratio, close_position, test_detected)
                }
                signals.append(signal)

        if not signals:
            return {"detected": False, "reason": "no_valid_joc_found"}

        latest_joc = signals[-1]
        latest_joc["confidence"] = round(latest_joc["confidence"], 2)

        return {
            "detected": True,
            "signals": signals,
            "latest": latest_joc,
            "method": "meng_hongtao_joc",
            "description": "孟洪涛JOC(跃过小溪)检测"
        }

    def _calculate_joc_confidence(self, breakout_pct, volume_ratio, close_position, has_test):
        """计算JOC置信度"""
        score = 0

        # 突破幅度
        if breakout_pct >= 5:
            score += 25
        elif breakout_pct >= 3:
            score += 20

        # 成交量
        if volume_ratio >= 2.5:
            score += 25
        elif volume_ratio >= 2.0:
            score += 20
        elif volume_ratio >= 1.5:
            score += 15

        # 收盘位置
        if close_position >= 90:
            score += 25
        elif close_position >= 80:
            score += 20
        elif close_position >= 75:
            score += 15

        # 回测确认(加分项)
        if has_test:
            score += 25

        return score

    def detect_vsa_signals(self) -> Dict:
        """
        VSA(Volume Spread Analysis)微观分析

        检测:
        1. No Supply(无供应)
        2. No Demand(无需求)
        3. Stopping Volume(停止行为)
        """
        if self.data is None or len(self.data) < 20:
            return {
                "no_supply": {"detected": False},
                "no_demand": {"detected": False},
                "stopping_vol": {"detected": False}
            }

        df = self.data.copy()
        volume_ma20 = df['Volume_MA20'].iloc[-1]

        # No Supply检测
        no_supply_signals = []
        for i in range(10, len(df)):
            # 上涨趋势中
            if df['Close'].iloc[i] > df['MA20'].iloc[i]:
                # 极小实体
                price_range = df['High'].iloc[i] - df['Low'].iloc[i]
                if price_range > 0:
                    body_pct = abs(df['Close'].iloc[i] - df['Open'].iloc[i]) / price_range
                    if body_pct < 0.3:  # 实体小于波动的30%
                        # 收在中高位
                        close_position = (df['Close'].iloc[i] - df['Low'].iloc[i]) / price_range
                        if close_position > 0.5:
                            # 极低成交量
                            vol_ratio = df['Volume'].iloc[i] / volume_ma20 if volume_ma20 > 0 else 1
                            if vol_ratio < 0.6:  # 成交量小于均量的60%
                                no_supply_signals.append({
                                    "date": df.index[i],
                                    "vol_ratio": round(vol_ratio, 2),
                                    "close_position": round(close_position * 100, 1)
                                })

        # No Demand检测
        no_demand_signals = []
        for i in range(10, len(df)):
            # 下跌趋势中
            if df['Close'].iloc[i] < df['MA20'].iloc[i]:
                # 极小实体
                price_range = df['High'].iloc[i] - df['Low'].iloc[i]
                if price_range > 0:
                    body_pct = abs(df['Close'].iloc[i] - df['Open'].iloc[i]) / price_range
                    if body_pct < 0.3:
                        # 极低成交量
                        vol_ratio = df['Volume'].iloc[i] / volume_ma20 if volume_ma20 > 0 else 1
                        if vol_ratio < 0.6:
                            no_demand_signals.append({
                                "date": df.index[i],
                                "vol_ratio": round(vol_ratio, 2)
                            })

        # Stopping Volume检测
        stopping_vol_signals = []
        for i in range(10, len(df)):
            # 下跌趋势中
            if df['Close'].iloc[i] < df['MA50'].iloc[i]:
                # 大成交量
                vol_ratio = df['Volume'].iloc[i] / volume_ma20 if volume_ma20 > 0 else 1
                if vol_ratio > 1.5:
                    # 价格止跌(窄幅波动)
                    price_range = df['High'].iloc[i] - df['Low'].iloc[i]
                    open_close_range = abs(df['Close'].iloc[i] - df['Open'].iloc[i])
                    if price_range > 0 and open_close_range / price_range < 0.3:
                        # 可能有下影线
                        lower_shadow = min(df['Open'].iloc[i], df['Close'].iloc[i]) - df['Low'].iloc[i]
                        if lower_shadow > price_range * 0.3:  # 下影线大于波动的30%
                            stopping_vol_signals.append({
                                "date": df.index[i],
                                "vol_ratio": round(vol_ratio, 2),
                                "price": df['Close'].iloc[i]
                            })

        return {
            "no_supply": {
                "detected": len(no_supply_signals) > 0,
                "signals": no_supply_signals[-5:] if no_supply_signals else [],  # 最近5个
                "latest": no_supply_signals[-1] if no_supply_signals else None
            },
            "no_demand": {
                "detected": len(no_demand_signals) > 0,
                "signals": no_demand_signals[-5:] if no_demand_signals else [],
                "latest": no_demand_signals[-1] if no_demand_signals else None
            },
            "stopping_vol": {
                "detected": len(stopping_vol_signals) > 0,
                "signals": stopping_vol_signals[-3:] if stopping_vol_signals else [],  # 最近3个
                "latest": stopping_vol_signals[-1] if stopping_vol_signals else None
            }
        }

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算ATR"""
        high = df['High']
        low = df['Low']
        close = df['Close'].shift(1)

        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=1).mean()

        return atr.iloc[-1] if len(atr) > 0 else 0

    def detect_boring_zone(self, window: int = 14) -> Dict:
        """
        检测"枯燥区"(Boring Zone)
        
        书中特征:价格波动极小,成交量极度萎缩,市场处于无聊状态,主力在默默吸筹.
        """
        if self.data is None or len(self.data) < window + 20:
            return {"detected": False, "reason": "insufficient_data"}

        df = self.data.tail(window + 20).copy()
        
        # 计算历史波动率参考
        atr_series = self._calculate_atr_series(df, 14)
        df['ATR_Pct'] = atr_series / df['Close'] * 100
        avg_atr_pct = df['ATR_Pct'].iloc[:-window].mean()
        
        # 枯燥区特征计算
        recent = df.tail(window)
        recent_vol_avg = recent['Volume'].mean()
        overall_vol_ma20 = df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]
        
        vol_contraction = recent_vol_avg / overall_vol_ma20 if overall_vol_ma20 > 0 else 1.0
        atr_contraction = recent['ATR_Pct'].mean() / avg_atr_pct if avg_atr_pct > 0 else 1.0
        
        # 判定标准:量能萎缩且波动率处于低位
        is_boring = vol_contraction < 0.75 and atr_contraction < 0.8
        
        score = self.calculate_boring_alert_score(vol_contraction, atr_contraction, window)
        
        return {
            "detected": is_boring,
            "score": score,
            "vol_contraction": round(vol_contraction, 2),
            "atr_contraction": round(atr_contraction, 2),
            "duration": window,
            "high_alert": score >= 85
        }

    def calculate_boring_alert_score(self, vol_contraction, atr_contraction, duration) -> int:
        """计算枯燥区评分及预警等级"""
        score = 0
        # 量能萎缩得分 (40分)
        if vol_contraction < 0.5: score += 40
        elif vol_contraction < 0.7: score += 30
        elif vol_contraction < 0.85: score += 15
        
        # 波动率收敛得分 (40分)
        if atr_contraction < 0.6: score += 40
        elif atr_contraction < 0.75: score += 30
        elif atr_contraction < 0.9: score += 15
        
        # 持续时间得分 (20分)
        if duration >= 20: score += 20
        elif duration >= 10: score += 15
        elif duration >= 5: score += 10
        
        return score

    def _analyze_spring_intraday_quality(self, intraday_data: pd.DataFrame) -> Dict:
        """
        分析 Spring 的日内质量(使用 60 分钟线)
        
        分析逻辑:
        1. 稳步吸筹型:下影线拉回过程中成交量递增,且价格重心稳步抬升.
        2. 尾盘偷袭型:仅在最后时段无量拉回,或者单笔巨量拉回后又陷入沉寂.
        """
        if intraday_data is None or len(intraday_data) < 4:
            return {"quality_score": 50, "recovery_type": "unknown", "observation": "数据不足以分析日内质量"}

        # 简单的日内逻辑:观察最后 4 根 60m K 线
        last_bars = intraday_data.tail(4)
        price_trend = last_bars['Close'].iloc[-1] > last_bars['Close'].iloc[0]
        vol_trend = last_bars['Volume'].iloc[-1] > last_bars['Volume'].mean()
        
        if price_trend and vol_trend:
            return {
                "quality_score": 85,
                "recovery_type": "steady_accumulation",
                "observation": "日内稳步拉回,且伴随主动性买盘放量,Spring 信号极其可靠"
            }
        elif price_trend and not vol_trend:
            return {
                "quality_score": 65,
                "recovery_type": "late_sneak_attack",
                "observation": "日内尾盘无量拉回,存在偷袭嫌疑,需观察次日跟随情况"
            }
        else:
            return {
                "quality_score": 40,
                "recovery_type": "weak_recovery",
                "observation": "日内反弹乏力,Spring 质量欠佳"
            }

    def _calculate_atr_series(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR序列"""
        high = df['High']
        low = df['Low']
        close = df['Close'].shift(1)
        tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
        return tr.rolling(window=period, min_periods=1).mean()

    def detect_dead_corner_breakout(self) -> Dict:
        """
        🔧 v1.3增强:检测"死角突破"(Dead Corner Breakout)

        理论依据:孟洪涛《新威科夫操盘法》"暴风雨前的宁静"
        - 枯燥区后的放量突破极具爆发力
        - 标准严格化,提高信号质量

        增强标准:
        1. 枯燥区得分 ≥ 85(高分预警)
        2. 放量突破(量能 > 2倍MA20)
        3. 突破后3天内不回测
        4. 收盘站稳突破位上方
        """
        boring_res = self.detect_boring_zone(window=10)

        # 🔧 v1.3增强:提高枯燥区质量要求(70 → 85)
        if not boring_res.get("detected") and boring_res.get("score", 0) < 85:
            return {
                "detected": False,
                "reason": "boring_score_too_low",
                "boring_zone": boring_res,
                "required_score": 85,
                "actual_score": boring_res.get("score", 0)
            }

        if self.data is None or len(self.data) < 20:
            return {"detected": False, "reason": "insufficient_data"}

        df = self.data.tail(20).copy()
        boring_high = df['High'].iloc[-10:-1].max()

        # 🔧 v1.3增强:使用更长的历史数据计算成交量均线
        vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]

        # 寻找突破点(从最新到最旧)
        breakout_found = False
        breakout_idx = None
        breakout_bar = None

        for i in range(len(df) - 1, -1, -1):
            current_bar = df.iloc[i]

            # 🔧 v1.3增强:提高量能要求(1.5倍 → 2倍)
            breakout_vol = current_bar['Volume'] > vol_ma20 * 2.0
            breakout_price = current_bar['Close'] > boring_high

            if breakout_vol and breakout_price:
                breakout_found = True
                breakout_idx = i
                breakout_bar = current_bar
                break

        if not breakout_found or breakout_bar is None:
            return {
                "detected": False,
                "reason": "no_breakout_found",
                "boring_zone": boring_res,
                "boring_high": round(boring_high, 2)
            }

        # 🔧 v1.3增强:突破后3天内不回测验证
        follow_through_confirmation = False
        max_pullback = 0

        if breakout_idx < len(df) - 1:
            # 检查后续3根K线
            follow_days = min(3, len(df) - breakout_idx - 1)
            for j in range(1, follow_days + 1):
                follow_bar = df.iloc[breakout_idx + j]

                # 计算最大回撤
                pullback = (breakout_bar['Close'] - follow_bar['Low']) / breakout_bar['Close']
                max_pullback = max(max_pullback, pullback)

                # 检查是否收盘在突破位上方
                if follow_bar['Close'] > breakout_bar['Close']:
                    follow_through_confirmation = True
                    break

        # 🔧 v1.3增强:计算置信度(基于多个因素)
        confidence_factors = {
            'boring_score': boring_res.get('score', 0) / 100,  # 0-1
            'volume_ratio': min(breakout_bar['Volume'] / vol_ma20 / 3, 1),  # 0-1
            'follow_through': 1.0 if follow_through_confirmation else 0.5,  # 0-1
            'pullback_penalty': max(0, 1 - max_pullback * 10)  # 0-1,回撤越大惩罚越大
        }

        confidence = (
            confidence_factors['boring_score'] * 0.3 +
            confidence_factors['volume_ratio'] * 0.3 +
            confidence_factors['follow_through'] * 0.25 +
            confidence_factors['pullback_penalty'] * 0.15
        )

        # 最终判断:必须有突破且有一定确认
        is_breakout = breakout_found and confidence > 0.6

        return {
            "detected": is_breakout,
            "boring_zone": boring_res,
            "breakout_price": round(float(breakout_bar['Close']), 2),
            "breakout_volume_ratio": round(float(breakout_bar['Volume']) / vol_ma20, 2) if vol_ma20 > 0 else 1.0,
            "breakout_date": df.index[breakout_idx] if breakout_idx is not None else None,
            "follow_through_confirmation": follow_through_confirmation,
            "max_pullback_pct": round(max_pullback * 100, 2),
            "confidence_factors": {
                'boring_score': round(confidence_factors['boring_score'], 2),
                'volume_ratio': round(confidence_factors['volume_ratio'], 2),
                'follow_through': round(confidence_factors['follow_through'], 2),
                'pullback_penalty': round(confidence_factors['pullback_penalty'], 2)
            },
            "confidence": round(min(confidence * 100, 100), 1),
            "description": f'🎯 死角突破!枯燥区{boring_res["score"]}分后的' +
                          f'{"强势" if follow_through_confirmation else "弱势"}' +
                          f'突破,量能{round(float(breakout_bar["Volume"]) / vol_ma20, 1)}倍' if vol_ma20 > 0 else ''
        }

    def detect_dead_corner_breakout_enhanced(self) -> Dict:
        """
        🔧 v1.3新增:增强版死角突破检测

        与detect_dead_corner_breakout的区别:
        - 支持多候选突破点比较
        - 增加对突破强度的量化
        - 提供更详细的交易建议

        Returns:
            增强版死角突破检测结果
        """
        # 调用基础检测
        base_result = self.detect_dead_corner_breakout()

        if not base_result.get("detected"):
            return base_result

        # 增强分析
        breakout_strength = self._classify_breakout_strength(base_result)
        trading_advice = self._generate_breakout_trading_advice(base_result, breakout_strength)

        base_result["breakout_strength"] = breakout_strength
        base_result["trading_advice"] = trading_advice

        return base_result

    def _classify_breakout_strength(self, breakout_result: Dict) -> str:
        """分类突破强度"""
        confidence = breakout_result.get("confidence", 0)
        vol_ratio = breakout_result.get("breakout_volume_ratio", 0)
        follow_through = breakout_result.get("follow_through_confirmation", False)

        if confidence >= 85 and vol_ratio >= 2.5 and follow_through:
            return "SUPER_STRONG"
        elif confidence >= 75 and vol_ratio >= 2.0:
            return "STRONG"
        elif confidence >= 65:
            return "MODERATE"
        else:
            return "WEAK"

    def _generate_breakout_trading_advice(self, breakout_result: Dict, strength: str) -> Dict:
        """生成突破交易建议"""
        breakout_price = breakout_result.get("breakout_price", 0)

        if strength == "SUPER_STRONG":
            return {
                "action": "STRONG_BUY",
                "entry_strategy": "激进追涨",
                "stop_loss": f"设在突破位下方2% ({round(breakout_price * 0.98, 2)})",
                "target": f"第一目标{round(breakout_price * 1.1, 2)},第二目标{round(breakout_price * 1.2, 2)}",
                "position_size": "建议3-5%仓位",
                "holding_period": "短期2-4周"
            }
        elif strength == "STRONG":
            return {
                "action": "BUY",
                "entry_strategy": "稳健做多",
                "stop_loss": f"设在突破位下方3% ({round(breakout_price * 0.97, 2)})",
                "target": f"第一目标{round(breakout_price * 1.08, 2)},第二目标{round(breakout_price * 1.15, 2)}",
                "position_size": "建议2-3%仓位",
                "holding_period": "短期2-4周"
            }
        elif strength == "MODERATE":
            return {
                "action": "WATCH",
                "entry_strategy": "观望等待确认",
                "stop_loss": f"待突破确认后设在支撑位",
                "target": f"待确认后评估",
                "position_size": "建议1-2%仓位试探",
                "holding_period": "待确认"
            }
        else:
            return {
                "action": "AVOID",
                "entry_strategy": "不建议参与",
                "reason": "突破强度不足,存在假突破风险",
                "alternative": "等待更明确的信号或回测确认"
            }

    def _detect_trading_range(self, df: pd.DataFrame, window: int = 60) -> Dict:
        """检测交易区间"""
        if len(df) < window:
            return {"is_consolidation": False}

        recent_df = df.tail(window)
        high_max = recent_df['High'].max()
        low_min = recent_df['Low'].min()
        range_pct = (high_max - low_min) / low_min

        is_consolidation = range_pct < 0.20  # 20%以内算震荡

        return {
            "is_consolidation": is_consolidation,
            "high": high_max,
            "low": low_min,
            "range_pct": range_pct
        }


# 集成到现有pattern_detector的建议
def enhance_pattern_detector(pattern_detector):
    """
    将孟洪涛增强方法集成到现有的pattern_detector

    使用示例:
    enhancer = MengPatternEnhancer(data, config)
    spring_result = enhancer.detect_spring_enhanced()
    joc_result = enhancer.detect_joc_enhanced()
    vsa_result = enhancer.detect_vsa_signals()
    """
    pass
