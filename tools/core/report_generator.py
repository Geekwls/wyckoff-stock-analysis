import pandas as pd
import numpy as np
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from ..config.settings import WyckoffConfig, WyckoffThresholds
from ..exceptions import DataFetchError
from .enums import MarketEnvironment, WyckoffPhase, MarketSide
from .utils import PhaseAdapter
from ..schemas import (
    ReportModel, BasicDataModel, MultiTimeframeModel, EventsModel,
    TradingRangeModel, ClimaxModel, SpringModel, UpthrustModel,
    SosModel, SowModel, LpsModel, LpsyModel, WyckoffEventModel,
    SignalQualityModel, TradingPlanModel, StopLossModel, TargetsModel,
    PositionSizingModel, RiskAdviceModel, RiskAdviceItem,
    MarketContextModel, GlobalSentimentModel, WyckoffLawsModel,
    SupplyDemandLawModel, EffortVsResultModel, CauseEffectModel,
    RelativeStrengthModel, SequenceScoreModel, DivergenceModel,
    CauseEffectAnalysisModel
)
from .backtest_engine import BacktestEngine
from .sentiment_analyzer import SentimentAnalyzer
from .trading_plan_generator import TradingPlanGenerator
import logging
logger = logging.getLogger(__name__)

class WyckoffReportGenerator:
    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.data = analyzer.data
        self.config = analyzer.config
        self.symbol = analyzer.symbol
        self.pattern_detector = getattr(analyzer, 'pattern_detector', None)
        self.law_analyzer = getattr(analyzer, 'law_analyzer', None)
        self.thresholds = WyckoffThresholds()

    def generate_report(self) -> str:
        """生成分析报告"""
        if self.data is None:
            data = self.analyzer.fetch_data()
            if data is None or (isinstance(data, pd.DataFrame) and data.empty):
                return f"无法获取数据: {self.symbol}"
            self.data = self.analyzer.data
            self.pattern_detector = self.analyzer.pattern_detector
            self.law_analyzer = self.analyzer.law_analyzer

        # ── 提前计算阶段信息，供报告头部和交易建议共用 ──────────
        phase_result = self.pattern_detector.identify_phase()
        phase_str    = phase_result.get('phase', 'Unknown')
        phase_conf   = phase_result.get('confidence', 0.0)
        seq_score    = phase_result.get('sequence_score', {})
        seq_rating   = seq_score.get('rating', '')
        ma_conf      = phase_result.get('ma_confidence', 0)
        vol_conf     = phase_result.get('vol_confidence', 0)

        # 阶段置信度颜色标记
        if phase_conf >= 0.75:
            conf_icon = '🟢'
        elif phase_conf >= 0.50:
            conf_icon = '🟡'
        else:
            conf_icon = '🔴'

        report = f"""
{'='*60}
威科夫形态 analysis 报告
{'='*60}

股票代码: {self.symbol}
分析日期: {datetime.now().strftime('%Y-%m-%d')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【当前阶段】
{conf_icon} {phase_str}
   置信度: {phase_conf*100:.0f}%  (均线确认: {ma_conf*100:.0f}% | 量能确认: {vol_conf*100:.0f}%)
   信号评级: {seq_rating}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【基础数据】
当前价格: {self.data['Close'].iloc[-1]:.2f}
52周最高: {self.data['High'].tail(252).max():.2f}
52周最低: {self.data['Low'].tail(252).min():.2f}
成交量: {self.data['Volume'].iloc[-1]:,.0f}
量比: {self.data['Volume'].iloc[-1] / max(self.data['Volume_MA20'].iloc[-1], 1):.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【形态检测】
"""

        # 检测各种形态
        trading_range = self.pattern_detector.detect_trading_range()
        spring = self.pattern_detector.detect_spring()
        upthrust = self.pattern_detector.detect_upthrust()
        sos = self.pattern_detector.detect_sos()
        sow = self.pattern_detector.detect_sow()
        lps = self.pattern_detector.detect_lps()
        lpsy = self.pattern_detector.detect_lpsy()

        if trading_range.get('is_consolidation'):
            report += f"""
✅ 检测到交易区间:
   区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
   幅度: {trading_range['range_pct']*100:.1f}%
   当前位置: {trading_range['position']*100:.0f}% (0%=底部, 100%=顶部)
   成交量趋势: {trading_range['volume_trend']}
"""

        if spring.get('detected'):
            latest = spring['latest_spring']
            report += f"""
✅ 检测到Spring:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   跌破价: {latest['breakdown_price']:.2f}
   支撑位: {latest['support_level']:.2f}
   收回价: {latest['recovery_price']:.2f}
   收回天数: {latest['recovery_days']}天
   ✓ 真Spring（3天内收回且放量）
"""

        if upthrust.get('detected'):
            latest = upthrust['latest_upthrust']
            report += f"""
✅ 检测到Upthrust:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   突破价: {latest['breakout_price']:.2f}
   阻力位: {latest['resistance_level']:.2f}
   回落价: {latest['rejection_price']:.2f}
   回落天数: {latest['rejection_days']}天
   收盘距高点: {latest['close_from_high']*100:.1f}%
   ✓ 真Upthrust（3天内回落且放量）
"""

        if sos.get('detected'):
            latest = sos['latest']
            report += f"""
✅ 检测到SOS（Sign of Strength）:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   价格: {latest['price']:.2f}
   成交量倍数: {latest['volume_ratio']:.1f}x
   涨幅: {latest['price_change']*100:.1f}%
   突破位: {latest['breakthrough_level']:.2f}
   ✓ 强势信号（放量突破）
"""

        if sow.get('detected'):
            latest = sow['latest']
            report += f"""
✅ 检测到SOW（Sign of Weakness）:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   价格: {latest['price']:.2f}
   成交量倍数: {latest['volume_ratio']:.1f}x
   跌幅: {latest['price_change']*100:.1f}%
   跌破位: {latest['breakdown_level']:.2f}
   ✓ 弱势信号（放量跌破）
"""

        if lps.get('detected'):
            report += f"""
✅ 检测到LPS（Last Point of Support）:
   日期: {lps['date'].strftime('%Y-%m-%d')}
   价格: {lps['price']:.2f}
   回调幅度: {lps['pullback_pct']*100:.1f}%
   成交量缩小: 是
   ⭐ 建议做多入场点
"""

        if lpsy.get('detected'):
            report += f"""
✅ 检测到LPSY（Last Point of Supply）:
   日期: {lpsy['date'].strftime('%Y-%m-%d')}
   价格: {lpsy['price']:.2f}
   反弹幅度: {lpsy['rally_pct']*100:.1f}%
   成交量缩小: 是
   ⭐ 建议做空入场点
"""

        # ── 新威科夫操盘法信号 (孟洪涛) ──────────────────────────
        joc = self.pattern_detector.detect_joc()
        fti = self.pattern_detector.detect_fti()
        vsa = self.pattern_detector.detect_vsa_signals()

        if joc.get('detected') or fti.get('detected') or any(
            vsa.get(k, {}).get('detected') for k in ('no_supply', 'no_demand', 'stopping_vol')
        ):
            report += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【新威科夫信号（孟洪涛）】
"""
        if joc.get('detected'):
            joc_date = joc['date'].strftime('%Y-%m-%d') if hasattr(joc['date'], 'strftime') else str(joc['date'])
            test_info = ""
            if joc.get('test_detected') and joc.get('test_date') is not None:
                td = joc['test_date'].strftime('%Y-%m-%d') if hasattr(joc['test_date'], 'strftime') else str(joc['test_date'])
                test_info = f"\n   回测确认: {td}（缩量{joc.get('test_vol_ratio', 0):.2f}x） ✓"
            else:
                test_info = "\n   回测确认: 等待回测（Test of JOC）中"
            report += f"""
🚀 检测到JOC（跃过小溪 / Jump Across the Creek）:
   日期: {joc_date}
   小溪阻力位: {joc['creek_level']:.2f}
   突破收盘: {joc['close_price']:.2f} (+{joc['breakout_pct']:.1f}%)
   成交量: {joc['volume_ratio']:.1f}x 均量{test_info}
   置信度: {joc['confidence']*100:.0f}%
   ⭐ 趋势跟踪买入信号（等待缩量回测 JOC 位入场）
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
   ⚠️  做空警示信号（等待缩量回测冰层位入场）
"""

        # VSA 辅助信号
        vsa_lines = []
        ns = vsa.get('no_supply', {})
        nd = vsa.get('no_demand', {})
        sv = vsa.get('stopping_vol', {})
        if ns.get('detected'):
            ns_date = ns['date'].strftime('%Y-%m-%d') if hasattr(ns.get('date'), 'strftime') else str(ns.get('date', ''))
            vsa_lines.append(f"   🟢 No Supply（无供应）: {ns_date} 缩量{ns.get('vol_ratio', 0):.2f}x 回调 → 买入辅助确认")
        if nd.get('detected'):
            nd_date = nd['date'].strftime('%Y-%m-%d') if hasattr(nd.get('date'), 'strftime') else str(nd.get('date', ''))
            vsa_lines.append(f"   🔴 No Demand（无需求）: {nd_date} 缩量{nd.get('vol_ratio', 0):.2f}x 反弹 → 做空辅助确认")
        if sv.get('detected'):
            sv_date = sv['date'].strftime('%Y-%m-%d') if hasattr(sv.get('date'), 'strftime') else str(sv.get('date', ''))
            vsa_lines.append(f"   🟡 Stopping Volume（停止行为）: {sv_date} 放量{sv.get('vol_ratio', 0):.2f}x 窄幅 → 主力吸收供应")
        if vsa_lines:
            report += "\n📊 VSA辅助信号（量价微观分析）:\n" + "\n".join(vsa_lines) + "\n"

        # 因果测算
        cause_effect = self.analyzer.calculate_cause_effect()
        targets_ok = cause_effect and 'targets' in cause_effect
        if targets_ok:
            report += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【因果测算】
交易区间: {trading_range.get('low', 0):.2f} - {trading_range.get('high', 0):.2f}
因果幅度: {cause_effect['cause_size']:.2f}
目标1 (0.618倍): {cause_effect['targets']['target_1']:.2f}
目标2 (1.0倍): {cause_effect['targets']['target_2']:.2f}
目标3 (1.618倍): {cause_effect['targets']['target_3']:.2f}
"""

        # ── 核心结论评估（加权信号 + 冲突检测 + 阈值门控） ──────────────────
        current_price = self.data['Close'].iloc[-1]
        signal_quality_data = self.calculate_signal_quality({'environment': self.analyzer._analyze_market_environment().get('environment')})
        quality_score = signal_quality_data.get('score', 0)
        max_score = signal_quality_data.get('max_score', 10)
        
        # 阈值门控：如果评分过低或置信度太低，强制观望
        if quality_score < 4 or phase_conf < 0.5:
            report += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【核心结论】
⏸️ 观望等待（信号质量不足）:
   当前评分: {quality_score}/{max_score} | 置信度: {phase_conf*100:.0f}%
   结论: 信号强度或可靠性低于执行阈值，建议继续观察。
"""
        else:
            # 收集信号并检测冲突
            bullish_signals = []
            bearish_signals = []
            if joc.get('detected'): bullish_signals.append("JOC")
            if lps.get('detected'): bullish_signals.append("LPS")
            if spring.get('detected'): bullish_signals.append("Spring")
            if fti.get('detected'): bearish_signals.append("FTI")
            if lpsy.get('detected'): bearish_signals.append("LPSY")
            if upthrust.get('detected'): bearish_signals.append("Upthrust")
            
            report += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n【核心结论】\n"
            
            # 冲突检测
            if bullish_signals and bearish_signals:
                report += f"""
⚠️ 信号冲突警示:
   看多信号: {', '.join(bullish_signals)}
   看空信号: {', '.join(bearish_signals)}
   结论: 市场多空分歧剧烈，建议在冲突消解前保持空仓或显著收紧止损。
"""
            # 决策树逻辑
            elif joc.get('detected') and joc.get('test_detected'):
                joc_entry = joc.get('creek_level', current_price)
                stop_price = round(joc_entry * 0.96, 2)
                target2 = cause_effect['targets']['target_2'] if targets_ok else round(current_price * 1.15, 2)
                report += f"""
🚀 趋势跟踪买入（JOC 突破确认）:
   参考入场区间: {joc_entry:.2f} ~ {round(joc_entry * 1.02, 2):.2f}
   止损: {stop_price:.2f} | 目标2: {target2:.2f}
   策略: JOC 突破位附近缩量分批买入。
"""
            elif lps.get('detected'):
                stop_price = round(lps['price'] * 0.95, 2)
                target2 = cause_effect['targets']['target_2'] if targets_ok else round(current_price * 1.15, 2)
                report += f"""
✅ 做多机会（LPS 最后支撑）:
   入场价格: {lps['price']:.2f} | 止损: {stop_price:.2f} | 目标: {target2:.2f}
"""
            elif fti.get('detected') and fti.get('test_detected'):
                fti_entry = fti.get('ice_level', current_price)
                stop_price = round(fti_entry * 1.04, 2)
                target2 = cause_effect['targets']['target_2'] if targets_ok else round(current_price * 0.85, 2)
                report += f"""
🔻 做空/减仓警示（FTI 跌破确认）:
   参考入场: {fti_entry:.2f} | 止损: {stop_price:.2f} | 目标: {target2:.2f}
   提示: {('建议减仓/止损' if self.analyzer._is_a_stock(self.symbol) else '可尝试做空')}
"""
            elif lpsy.get('detected'):
                stop_price = round(lpsy['price'] * 1.05, 2)
                target2 = cause_effect['targets']['target_2'] if targets_ok else round(current_price * 0.85, 2)
                report += f"""
✅ 卖出/减仓机会（LPSY 最后供应）:
   价格: {lpsy['price']:.2f} | 止损: {stop_price:.2f} | 目标: {target2:.2f}
"""
            elif trading_range.get('is_consolidation'):
                report += "⏳ 观望等待: 横盘整理阶段，等待信号。\n"
            else:
                report += "⏸️ 无明显信号: 建议继续观察。\n"

        report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【风险提示】
⚠️ 本报告仅供参考，不构成投资建议
⚠️ 股市有风险，投资需谨慎
⚠️ 请根据自身风险承受能力做出决策
⚠️ 建议结合其他分析方法和市场环境

{'='*60}
"""

        return report

    def _round_floats(self, obj):
        """递归遍历字典/列表，将浮点数截断至3位小数"""
        if isinstance(obj, float):
            return round(obj, 3)
        elif isinstance(obj, dict):
            return {k: self._round_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._round_floats(x) for x in obj]
        return obj

    def calculate_signal_quality(self, market_phase) -> dict:
        """计算信号质量评分 - 显式配置化"""
        cfg = self.thresholds.SCORING
        score = 0
        reasons = []
        phase_str = 'Unknown'

        if self.data is not None:
            vol_ratio = self.data['Volume'].iloc[-1] / max(self.data['Volume_MA20'].iloc[-1], 1)
            phase_res = self.pattern_detector.identify_phase()
            phase_str = phase_res.get('phase', 'Unknown')
            
            # 1. 技术确认度 (成交量配合)
            is_bullish_side = PhaseAdapter.get_market_side(phase_str) == MarketSide.BULLISH
            
            if is_bullish_side:
                if vol_ratio > 1.5:
                    score += cfg.vol_strong_weight
                    reasons.append(f"成交量强力确认 (+{cfg.vol_strong_weight}分)")
                elif vol_ratio > 1.0:
                    score += cfg.vol_moderate_weight
                    reasons.append(f"成交量温和配合 (+{cfg.vol_moderate_weight}分)")
            else:
                if vol_ratio > 1.5:
                    score += cfg.vol_strong_weight
                    reasons.append(f"成交量强力确认 (放量下跌) (+{cfg.vol_strong_weight}分)")
        
            # 2. 趋势一致性
            current_price = self.data['Close'].iloc[-1]
            ma50 = self.data['MA50'].iloc[-1]
            ma200 = self.data['MA200'].iloc[-1]
            
            if (current_price > ma50 > ma200) or (current_price < ma50 < ma200):
                score += cfg.trend_alignment_weight
                reasons.append(f"多时间框架一致 (+{cfg.trend_alignment_weight}分)")

        # 3. 市场环境配合
        market_env = market_phase.get('environment', MarketEnvironment.UNKNOWN)
        is_market_bullish = market_env in [MarketEnvironment.STRONG_BULL, MarketEnvironment.BULL]
        is_market_bearish = market_env in [MarketEnvironment.STRONG_BEAR, MarketEnvironment.BEAR]
        
        current_side = PhaseAdapter.get_market_side(phase_str)
        
        if is_market_bullish:
            if current_side == MarketSide.BULLISH:
                score += cfg.market_bullish_weight
                reasons.append(f"顺应大盘多头 (+{cfg.market_bullish_weight}分)")
        elif is_market_bearish:
            if current_side == MarketSide.BEARISH:
                score += cfg.market_bearish_weight
                reasons.append(f"顺应大盘空头 (+{cfg.market_bearish_weight}分)")
        elif market_env == MarketEnvironment.RANGE_BOUND:
            score += cfg.market_range_bonus
            reasons.append(f"大盘震荡中性 (+{cfg.market_range_bonus}分)")

        return {
            "score": score,
            "max_score": cfg.max_score,
            "confidence": "高" if score >= (cfg.max_score * 0.7) else "中" if score >= (cfg.max_score * 0.4) else "低",
            "reasons": reasons
        }

    def get_relevant_terms(self, phase: str, events: dict) -> dict:
        """获取相关术语的大白话解释"""
        all_terms = {
            "SOS (强势信号)": {
                "simple": "强势信号 - 价格放量突破阻力位",
                "example": "像蓄势后的跳跃，成交量放大确认",
                "action": "考虑买入或持有"
            },
            "SOW (弱势信号)": {
                "simple": "弱势信号 - 价格放量跌破支撑位",
                "example": "像突然脚软跌入坑中，供给开始主导",
                "action": "考虑卖出或观望"
            },
            "Spring (震仓)": {
                "simple": "震仓 - 短暂跌破支撑后快速收回",
                "example": "像弹簧被压下去后弹起，洗出散户",
                "action": "可能是极佳的买入机会"
            },
            "Upthrust (上冲回落)": {
                "simple": "诱多 - 短暂突破阻力后快速跌回",
                "example": "假装大涨吸引散户接盘，随后迅速撤退",
                "action": "可能是做空或逃顶机会"
            },
            "Accumulation (积累期)": {
                "simple": "建仓期 - 主力在低位悄悄买入筹码",
                "example": "像批发商在淡季默默囤货",
                "action": "耐心等待突破信号"
            },
            "Distribution (派发期)": {
                "simple": "出货期 - 主力在高位分批卖出筹码",
                "example": "像批发商在旺季大肆推销",
                "action": "注意风险，逢高减仓"
            },
            "LPS (最后支撑点)": {
                "simple": "最后支撑点 - 震仓后的缩量回调",
                "example": "像弹簧压到底部的最低点，反弹概率最高",
                "action": "强烈建议买入"
            },
            "LPSY (最后供应点)": {
                "simple": "最后供应点 - 跌破支撑后的无力反抽",
                "example": "像反弹无力撞上天花板",
                "action": "强烈建议卖出"
            }
        }
        
        relevant = {}
        if "Accumulation" in phase:
            relevant["Accumulation (积累期)"] = all_terms["Accumulation (积累期)"]
        elif "Distribution" in phase:
            relevant["Distribution (派发期)"] = all_terms["Distribution (派发期)"]
            
        if events.get('sos', {}).get('detected'):
            relevant["SOS (强势信号)"] = all_terms["SOS (强势信号)"]
        if events.get('sow', {}).get('detected'):
            relevant["SOW (弱势信号)"] = all_terms["SOW (弱势信号)"]
        if events.get('spring', {}).get('detected'):
            relevant["Spring (震仓)"] = all_terms["Spring (震仓)"]
        if events.get('upthrust', {}).get('detected'):
            relevant["Upthrust (上冲回落)"] = all_terms["Upthrust (上冲回落)"]
        if events.get('lps', {}).get('detected'):
            relevant["LPS (最后支撑点)"] = all_terms["LPS (最后支撑点)"]
        if events.get('lpsy', {}).get('detected'):
            relevant["LPSY (最后供应点)"] = all_terms["LPSY (最后供应点)"]
            
        return relevant

    def generate_risk_advice(self, signal_quality: dict, trading_plan: dict) -> dict:
        """生成具体的风险分层操作建议 - 考虑波动率与流动性"""
        score = signal_quality.get("score", 0)
        direction = trading_plan.get("direction", "观望")
        stop_con = trading_plan.get("stop_loss", {}).get("conservative", "未知")
        stop_agg = trading_plan.get("stop_loss", {}).get("aggressive", "未知")
        
        # 波动率与流动性惩罚因子
        pos_cfg = self.thresholds.POSITION_SIZING
        current_price = self.data['Close'].iloc[-1]
        atr = self.data['ATR'].iloc[-1] if 'ATR' in self.data.columns else current_price * 0.02
        vol_ma20 = self.data['Volume_MA20'].iloc[-1] if 'Volume_MA20' in self.data.columns else 1e9
        
        volatility_ratio = atr / current_price
        safety_multiplier = 1.0
        
        # 1. 波动率惩罚：如果 ATR 占比超过阈值，减少仓位
        if volatility_ratio > pos_cfg.volatility_cap_threshold:
            safety_multiplier *= (pos_cfg.volatility_cap_threshold / volatility_ratio)
            
        # 2. 流动性惩罚：如果成交量过低，减少仓位
        if vol_ma20 < pos_cfg.liquidity_min_volume_ma20:
            safety_multiplier *= max(vol_ma20 / pos_cfg.liquidity_min_volume_ma20, 0.5)

        def fmt_pos(base_pos: float) -> str:
            final_pos = base_pos * safety_multiplier
            return f"{final_pos*100:.1f}%"

        # 止损执行说明
        sl_rule = " (若开盘跳空跌破止损线，建议在开盘5分钟内寻找反抽机会果断离场，不计较滑点)"

        if score <= 4:
            return {
                "conservative": {
                    "action": "绝对观望",
                    "reason": f"信号质量仅 {score}/{signal_quality.get('max_score', 10)} 分，风险极高",
                    "entry_condition": "等待明确的量价反转信号"
                },
                "moderate": {
                    "action": "观望为主",
                    "position": "建议空仓",
                    "stop_loss": "暂不适用"
                },
                "aggressive": {
                    "action": f"极轻仓试错 ({direction})",
                    "position": f"不超过 {fmt_pos(0.03)} 仓位",
                    "stop_loss": f"{stop_con}元{sl_rule}"
                }
            }
        elif score <= 7:
            return {
                "conservative": {
                    "action": "观望或极轻仓",
                    "reason": f"信号质量 {score} 分，未达到绝对安全边际",
                    "entry_condition": "等待价格回调确认支撑"
                },
                "moderate": {
                    "action": f"分批建仓 ({direction})",
                    "position": f"{fmt_pos(0.05)} 仓位上限",
                    "stop_loss": f"{stop_con}元{sl_rule}"
                },
                "aggressive": {
                    "action": f"按计划参与 ({direction})",
                    "position": f"{fmt_pos(pos_cfg.max_moderate_position)} 仓位上限",
                    "stop_loss": f"{stop_agg}元{sl_rule}"
                }
            }
        else:
            return {
                "conservative": {
                    "action": f"稳步参与 ({direction})",
                    "reason": "高信号质量共振",
                    "entry_condition": "当前区间直接介入"
                },
                "moderate": {
                    "action": f"积极布局 ({direction})",
                    "position": f"{fmt_pos(pos_cfg.max_moderate_position)} 仓位上限",
                    "stop_loss": f"{stop_con}元{sl_rule}"
                },
                "aggressive": {
                    "action": f"重仓出击 ({direction})",
                    "position": f"{fmt_pos(pos_cfg.max_aggressive_position)} 仓位上限",
                    "stop_loss": f"{stop_agg}元{sl_rule}"
                }
            }

    def generate_interactive_qa(self, signal_quality: dict, trading_plan: dict) -> list:
        """根据分析结果预生成交互问答"""
        direction = trading_plan.get("direction", "观望")
        score = signal_quality.get("score", 0)
        stop = trading_plan.get("stop_loss", {}).get("conservative", "未知")
        period = trading_plan.get("holding_period", "未知")
        
        return [
            f"现在{direction} {self.symbol} 合适吗？(当前信号质量为 {score}/10)",
            f"如果参与 {self.symbol}，应该设置多少止损？(建议保守防守线在 {stop}元)",
            f"这笔交易预期需要持有多长时间？(系统预估 {period})"
        ]

    def generate_json(self) -> str:
        """生成JSON格式的分析报告（供AI Agent读取）"""
        if self.data is None or (isinstance(self.data, pd.DataFrame) and self.data.empty):
            raise DataFetchError(self.symbol, "无法获取数据")
            
        self.data = self.analyzer.data
        self.pattern_detector = self.analyzer.pattern_detector
        self.law_analyzer = self.analyzer.law_analyzer
            
        # 1. 基础事件分析
        climax_res = self.pattern_detector.detect_climax()
        ar_res = self.pattern_detector.detect_automatic_reaction(climax_res)
        st_res = self.pattern_detector.detect_secondary_test(climax_res, ar_res)
        
        # 构建事件模型
        events = EventsModel(
            trading_range=TradingRangeModel(**self.pattern_detector.detect_trading_range()),
            climax=ClimaxModel(**climax_res),
            automatic_reaction=WyckoffEventModel(**ar_res) if ar_res.get('detected') else WyckoffEventModel(detected=False),
            secondary_test=WyckoffEventModel(**st_res) if st_res.get('detected') else WyckoffEventModel(detected=False),
            spring=SpringModel(**self.pattern_detector.detect_spring()),
            upthrust=UpthrustModel(**self.pattern_detector.detect_upthrust()),
            sos=SosModel(**self.pattern_detector.detect_sos()),
            sow=SosModel(**self.pattern_detector.detect_sow()) if 'sow' in dir(self.pattern_detector) else WyckoffEventModel(detected=False), # Fallback
            lps=LpsModel(**self.pattern_detector.detect_lps()),
            lpsy=LpsyModel(**self.pattern_detector.detect_lpsy())
        )
        
        # 获取完整带多时间框架和RS的阶段
        phase_dict = self.analyzer.identify_phase_with_rs()
        phase_str = phase_dict.get('phase', 'Unknown')
        
        daily_phase_dict = phase_dict.get('daily_analysis', {})
        seq_score = SequenceScoreModel(**daily_phase_dict.get('sequence_score', {'completeness': 0, 'score': 0, 'rating': 'N/A'}))
        div_res = DivergenceModel(**daily_phase_dict.get('divergence', {'detected': False}))

        # 构建基础数据
        basic_data = BasicDataModel(
            current_price=round(self.data['Close'].iloc[-1], 2),
            volume=int(self.data['Volume'].iloc[-1]),
            volume_ratio=round(self.data['Volume'].iloc[-1] / max(self.data['Volume_MA20'].iloc[-1], 1), 2)
        )
        
        # 构建多时间框架
        multi_timeframe = MultiTimeframeModel(
            weekly_trend=phase_dict.get('weekly_trend', 'unknown'),
            monthly_trend=phase_dict.get('monthly_trend', 'unknown'),
            agreement=phase_dict.get('agreement', 'unknown')
        )
        
        # 构建相对强度
        rs_data = phase_dict.get('relative_strength', {})
        relative_strength = RelativeStrengthModel(**rs_data) if rs_data else RelativeStrengthModel()
        
        # 构建因果分析
        cause_effect_data = self.analyzer.calculate_cause_effect()
        cause_effect = CauseEffectAnalysisModel(**cause_effect_data)
        
        # 获取大盘基准
        index_symbol = self.analyzer._get_baseline_index_symbol()
        idx_analyzer = self.analyzer._get_cached_index_analyzer()

        market_context = MarketContextModel(index_symbol=index_symbol)
        if idx_analyzer is not None:
            market_phase_dict = idx_analyzer.identify_phase_with_rs()
            market_phase_str = market_phase_dict.get('phase', 'Unknown')
            env_dict = self.analyzer._analyze_market_environment()
            market_context = MarketContextModel(
                index_symbol=index_symbol,
                phase=market_phase_str,
                environment=env_dict.get("environment", MarketEnvironment.UNKNOWN),
                ma_spread_pct=env_dict.get("ma_spread_pct", 0)
            )
        
        # 使用SentimentAnalyzer获取市场情绪
        sentiment_analyzer = SentimentAnalyzer(self.symbol)
        global_sentiment_data = sentiment_analyzer.analyze(
            index_data=idx_analyzer.data if idx_analyzer else None,
            index_symbol=index_symbol
        )
        global_sentiment = GlobalSentimentModel(**global_sentiment_data)
        
        # 增加信号质量评分和交易计划
        signal_quality_data = self.calculate_signal_quality(market_context.model_dump())
        signal_quality = SignalQualityModel(**signal_quality_data)
        
        # 使用TradingPlanGenerator生成交易计划
        trading_plan_generator = TradingPlanGenerator(self.data, self.pattern_detector)
        trading_plan_data = trading_plan_generator.generate(global_sentiment_data, phase_str, is_a_stock=self.analyzer._is_a_stock(self.symbol))
        trading_plan = TradingPlanModel(**trading_plan_data)
        
        # 增加Wyckoff三大定律完整分析
        wyckoff_laws = WyckoffLawsModel(
            supply_demand_law=SupplyDemandLawModel(**self.law_analyzer.analyze_supply_demand_law()),
            effort_vs_result_law=EffortVsResultModel(**self.law_analyzer.analyze_effort_vs_result_law()),
            cause_effect_law=CauseEffectModel(**self.law_analyzer.analyze_cause_effect_law_enhanced())
        )

        # 增加风险建议
        risk_advice_data = self.generate_risk_advice(signal_quality_data, trading_plan_data)
        risk_advice = RiskAdviceModel(
            conservative=RiskAdviceItem(**risk_advice_data.get('conservative', {})),
            moderate=RiskAdviceItem(**risk_advice_data.get('moderate', {})),
            aggressive=RiskAdviceItem(**risk_advice_data.get('aggressive', {}))
        )
        
        # 使用BacktestEngine获取历史表现
        backtest_engine = BacktestEngine(self.data, self.pattern_detector.thresholds)
        performance_tracking = backtest_engine.calculate_signal_performance(events.model_dump())
        
        # 构建完整报告
        report = ReportModel(
            symbol=self.symbol,
            date=datetime.now().strftime('%Y-%m-%d'),
            phase=phase_str,
            phase_confidence=phase_dict.get('confidence', 0.0),
            sequence_score=seq_score,
            divergence=div_res,
            multi_timeframe=multi_timeframe,
            relative_strength=relative_strength,
            basic_data=basic_data,
            events=events,
            cause_effect=cause_effect,
            market_context=market_context,
            global_sentiment=global_sentiment,
            signal_quality=signal_quality,
            trading_plan=trading_plan,
            wyckoff_laws=wyckoff_laws,
            terminology_guide=self.get_relevant_terms(phase_str, events.model_dump()),
            risk_specific_advice=risk_advice,
            interactive_qa=self.generate_interactive_qa(signal_quality_data, trading_plan_data),
            performance_tracking=performance_tracking
        )
        
        # 使用自定义序列化器处理numpy类型
        def default_serializer(obj):
            import numpy as np
            if isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            if isinstance(obj, (np.floating, np.float64)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        return report.model_dump_json(indent=2, exclude_none=True, fallback=default_serializer)
