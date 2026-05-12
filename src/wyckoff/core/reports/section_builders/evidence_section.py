from .base_builder import BaseSectionBuilder

class EvidenceSection(BaseSectionBuilder):
    """构建核心证据清单区块"""
    def build(self, phase_result: dict) -> str:
        core_evidence = phase_result.get('core_evidence', {})
        if not core_evidence or 'error' in core_evidence:
            return ''
            
        evidence = core_evidence.get('evidence', {})
        evidence_count = core_evidence.get('evidence_count', 0)
        total_checks = core_evidence.get('total_checks', 4)
        strength = core_evidence.get('strength', 'none')
        
        text = f"\n【核心证据清单】（孟洪涛方法）\n   Phase A 确认度: {evidence_count}/{total_checks} ({strength.upper()})\n"
        text += "   注意：Phase A 标准事件为 PS → SC → AR → ST，SOT/Spring为辅助信号\n"

        # SC
        sc = evidence.get('sc', {})
        if sc.get('detected') and all(k in sc for k in ['date', 'price', 'volume_ratio', 'confidence']):
            text += f"   [Phase A] SC (恐慌抛售): {sc['date']} 价格{sc['price']:.2f} 量比{sc['volume_ratio']:.1f}x 置信度{sc['confidence']:.0f}%\n"
        else:
            text += "   [Phase A] SC (恐慌抛售): 未检测到\n"

        # PS
        ps = evidence.get('ps', {})
        if ps.get('detected') and all(k in ps for k in ['rebound_pct', 'sc_date', 'ps_date', 'confidence']):
            text += f"   [Phase A] PS (初步支撑): 反弹{ps['rebound_pct']:.1f}% ({ps['sc_date']} → {ps['ps_date']}) 置信度{ps['confidence']:.0f}%\n"
        else:
            text += "   [Phase A] PS (初步支撑): 未检测到\n"

        # AR
        ar = evidence.get('ar', {})
        if ar.get('detected') and all(k in ar for k in ['date', 'price', 'decline_pct', 'confidence']):
            text += f"   [Phase A] AR (自动反弹): {ar.get('date','?')} 价格{ar.get('price',0):.2f} 回撤{ar.get('decline_pct',0)*100:.1f}% 置信度{ar.get('confidence',0):.0f}%\n"
        else:
            text += "   [Phase A] AR (自动反弹): 未检测到\n"

        # ST
        st = evidence.get('st', {})
        if st.get('detected') and all(k in st for k in ['date', 'price', 'volume', 'confidence']):
            text += f"   [Phase A] ST (二次测试): {st['date']} 价格{st['price']:.2f} 量比{st['volume_ratio']:.2f}x 置信度{st['confidence']:.0f}%\n"
        else:
            text += "   [Phase A] ST (二次测试): 未检测到\n"

        # Spring (辅助)
        spring_ev = evidence.get('spring', {})
        if spring_ev.get('detected') and all(k in spring_ev for k in ['date', 'close', 'filters_passed']):
            try:
                intraday_data = getattr(self.generator, '_get_intraday_data_fn', lambda tf: None)("60m")
                spring_quality = self.pattern_detector.meng_enhancer._analyze_spring_intraday_quality(intraday_data)
                quality_text = f"质量评分{spring_quality['quality_score']} ({spring_quality['recovery_type']})"
                observation = f"\n       微观细节: {spring_quality['observation']}"
            except Exception:
                quality_text = "质量未评估 (数据获取失败)"
                observation = ""
            text += f"   ✓ Spring (弹簧): {spring_ev['date']} 收盘{spring_ev['close']:.2f} 滤网{spring_ev['filters_passed']}/5 {quality_text}{observation}\n"
        else:
            text += "   ✗ Spring (弹簧): 未检测到\n"

        if strength == 'strong':
            text += f"   >>> 强 Phase A ({evidence_count}/{total_checks}) - 可考虑LPS入场\n"
        elif strength == 'weak':
            text += f"   >>> 弱 Phase A ({evidence_count}/{total_checks}) - 建议等待更多证据\n"
        else:
            text += "   >>> 无 Phase A 证据 - 当前处于趋势或深度休整中\n"
            
        return text
