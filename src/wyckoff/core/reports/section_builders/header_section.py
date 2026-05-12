from datetime import datetime
from .base_builder import BaseSectionBuilder

class HeaderSection(BaseSectionBuilder):
    """构建报告头部及基础数据区块"""
    def build(self, phase_result: dict, trading_range: dict) -> str:
        phase_str = phase_result.get('phase', 'Unknown')
        phase_conf = phase_result.get('confidence', 0.0)
        ma_conf = phase_result.get('ma_confidence', 0)
        vol_conf = phase_result.get('vol_confidence', 0)
        seq_rating = phase_result.get('sequence_score', {}).get('rating', '')

        conf_icon = '[OK]' if phase_conf >= 0.75 else '[WARN]' if phase_conf >= 0.50 else '[ERR]'
        
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
"""
        duration_days = trading_range.get('duration_days', 0)
        consolidation_duration = trading_range.get('consolidation_duration_days', 0)
        
        if duration_days >= 60:
            time_assessment = "[YES] 该结构已运行60天以上，已具备充足的时间基础，结构可靠性高"
        elif duration_days >= 30:
            time_assessment = "[!] 该结构已运行30-60天，时间基础尚可，结构正在形成中"
        else:
            time_assessment = "⏳ 该结构运行不足30天，时间基础薄弱，结构尚未成熟"

        report += f"""
【基础数据】
当前价格: {self.data['Close'].iloc[-1]:.2f}
52周最高: {self.data['High'].tail(252).max():.2f}
52周最低: {self.data['Low'].tail(252).min():.2f}
成交量: {self.data['Volume'].iloc[-1]:,.0f}
量比: {self.data['Volume'].iloc[-1] / max(self.data['Volume_MA20'].iloc[-1], 1):.2f}
"""
        rs_data = phase_result.get('relative_strength', {})
        if rs_data.get('rs_anomaly_warning'):
            report += f"\n[!] 【数据质量警告】\n{rs_data['rs_anomaly_warning']}\n"

        report += f"""
【时间维度分析】
结构持续时间: {duration_days} 天
盘整持续时间: {consolidation_duration} 天
时间评估: {time_assessment}
💡 威科夫理论：时间是结构可靠性的重要维度。持续时间越长，结构越成熟，突破后的趋势延续性越强。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        return report
