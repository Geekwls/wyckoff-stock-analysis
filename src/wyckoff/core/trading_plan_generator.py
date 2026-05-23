"""
威科夫分析系统 - 交易计划生成器
从report_generator.py中提取，负责生成交易计划
"""
import pandas as pd
from typing import Dict, Any, Optional
import logging

from .signal_extractor import SignalExtractor, get_events_from_phase
from .utils import PhaseAdapter

logger = logging.getLogger(__name__)


class TradingPlanGenerator:
    """
    交易计划生成器
    根据技术分析结果生成交易计划
    """
    
    # 默认仓位比例
    DEFAULT_POSITION = {
        'conservative': 2.5,
        'moderate': 5.0,
        'aggressive': 10.0
    }
    
    # 情绪调整系数
    SENTIMENT_ADJUSTMENT = {
        'extreme_fear': 0.5,
        'fear': 0.8,
        'neutral': 1.0,
        'greed': 1.2
    }
    
    def __init__(self, data: pd.DataFrame, pattern_detector):
        """
        初始化交易计划生成器
        
        Args:
            data: K线数据
            pattern_detector: 形态检测器
        """
        self.data = data
        self.pattern_detector = pattern_detector
        self.is_a_stock = False
        if hasattr(pattern_detector, 'data_fetcher'): # PatternDetector doesn't have it usually, but analyzer does.
             pass
    
    def generate(self, sentiment_data: Optional[Dict[str, Any]] = None, 
                 phase_str: str = "", is_a_stock: bool = False) -> Dict[str, Any]:
        """
        生成交易计划
        
        Args:
            sentiment_data: 市场情绪数据
            phase_str: 当前阶段字符串
            is_a_stock: 是否为A股
            
        Returns:
            交易计划字典
        """
        self.is_a_stock = is_a_stock
        if self.data is None:
            return {}
        
        current_price = self.data['Close'].iloc[-1]
        atr = self.data['ATR'].iloc[-1]
        
        # 获取交易区间
        tr = self.pattern_detector.detect_trading_range()
        high = tr.get("high", current_price * 1.1)
        low = tr.get("low", current_price * 0.9)
        
        # 获取阶段与事件（主链同源）
        phase_res = None
        if not phase_str:
            phase_res = self.pattern_detector.identify_phase()
            phase_str = SignalExtractor.get_effective_phase(phase_res) if isinstance(phase_res, dict) else str(phase_res)
        elif hasattr(self.pattern_detector, 'identify_phase'):
            phase_res = self.pattern_detector.identify_phase()

        events = get_events_from_phase(phase_res) if phase_res else None
        joc_ev = SignalExtractor.get_event_dict(events, 'joc') if events else {}
        spring_ev = SignalExtractor.get_event_dict(events, 'spring') if events else {}
        fti_ev = SignalExtractor.get_event_dict(events, 'fti') if events else {}
        sow_ev = SignalExtractor.get_event_dict(events, 'sow') if events else {}
        upthrust_ev = SignalExtractor.get_event_dict(events, 'upthrust') if events else {}
        lps_ev = SignalExtractor.get_event_dict(events, 'lps') if events else {}
        lpsy_ev = SignalExtractor.get_event_dict(events, 'lpsy') if events else {}
        has_lps = lps_ev.get('detected', False)
        has_lpsy = lpsy_ev.get('detected', False)
        has_joc = joc_ev.get('detected', False)
        has_fti = fti_ev.get('detected', False)
        has_sow = sow_ev.get('detected', False)
        has_spring = spring_ev.get('detected', False)
        has_upthrust = upthrust_ev.get('detected', False)
        spring_failed = SignalExtractor._spring_lifecycle_failed(spring_ev) if has_spring else False
        upthrust_failed = SignalExtractor._upthrust_lifecycle_failed(upthrust_ev) if has_upthrust else False
        
        is_bullish = "Accumulation" in phase_str or "Markup" in phase_str
        is_distribution = "Distribution" in phase_str or "Markdown" in phase_str
        is_accumulation = "Accumulation" in phase_str

        entry_zone, stop_loss, targets = self._calculate_levels(
            current_price, atr, high, low, is_bullish
        )

        # 威科夫方向锁：积累期默认谨慎；Phase D/JOC 才可积极做多
        if is_accumulation:
            if 'Phase E' in phase_str:
                direction = "做多"
                dynamic_warning = "Markup/Phase E 推进期，可按 LPS 或趋势回撤分批参与。"
                entry_zone = f"Creek/JOC 回测区附近 (JOC: {joc_ev.get('creek_level', round(low, 2))})"
            elif has_joc and has_lps:
                direction = "做多"
                dynamic_warning = "JOC+LPS 威科夫标准入场，可按 LPS 分批建仓。"
                lps_price = lps_ev.get('price') or lps_ev.get('support_level') or round(low, 2)
                entry_zone = f"{lps_price} 附近 (JOC+LPS 回测)"
            elif has_joc or 'Phase D' in phase_str:
                direction = "观望"
                dynamic_warning = "JOC/Phase D 已现，等待 LPS 缩量回测确认（威科夫第五步）。"
                entry_zone = "等待 LPS 确认"
            elif has_spring and not spring_failed:
                direction = "观望"
                dynamic_warning = "Spring 震仓已现，等待 JOC 突破小溪或 LPS 缩量回测确认（孟氏 checklist）。"
                entry_zone = "等待 JOC/LPS 确认"
            elif spring_failed:
                direction = "观望"
                dynamic_warning = "Spring 生命周期已失效，等待新结构确认。"
                entry_zone = "结构失效，暂不入场"
            else:
                direction = "观望"
                dynamic_warning = "吸筹早期/中期，等待 Spring→JOC 完整序列。"
                entry_zone = f"观察支撑区: {round(low, 2)} 附近"
            pos_sizing, _ = self._adjust_position_with_sentiment(
                sentiment_data, phase_str, direction == "做多"
            )
            scale_in_triggers = self._calculate_scale_in_triggers(
                current_price, high, low, atr, direction == "做多"
            )
        elif is_distribution:
            is_phase_d = 'Phase D' in phase_str
            is_phase_e = 'Phase E' in phase_str or 'Markdown' in phase_str
            if has_fti and has_lpsy:
                direction = "减仓/对冲" if self.is_a_stock else "做空"
                dynamic_warning = "FTI+LPSY 威科夫标准入场，可按 LPSY 分批减仓或做空。"
                lpsy_price = lpsy_ev.get('price') or lpsy_ev.get('resistance_level') or round(high, 2)
                entry_zone = f"{lpsy_price} 附近 (FTI+LPSY 反抽)"
            elif is_phase_e:
                direction = "减仓/对冲" if self.is_a_stock else "做空"
                dynamic_warning = "派发/markdown 推进期，可按反弹阻力减仓或做空。"
                entry_zone = f"阻力位: {round(high, 2)} 附近"
            elif has_fti or (is_phase_d and has_sow):
                direction = "观望"
                dynamic_warning = "FTI/Phase D 已现，等待 LPSY 缩量回测确认（威科夫第五步）。"
                entry_zone = "等待 LPSY 确认"
            elif has_upthrust and not upthrust_failed and (has_sow or has_fti):
                direction = "减仓/对冲" if self.is_a_stock else "做空"
                dynamic_warning = "Upthrust 诱多后 SOW/FTI 结构确认，可按阻力区减仓。"
                entry_zone = f"阻力位: {round(high, 2)} 附近"
            else:
                direction = "观望"
                dynamic_warning = (
                    "派发阶段，等待 FTI 跌破冰层或 Upthrust/SOW 结构确认后再做空"
                    "（孟氏 checklist）。"
                )
                entry_zone = "等待 FTI/LPSY 确认"
            pos_sizing = {"status": "空仓/减持"} if direction != "观望" else {"status": "绝对观望"}
            scale_in_triggers = {
                "exit_1": {"condition": "跌破区间下沿 (确认派发)", "price": round(low, 2)},
                "exit_2": {"condition": "反抽阻力位无力", "price": round(high, 2)}
            } if direction != "观望" else {
                "observation": {"condition": "等待 FTI 或 SOW/Upthrust 结构确认", "price": 0.0}
            }
            if direction != "观望":
                dynamic_warning = (
                    dynamic_warning or
                    "当前处于派发阶段。威科夫第一原则：出货区只卖不买。"
                )
        else:
            direction = "做多" if is_bullish else "观望"
            pos_sizing, dynamic_warning = self._adjust_position_with_sentiment(
                sentiment_data, phase_str, is_bullish
            )
            scale_in_triggers = self._calculate_scale_in_triggers(
                current_price, high, low, atr, is_bullish
            )

        # 派发初期（Phase A/B）强制绝对观望拦截
        is_dist_early = PhaseAdapter.is_distribution_early(phase_str)

        if is_dist_early:
            direction = "观望"
            entry_zone = "绝对观望"
            pos_sizing = {"conservative": "0%", "moderate": "0%", "aggressive": "0%", "status": "绝对观望"}
            scale_in_triggers = {"observation": {"condition": "等待进入 Phase C/D 确认信号", "price": 0.0}}
            dynamic_warning = "当前处于派发初期（Phase A），主力在测试需求，供应尚未完全主控。虽然有弱势信号迹象，但下方仍有需求抵抗，此时做空极易被轧空。根据威科夫原则，应保持空仓观望，等待 Phase C 的 UTAD 确认或 Phase D 的 SOW 破位。"
            stop_loss = {
                "conservative": {
                    "value": 0.0,
                    "derivation": "无",
                    "note": "派发初期（Phase A/B）不提供做空建议，以防被轧空"
                },
                "aggressive": {
                    "value": 0.0,
                    "derivation": "无",
                    "note": "派发初期（Phase A/B）不提供做空建议，以防被轧空"
                },
                "atr_dynamic_stop": {
                    "value": 0.0,
                    "derivation": "无",
                    "note": "派发初期（Phase A/B）不提供做空建议，以防被轧空"
                }
            }
            targets = {
                "target_1": {
                    "value": 0.0,
                    "derivation": "无",
                    "note": "派发初期（Phase A/B）不提供做空目标"
                },
                "target_2": {
                    "value": 0.0,
                    "derivation": "无",
                    "note": "派发初期（Phase A/B）不提供做空目标"
                }
            }

        # ── 再派发 (Re-distribution) 熊市中继强力拦截 ──
        is_redist = 'Re-distribution' in phase_str or '再派发' in phase_str
        if is_redist:
            direction = "减仓/对冲" if self.is_a_stock else "做空"
            entry_zone = f"阻力位: {round(high, 2)} 附近 (寻找做空反弹阻力点)"
            pos_sizing = {"conservative": "0%", "moderate": "0%", "aggressive": "0%", "status": "空仓观望，建议寻找做空阻力点或对冲"}
            scale_in_triggers = {
                "short_entry": {"condition": "反弹至上沿无力", "price": round(high, 2)},
                "breakdown": {"condition": "跌破区间下沿", "price": round(low, 2)}
            }
            dynamic_warning = "当前处于熊市中继的‘再派发’阶段。威科夫原则：严禁在此处做多，任何反弹都是寻找做空/对冲或减仓的机会。等待再次破位确认。"
            stop_loss = {
                "conservative": {
                    "value": round(high * 1.01, 2),
                    "derivation": "区间上沿上方 1%",
                    "note": "站稳区间上沿则结构失效"
                },
                "aggressive": {
                    "value": round(high * 1.005, 2),
                    "derivation": "区间上沿上方 0.5%",
                    "note": "站稳区间上沿则结构失效"
                },
                "atr_dynamic_stop": {
                    "value": round(high + atr * 0.5, 2),
                    "derivation": "区间上沿 + 0.5 * ATR",
                    "note": "站稳区间上沿则结构失效"
                }
            }
            targets = {
                "target_1": {
                    "value": round(low, 2),
                    "derivation": "区间下沿",
                    "note": "区间下沿支撑位"
                },
                "target_2": {
                    "value": round(low - (high - low), 2),
                    "derivation": "一倍箱体跨度下量",
                    "note": "破位后的垂直量化目标"
                }
            }

        # 退出规则
        exit_rules = self._calculate_exit_rules(atr)

        return {
            "direction": direction,
            "entry_zone": entry_zone,
            "stop_loss": stop_loss,
            "targets": targets,
            "position_sizing": pos_sizing,
            "scale_in_triggers": scale_in_triggers,
            "exit_rules": exit_rules,
            "holding_period": "中期（2-8周）" if "Markup" in phase_str or "Markdown" in phase_str else "短期（1-3周）",
            "atr_value": round(atr, 2),
            "dynamic_warning": dynamic_warning,
            "market_constraint": "A股无法直接做空，建议以减仓或对冲替代" if self.is_a_stock and is_distribution and not is_accumulation else None
        }
    
    def _calculate_levels(self, current_price: float, atr: float, 
                          high: float, low: float, is_bullish: bool) -> tuple:
        """
        计算入场、止损、目标价位

        Wave 4 偏差二修正：引入 PnF 因果目标作为优先来源。
        在 PnF 水平计数 >= 3 列且投影目标有效时，使用：
        - target_1: PnF 1.0x 基准垂直投影（因果目标初始兑现位）
        - target_2: PnF 1.618x 斐波那契扩展（强趋势空间推演）
        仅在 PnF 无法计算或失效时，退回 ATR 兜底。
        
        Args:
            current_price: 当前价格
            atr: ATR值
            high: 区间高点
            low: 区间低点
            is_bullish: 是否看涨
            
        Returns:
            (入场区间, 止损, 目标)
        """
        entry_zone = f"{round(current_price * 0.99, 2)} - {round(current_price * 1.01, 2)}"

        # ─────────────────────────────────────────────────────────────────
        # Wave 4 偏差二修正：PnF 因果目标优先策略
        # 利用点数图水平计数计算因（筹码积累宽度）对应的果（价格目标）
        # ─────────────────────────────────────────────────────────────────
        pnf_target_1 = None
        pnf_target_2 = None
        pnf_derivation = None
        pnf_horizontal_count = 0

        try:
            from .point_and_figure import calculate_cause_effect_from_pnf
            pnf_phase = "Accumulation" if is_bullish else "Distribution"
            pnf_res = calculate_cause_effect_from_pnf(
                self.data,
                box_size_pct=1.0,
                reversal_boxes=3,
                phase=pnf_phase,
                known_tr_high=high,
                known_tr_low=low
            )
            if pnf_res:
                h_count = pnf_res.get('horizontal_count', 0)
                pnf_targets = pnf_res.get('targets', {})
                # 动态阈值：count >= 3 且目标字典非空时认为 PnF 因果目标有效
                if h_count >= 3 and pnf_targets:
                    raw_t1 = pnf_targets.get('target_1', 0)
                    raw_t2 = pnf_targets.get('target_2', 0)
                    # 合理性校验：做多目标必须大于当前价，做空目标必须小于当前价
                    if is_bullish and raw_t1 > current_price and raw_t2 > current_price:
                        pnf_target_1 = round(raw_t1, 2)
                        pnf_target_2 = round(raw_t2, 2)
                        pnf_horizontal_count = h_count
                        pnf_derivation = (
                            f"点数图因果律: 水平计数{h_count}列 x 箱体{pnf_res.get('box_size_pct', 1.0):.0f}% = "
                            f"因果目标幅{pnf_res.get('base_effect', 0):.2f} | "
                            f"1.0x基准目标={pnf_target_1}, 1.618x扩展目标={pnf_target_2}"
                        )
                    elif not is_bullish and raw_t1 < current_price and raw_t2 < current_price:
                        pnf_target_1 = round(raw_t1, 2)
                        pnf_target_2 = round(raw_t2, 2)
                        pnf_horizontal_count = h_count
                        pnf_derivation = (
                            f"点数图因果律(向下): 水平计数{h_count}列 x 箱体{pnf_res.get('box_size_pct', 1.0):.0f}% = "
                            f"因果目标幅{pnf_res.get('base_effect', 0):.2f} | "
                            f"1.0x基准={pnf_target_1}, 1.618x扩展={pnf_target_2}"
                        )
        except Exception as _pnf_err:
            logger.debug(f"[Wave4] PnF 因果目标计算失败，退回 ATR 兜底: {_pnf_err}")

        if is_bullish:
            # 止损修复：使用 ATR 倍数 + TR 下沿兜底
            conservative_val = round(max(current_price - 2.5 * atr, low), 2)
            aggressive_val = round(max(current_price - 1.5 * atr, low), 2)
            
            stop_loss = {
                "conservative": {
                    "value": conservative_val,
                    "derivation": "max(current_price - 2.5*ATR, TR_low)",
                    "note": "保守止损，基于2.5倍ATR和区间下沿双重保护"
                },
                "aggressive": {
                    "value": aggressive_val,
                    "derivation": "max(current_price - 1.5*ATR, TR_low)",
                    "note": "激进止损，基于1.5倍ATR和区间下沿"
                },
                "atr_dynamic_stop": {
                    "value": round(current_price - 1.5 * atr, 2),
                    "derivation": "current_price - 1.5*ATR",
                    "note": "ATR动态追踪止损"
                }
            }

            # ────── Wave 4: PnF 因果目标优先，ATR 兜底 ──────
            if pnf_target_1 is not None:
                target_1_val = pnf_target_1
                target_2_val = pnf_target_2
                t1_derivation = pnf_derivation
                t1_note = f"第一目标位（PnF 因果律 1.0x基准投影，{pnf_horizontal_count}列计数）"
                t2_note = f"第二目标位（PnF 因果律 1.618x斐波那契扩展）"
            else:
                target_1_val = round(high, 2) if current_price < high else round(current_price + atr * 2, 2)
                target_2_val = round(high + atr * 3, 2)
                t1_derivation = "TR_high if current_price < high else current_price + 2*ATR"
                t1_note = "第一目标位，测试区间高点或平推2倍ATR"
                t2_note = "第二目标位，预期趋势加速"

            targets = {
                "target_1": {
                    "value": target_1_val,
                    "derivation": t1_derivation,
                    "note": t1_note
                },
                "target_2": {
                    "value": target_2_val,
                    "derivation": pnf_derivation or "TR_high + 3*ATR",
                    "note": t2_note
                }
            }
        else:
            conservative_val = round(min(high, current_price + 2.5 * atr), 2)
            aggressive_val = round(min(high, current_price + 1.5 * atr), 2)
            
            stop_loss = {
                "conservative": {
                    "value": conservative_val,
                    "derivation": "min(TR_high, current_price + 2.5*ATR)",
                    "note": "保守止损，防止反抽过强"
                },
                "aggressive": {
                    "value": aggressive_val,
                    "derivation": "min(TR_high, current_price + 1.5*ATR)",
                    "note": "激进止损，紧跟反抽阻力"
                },
                "atr_dynamic_stop": {
                    "value": round(current_price + 1.5 * atr, 2),
                    "derivation": "current_price + 1.5*ATR",
                    "note": "ATR动态追踪止损"
                }
            }

            # ────── Wave 4: PnF 因果目标优先（做空方向）──────
            if pnf_target_1 is not None:
                target_1_val = pnf_target_1
                target_2_val = pnf_target_2
                t1_derivation = pnf_derivation
                t1_note = f"第一目标位（PnF 因果律 1.0x基准向下投影，{pnf_horizontal_count}列计数）"
                t2_note = f"第二目标位（PnF 因果律 1.618x斐波那契向下扩展）"
            else:
                target_1_val = round(low, 2) if current_price > low else round(current_price - atr * 2, 2)
                target_2_val = round(low - atr * 3, 2)
                t1_derivation = "TR_low if current_price > low else current_price - 2*ATR"
                t1_note = "第一目标位，测试区间底点或平推2倍ATR"
                t2_note = "第二目标位，看空趋势确立"

            targets = {
                "target_1": {
                    "value": target_1_val,
                    "derivation": t1_derivation,
                    "note": t1_note
                },
                "target_2": {
                    "value": target_2_val,
                    "derivation": pnf_derivation or "TR_low - 3*ATR",
                    "note": t2_note
                }
            }
        
        return entry_zone, stop_loss, targets

    
    def _adjust_position_with_sentiment(self, sentiment_data: Optional[Dict[str, Any]], 
                                         phase_str: str, is_bullish: bool) -> tuple:
        """
        根据市场情绪调整仓位
        
        Args:
            sentiment_data: 市场情绪数据
            phase_str: 当前阶段
            is_bullish: 是否看涨
            
        Returns:
            (仓位配置, 动态预警)
        """
        pos_conservative = self.DEFAULT_POSITION['conservative']
        pos_moderate = self.DEFAULT_POSITION['moderate']
        pos_aggressive = self.DEFAULT_POSITION['aggressive']
        
        dynamic_warning = None
        
        if sentiment_data:
            sentiment = sentiment_data.get("market_sentiment", "neutral")
            adjustment = self.SENTIMENT_ADJUSTMENT.get(sentiment, 1.0)
            
            pos_conservative *= adjustment
            pos_moderate *= adjustment
            pos_aggressive *= adjustment
            
            # 情绪背离预警
            if sentiment == "greed" and ("Distribution" in phase_str or "Markdown" in phase_str):
                dynamic_warning = "⚠️ 极度危险：大盘贪婪 + 个股派发 = 暴跌前兆，禁止盲目接刀！"
            elif sentiment == "extreme_fear" and ("Accumulation" in phase_str or "Markup" in phase_str):
                dynamic_warning = "💡 黄金坑预警：大盘极度恐慌 + 个股筑底 = 绝佳击球区，请重点关注抗跌表现！"
        
        pos_sizing = {
            "conservative": f"{round(pos_conservative, 1)}%总仓",
            "moderate": f"{round(pos_moderate, 1)}%总仓",
            "aggressive": f"{round(pos_aggressive, 1)}%总仓"
        }
        
        return pos_sizing, dynamic_warning
    
    def _calculate_scale_in_triggers(self, current_price: float, high: float, 
                                      low: float, atr: float, is_bullish: bool) -> Dict[str, Dict[str, Any]]:
        """
        计算分批建仓触发条件
        
        Args:
            current_price: 当前价格
            high: 区间高点
            low: 区间低点
            atr: ATR值
            is_bullish: 是否看涨
            
        Returns:
            分批建仓触发条件
        """
        if is_bullish:
            return {
                "entry_1_30pct": {
                    "condition": "当前信号出现 (如 Spring/SOS)",
                    "price": round(current_price, 2)
                },
                "entry_2_50pct": {
                    "condition": "价格突破关键阻力位或回踩支撑不破",
                    "price": round(high, 2)
                },
                "entry_3_20pct": {
                    "condition": "创出新高或确认进入强势上涨阶段 (Phase E)",
                    "price": round(high + atr, 2)
                }
            }
        else:
            return {
                "entry_1_30pct": {
                    "condition": "当前做空信号出现",
                    "price": round(current_price, 2)
                },
                "entry_2_50pct": {
                    "condition": "跌破关键支撑位或反抽阻力不破",
                    "price": round(low, 2)
                },
                "entry_3_20pct": {
                    "condition": "创出新低或确认进入强势下跌阶段 (Phase E)",
                    "price": round(low - atr, 2)
                }
            }
    
    def _calculate_exit_rules(self, atr: float) -> list:
        """
        计算退出规则
        
        Args:
            atr: ATR值
            
        Returns:
            退出规则列表
        """
        return [
            {
                "type": "trailing_stop",
                "trigger": "1ATR_profit",
                "description": f"浮盈达到1个ATR ({round(atr, 2)}元)",
                "action": "move_to_cost"
            },
            {
                "type": "trailing_stop",
                "trigger": "2ATR_profit",
                "description": f"浮盈达到2个ATR ({round(atr * 2, 2)}元)",
                "action": "move_to_1ATR_profit"
            },
            {
                "type": "time_stop",
                "trigger": "5-8_days_no_profit",
                "description": "建仓后 5-8 个交易日未脱离成本区",
                "action": "exit_position"
            }
        ]
