import pandas as pd
import numpy as np
import logging
from typing import Dict, List
from .base_detector import BaseDetector

logger = logging.getLogger(__name__)

class MengVsaDetector(BaseDetector):
    """
    孟洪涛增强型 VSA 检测器
    (VSA Signals, Boring Zone)
    """
    def __init__(self, data: pd.DataFrame, config, thresholds, indicator_cache=None):
        super().__init__(indicator_cache=indicator_cache)
        self.data = data
        self.config = config
        self.thresholds = thresholds

    def detect_vsa_signals(self) -> Dict:
        """
        🔧 修复#6: VSA 信号检测优化 - 调整阈值符合孟洪涛理论
        
        孟洪涛理论标准：
        - No Supply: 量比<0.5（极度萎缩），收盘位置>60%（中高位）
        - No Demand: 量比<0.5，收盘位置<40%（低位），出现在下跌反弹中
        - Stopping Volume: 量比>2.0（显著放大），实体<30%，下影线>30%
        """
        if self.data is None or len(self.data) < 20:
            return {"no_supply": {"detected": False}, "no_demand": {"detected": False}, "stopping_vol": {"detected": False}}
        df = self.data.copy()
        vol_ma20 = df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]
        ns, nd, sv = [], [], []
        t = self.thresholds
        
        # 🔧 优化：在循环外部一次性计算移动平均线，彻底解决每次循环内全量重算的严重性能漏洞
        ma5 = df['Close'].rolling(5).mean()
        ma20 = df['MA20'] if 'MA20' in df.columns else df['Close'].rolling(20).mean()
        ma50 = df['MA50'] if 'MA50' in df.columns else df['Close'].rolling(50).mean()
        
        for i in range(10, len(df)):
            pr = df['High'].iloc[i] - df['Low'].iloc[i]
            if pr <= 0: continue
            body_pct, vol_r = abs(df['Close'].iloc[i] - df['Open'].iloc[i]) / pr, df['Volume'].iloc[i] / vol_ma20 if vol_ma20 > 0 else 1
            
            # 计算 5 日均线价格重心波段方向 (Swing Direction)
            swing_dir = 1 if (i > 0 and ma5.iloc[i] > ma5.iloc[i-1]) else -1
            
            # 计算 60 日交易区间内部相对位置 (TR Position)
            tr_high = df['High'].iloc[max(0, i-59):i+1].max()
            tr_low = df['Low'].iloc[max(0, i-59):i+1].min()
            tr_diff = tr_high - tr_low
            tr_pos = (df['Close'].iloc[i] - tr_low) / tr_diff if tr_diff > 0 else 0.5

            # ─────────────────────────────────────────────────────────────────
            # Wave 4 偏差一修正：Tom Williams VSA 比较性缩量双重锚定约束
            # 理论依据：No Supply / No Demand 是比较性信号，当前缩量必须相对于
            # 前序放量才有意义。仅凭绝对均线阈值，会在整体低量环境下漏报高质量
            # 回踩，也会在量能反弹时产生误报。
            # ─────────────────────────────────────────────────────────────────

            # 涨跌停识别：A 股涨跌停时成交量被动萎缩，不具备比较意义
            # 以前收盘价为基准，当日涨跌幅超过 9.5% 判定为触板（含 ST 股 5% 板）
            prev_close = df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]
            daily_chg_pct = abs(df['Close'].iloc[i] - prev_close) / max(prev_close, 1e-9)
            is_limit_day = daily_chg_pct >= 0.095  # 涨停/跌停日

            # 次日也需要排除（涨跌停次日流动性仍异常）
            is_post_limit_day = False
            if i >= 1:
                prev_prev_close = df['Close'].iloc[i-2] if i >= 2 else df['Close'].iloc[i-1]
                prev_chg_pct = abs(df['Close'].iloc[i-1] - prev_prev_close) / max(prev_prev_close, 1e-9)
                is_post_limit_day = prev_chg_pct >= 0.095

            # 比较性低量：V_t < V_{t-1} AND V_t < V_{t-2}
            vol_t = df['Volume'].iloc[i]
            vol_t1 = df['Volume'].iloc[i-1] if i >= 1 else vol_t + 1
            vol_t2 = df['Volume'].iloc[i-2] if i >= 2 else vol_t + 1
            is_comparative_low = (vol_t < vol_t1) and (vol_t < vol_t2)

            # 综合低量判断：绝对标准 OR（动态标准 + 比较性约束）
            # 涨跌停日及次日跳过比较性约束（避免被动缩量误判）
            if is_limit_day or is_post_limit_day:
                is_vsa_low_vol = vol_r < 0.5  # 仅用绝对标准兜底
            else:
                is_vsa_low_vol = (vol_r < 0.5) or (vol_r < 1.0 and is_comparative_low)
            
            # 记录低量类型，用于 description 说明
            vol_mode = "limit_day_passive" if (is_limit_day or is_post_limit_day) else (
                "comparative" if (vol_r >= 0.5 and is_comparative_low) else "absolute"
            )

            # 🔧 优化后的 No Supply 检测
            # 背景要求：上涨波段中，或者在下跌波段且价格回调至区间下轨（tr_pos < 0.4）
            is_no_supply_bg = (swing_dir == 1) or (swing_dir == -1 and tr_pos < 0.4)
            if is_no_supply_bg:
                if body_pct < t.MENG_VSA_BODY_RATIO:
                    cp = (df['Close'].iloc[i] - df['Low'].iloc[i]) / pr
                    # 孟洪涛要求：低量，收盘在中高位（>60%）
                    if cp > 0.6 and is_vsa_low_vol:
                        is_bottom_test = (swing_dir == -1 and tr_pos < 0.4)
                        desc_vol = {
                            "absolute": "上升趋势无供应（卖盘枯竭）" if not is_bottom_test else "底部无供应测试（主力吸筹后期）",
                            "comparative": "[VSA比较性缩量] 量能低于前序两日，卖盘相对萎缩" + ("，底部测试" if is_bottom_test else ""),
                            "limit_day_passive": "涨跌停后被动缩量，量能可信度低，需结合前后量能判断"
                        }.get(vol_mode, "无供给信号")
                        ns.append({
                            "date": df.index[i], 
                            "vol_ratio": round(vol_r, 2),
                            "vol_mode": vol_mode,
                            "is_comparative_low": is_comparative_low,
                            "close_position": round(cp * 100, 1),
                            "tr_position": round(tr_pos * 100, 1),
                            "swing_direction": "UP" if swing_dir == 1 else "DOWN",
                            "is_bottom_test": is_bottom_test,
                            "description": desc_vol
                        })
            
            # 🔧 优化后的 No Demand 检测：添加位置约束和趋势判断
            # 背景要求：下跌波段中，或者在上涨波段且价格反弹至区间上轨（tr_pos > 0.6）
            is_no_demand_bg = (swing_dir == -1) or (swing_dir == 1 and tr_pos > 0.6)
            if is_no_demand_bg:
                if body_pct < 0.3 and is_vsa_low_vol:
                    cp = (df['Close'].iloc[i] - df['Low'].iloc[i]) / pr
                    # 孟洪涛要求：出现在下跌中，收盘在低位（<40%）
                    if cp < 0.4:
                        is_top_test = (swing_dir == 1 and tr_pos > 0.6)
                        desc_nd = {
                            "absolute": "顶部无需求测试（上涨受阻）" if is_top_test else "下跌趋势无需求（买盘枯竭）",
                            "comparative": "[VSA比较性缩量] 量能低于前序两日，" + ("顶部需求萎缩" if is_top_test else "下行买盘枯竭"),
                            "limit_day_passive": "涨跌停后被动缩量，量能可信度低，需结合前后量能判断"
                        }.get(vol_mode, "无需求信号")
                        nd.append({
                            "date": df.index[i], 
                            "vol_ratio": round(vol_r, 2),
                            "vol_mode": vol_mode,
                            "is_comparative_low": is_comparative_low,
                            "close_position": round(cp * 100, 1),
                            "tr_position": round(tr_pos * 100, 1),
                            "swing_direction": "UP" if swing_dir == 1 else "DOWN",
                            "is_top_test": is_top_test,
                            "description": desc_nd
                        })
            
            # 孟洪涛 Stopping Volume 优化：
            # 价格处于 60 日交易区间的相对中低位（tr_pos < 0.5），或者收盘价低于短期 20 日均线
            if tr_pos < 0.5 or df['Close'].iloc[i] < ma20.iloc[i]:
                # 联动配置中的量比、窄幅实体以及下影线阈值，避免放宽位置限制后引入噪点
                if vol_r > t.MENG_STOPPING_VOL_RATIO and body_pct < t.MENG_STOPPING_BODY_RATIO:
                    ls = min(df['Open'].iloc[i], df['Close'].iloc[i]) - df['Low'].iloc[i]
                    if ls > pr * t.MENG_STOPPING_SHADOW_RATIO:
                        sv.append({"date": df.index[i], "vol_ratio": round(vol_r, 2), "price": df['Close'].iloc[i]})
        
        return {
            "no_supply": {"detected": len(ns) > 0, "signals": ns[-5:], "latest": ns[-1] if ns else None},
            "no_demand": {"detected": len(nd) > 0, "signals": nd[-5:], "latest": nd[-1] if nd else None},
            "stopping_vol": {"detected": len(sv) > 0, "signals": sv[-3:], "latest": sv[-1] if sv else None}
        }

    def detect_boring_zone(self, window: int = 14) -> Dict:
        """检测枯燥区"""
        if self.data is None or len(self.data) < window + 20: return {"detected": False, "reason": "insufficient_data"}
        df = self.data.tail(window + 20).copy()
        atr_s = self._calculate_atr_series(df, 14)
        df['ATR_Pct'] = atr_s / df['Close'] * 100
        avg_atr_p = df['ATR_Pct'].iloc[:-window].mean()
        recent = df.tail(window)
        rv_avg = recent['Volume'].mean()
        ov_ma20 = df['Volume_MA20'].iloc[-1] if 'Volume_MA20' in df.columns else df['Volume'].rolling(20).mean().iloc[-1]
        vc, ac = rv_avg / ov_ma20 if ov_ma20 > 0 else 1.0, recent['ATR_Pct'].mean() / avg_atr_p if avg_atr_p > 0 else 1.0
        is_boring = vc < 0.75 and ac < 0.8
        score = self.calculate_boring_alert_score(vc, ac, window)
        
        # 新增：地量确认与爆发前夜
        is_eve_of_breakout = False
        if score >= 80:
            last_3_vol = recent['Volume'].tail(3).values
            ground_vol_limit = ov_ma20 * 0.4
            # 地量判断：最近 3 天均低于均量的 40%，且呈萎缩趋势
            is_ground_vol = all(v < ground_vol_limit for v in last_3_vol)
            is_shrinking = last_3_vol[-1] < last_3_vol[-2] < last_3_vol[-3]
            
            if is_ground_vol and is_shrinking:
                is_eve_of_breakout = True
                score += 20 # 额外奖励分
        
        return {
            "detected": is_boring, 
            "score": min(100, score), 
            "vol_contraction": round(vc, 2), 
            "atr_contraction": round(ac, 2), 
            "duration": window, 
            "high_alert": score >= 85,
            "is_eve_of_breakout": is_eve_of_breakout,
            "signal_status": "THE_EVE_OF_BREAKOUT" if is_eve_of_breakout else "BORING_ZONE"
        }

    def calculate_boring_alert_score(self, vc, ac, dur) -> int:
        score = 0
        if vc < 0.5: score += 40
        elif vc < 0.7: score += 30
        elif vc < 0.85: score += 15
        if ac < 0.6: score += 40
        elif ac < 0.75: score += 30
        elif ac < 0.9: score += 15
        if dur >= 20: score += 20
        elif dur >= 10: score += 15
        elif dur >= 5: score += 10
        return score

    def detect_volume_trend(self, window: int = 10) -> Dict:
        """
        孟洪涛原则：检测成交量趋势

        孟洪涛理论强调：成交量趋势比单日信号更重要
        - 放量趋势：成交量持续放大，表示资金积极参与
        - 缩量趋势：成交量持续萎缩，表示市场观望情绪
        - 平稳：成交量在正常范围内波动

        Returns:
            {
                'trend': 'expanding' | 'contracting' | 'stable',
                'strength': 0-100,
                'description': str,
                'short_ma': float,
                'long_ma': float,
                'ratio': float
            }
        """
        if self.data is None or len(self.data) < window * 2:
            return {'trend': 'unknown', 'reason': 'insufficient_data'}

        df = self.data.tail(window * 2).copy()
        volumes = df['Volume'].values

        # 计算短期和长期成交量均线
        short_window = max(3, window // 2)
        vol_ma_short = df['Volume'].rolling(short_window).mean().iloc[-1]
        vol_ma_long = df['Volume'].rolling(window).mean().iloc[-1]

        if vol_ma_long <= 0:
            return {'trend': 'unknown', 'reason': 'invalid_volume_data'}

        # 计算量比
        vol_ratio = vol_ma_short / vol_ma_long

        # 计算趋势强度（基于最近几天的成交量变化）
        recent_volumes = volumes[-min(5, len(volumes)):]
        if len(recent_volumes) >= 3:
            # 线性回归斜率
            x = np.arange(len(recent_volumes))
            y = recent_volumes
            slope = np.polyfit(x, y, 1)[0] if len(y) > 1 else 0
            # 归一化强度
            avg_vol = np.mean(y)
            strength = abs(slope) / avg_vol * 100 if avg_vol > 0 else 0
            strength = min(strength, 100)
        else:
            strength = 0

        # 判断趋势
        if vol_ratio > 1.2:
            trend = 'expanding'
            description = f"放量趋势：短期均量{vol_ma_short:.0f} > 长期均量{vol_ma_long:.0f}（量比{vol_ratio:.2f}），资金积极参与"
        elif vol_ratio < 0.8:
            trend = 'contracting'
            description = f"缩量趋势：短期均量{vol_ma_short:.0f} < 长期均量{vol_ma_long:.0f}（量比{vol_ratio:.2f}），市场观望情绪"
        else:
            trend = 'stable'
            description = f"成交量平稳：短期均量{vol_ma_short:.0f} ≈ 长期均量{vol_ma_long:.0f}（量比{vol_ratio:.2f}），市场处于平衡状态"

        return {
            'trend': trend,
            'strength': round(strength, 1),
            'description': description,
            'short_ma': round(float(vol_ma_short), 0),
            'long_ma': round(float(vol_ma_long), 0),
            'ratio': round(vol_ratio, 2),
            'slope': round(float(slope), 2) if 'slope' in locals() else 0
        }

    def detect_vsa_with_trend_context(self) -> Dict:
        """
        结合成交量趋势的VSA信号检测（孟洪涛理论升级版）

        孟洪涛强调：成交量趋势是判断信号质量的关键
        - 在放量趋势中，No Supply/No Demand 信号更可靠
        - 在缩量趋势中，Stopping Volume 信号更可靠
        """
        # 获取VSA信号
        vsa_signals = self.detect_vsa_signals()

        # 获取成交量趋势
        vol_trend = self.detect_volume_trend()

        # 根据成交量趋势调整信号质量
        enhanced_signals = {
            'no_supply': vsa_signals['no_supply'].copy(),
            'no_demand': vsa_signals['no_demand'].copy(),
            'stopping_vol': vsa_signals['stopping_vol'].copy(),
            'volume_trend': vol_trend
        }

        # 根据成交量趋势增强信号解释
        trend = vol_trend.get('trend', 'stable')

        if vsa_signals['no_supply']['detected']:
            if trend == 'contracting':
                enhanced_signals['no_supply']['quality'] = 'high'
                enhanced_signals['no_supply']['note'] = '缩量趋势中的No Supply，供应枯竭确认'
            elif trend == 'expanding':
                enhanced_signals['no_supply']['quality'] = 'medium'
                enhanced_signals['no_supply']['note'] = '放量趋势中的No Supply，需谨慎确认'
            else:
                enhanced_signals['no_supply']['quality'] = 'neutral'

        if vsa_signals['no_demand']['detected']:
            if trend == 'contracting':
                enhanced_signals['no_demand']['quality'] = 'high'
                enhanced_signals['no_demand']['note'] = '缩量趋势中的No Demand，需求枯竭确认'
            elif trend == 'expanding':
                enhanced_signals['no_demand']['quality'] = 'medium'
                enhanced_signals['no_demand']['note'] = '放量趋势中的No Demand，需谨慎确认'
            else:
                enhanced_signals['no_demand']['quality'] = 'neutral'

        if vsa_signals['stopping_vol']['detected']:
            if trend == 'expanding':
                enhanced_signals['stopping_vol']['quality'] = 'high'
                enhanced_signals['stopping_vol']['note'] = '放量趋势中的Stopping Volume，主力吸筹确认'
            elif trend == 'contracting':
                enhanced_signals['stopping_vol']['quality'] = 'medium'
                enhanced_signals['stopping_vol']['note'] = '缩量趋势中的Stopping Volume，可能存在'
            else:
                enhanced_signals['stopping_vol']['quality'] = 'neutral'

        return enhanced_signals
