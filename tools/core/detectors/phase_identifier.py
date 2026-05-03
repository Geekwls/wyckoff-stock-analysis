import pandas as pd
from typing import Dict, Tuple, List, Optional, Union
from ...config.settings import WyckoffConfig
from ..enums import WyckoffPhase
from ..utils import PhaseAdapter

class PhaseIdentifier:
    """负责识别威科夫阶段和评分"""
    def __init__(self, data: pd.DataFrame, config: WyckoffConfig):
        self.data = data
        self.config = config

    def identify(self, events: Dict) -> Dict:
        """主识别流程"""
        if self.data is None:
            return {'phase': 'Unknown', 'confidence': 0.0, 'phase_enum': WyckoffPhase.UNKNOWN}

        phase_str, phase_enum, confidence = self._determine_phase_from_events(events)
        if phase_enum == WyckoffPhase.UNKNOWN:
            phase_str, phase_enum, confidence = self._fallback_logic()

        ma_conf = self._check_ma_confirmation(phase_enum)
        vol_conf = self._check_volume_confirmation(phase_enum)
        
        final_conf = confidence * 0.5 + ma_conf * 0.3 + vol_conf * 0.2
        seq_score = self.calculate_sequence_score(events, phase_enum)
        final_conf *= seq_score.get('adjustment_factor', 1.0)

        return {
            'phase': phase_str,
            'phase_enum': phase_enum,
            'confidence': round(min(final_conf, 1.0), 2),
            'ma_confidence': round(ma_conf, 2),
            'vol_confidence': round(vol_conf, 2),
            'sequence_score': seq_score
        }

    def _determine_phase_from_events(self, events: Dict) -> Tuple[str, WyckoffPhase, float]:
        """从事件序列中判定阶段"""
        su = events.get('spring_upthrust') or {}
        ss = events.get('sos_sow') or {}
        cl = events.get('climax') or {}
        ar = events.get('automatic_reaction') or {}
        st = events.get('secondary_test') or {}

        is_spring = su.get('detected') and su.get('_type') == 'spring'
        is_upthrust = su.get('detected') and su.get('_type') == 'upthrust'
        is_sos = ss.get('detected') and ss.get('_type') == 'sos'
        is_sow = ss.get('detected') and ss.get('_type') == 'sow'

        if is_spring and is_sos: 
            return 'Accumulation Phase D (积累期突破)', WyckoffPhase.PHASE_D, 0.85
        if is_spring: 
            return 'Accumulation Phase C (积累期震仓)', WyckoffPhase.PHASE_C, 0.70
        if is_upthrust and is_sow: 
            return 'Distribution Phase D (派发期跌破)', WyckoffPhase.PHASE_D, 0.85
        if is_upthrust: 
            return 'Distribution Phase C (派发期诱多)', WyckoffPhase.PHASE_C, 0.70
            
        if cl.get('detected') and ar.get('detected'):
            if cl.get('type') == 'selling_climax': 
                return 'Accumulation Phase A (恐慌抛售停止)', WyckoffPhase.PHASE_A, 0.75
            return 'Distribution Phase A (买入高潮停止)', WyckoffPhase.PHASE_A, 0.75
            
        if st.get('detected'):
            if cl.get('type') == 'selling_climax': 
                return 'Accumulation Phase B (积累期测试)', WyckoffPhase.PHASE_B, 0.60
            return 'Distribution Phase B (派发期测试)', WyckoffPhase.PHASE_B, 0.60
            
        return 'Unknown', WyckoffPhase.UNKNOWN, 0.30

    def _fallback_logic(self) -> Tuple[str, WyckoffPhase, float]:
        """基于均线排布的降级判定逻辑"""
        ma20, ma50, ma200 = self.data['MA20'].iloc[-1], self.data['MA50'].iloc[-1], self.data['MA200'].iloc[-1]
        current = self.data['Close'].iloc[-1]
        
        if current > ma20 > ma50 > ma200: 
            return "Markup Phase E (强势上涨)", WyckoffPhase.PHASE_E, 0.6
        if current < ma20 < ma50 < ma200: 
            return "Markdown Phase E (强势下跌)", WyckoffPhase.PHASE_E, 0.6
            
        return "Trending (趋势中)", WyckoffPhase.UNKNOWN, 0.4

    def _check_ma_confirmation(self, phase: Union[str, WyckoffPhase]) -> float:
        """检查均线确认"""
        ma200, current = self.data['MA200'].iloc[-1], self.data['Close'].iloc[-1]
        if PhaseAdapter.is_accumulation(phase) or PhaseAdapter.is_markup(phase): 
            return 0.8 if current > ma200 else 0.4
        if PhaseAdapter.is_distribution(phase) or PhaseAdapter.is_markdown(phase): 
            return 0.8 if current < ma200 else 0.4
        return 0.5

    def _check_volume_confirmation(self, phase: Union[str, WyckoffPhase]) -> float:
        """检查成交量确认 (Effort vs Result)"""
        df = self.data.tail(20)
        up_v = df[df['Close'] > df['Close'].shift(1)]['Volume'].mean()
        dn_v = df[df['Close'] < df['Close'].shift(1)]['Volume'].mean()
        ratio = up_v / dn_v if dn_v > 0 else 1
        
        if PhaseAdapter.is_markup(phase): 
            return 0.9 if ratio > 1.2 else 0.5
        if PhaseAdapter.is_markdown(phase): 
            return 0.9 if ratio < 0.8 else 0.5
        return 0.5

    def calculate_sequence_score(self, events: Dict, phase: Union[str, WyckoffPhase]) -> Dict:
        """计算事件序列完整性得分"""
        count = 0
        checks = ['climax', 'automatic_reaction', 'secondary_test', 'spring_upthrust', 'sos_sow']
        for c in checks:
            event = events.get(c) or {}
            if event.get('detected'): count += 1
            
        completeness = (count / len(checks)) * 100
        factor = 1.0 if completeness >= 80 else 0.8 if completeness >= 60 else 0.6
        return {
            'completeness': completeness, 
            'adjustment_factor': factor, 
            'rating': 'S' if completeness >= 80 else 'B' if completeness >= 60 else 'C'
        }
