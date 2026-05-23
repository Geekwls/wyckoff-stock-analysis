"""Strategy decision audit log tests."""
import json
import unittest

import pandas as pd

from wyckoff.config.settings import WyckoffThresholds
from wyckoff.core.enums import MarketEnvironment
from wyckoff.core.recommendation_engine import RecommendationEngine
from wyckoff.core.strategy_decision_audit import (
    StrategyDecisionAuditLog,
    audit_summary_fields,
    format_audit_markdown,
    iter_audit_jsonl_records,
    write_audit_jsonl,
)
from wyckoff.core.wie3_market_state_service import WIE3AnalysisResult, WIE3MarketStateService
from wyckoff.core.searchlight_enrichment import enrich_patterns_with_searchlight


class _MockBearishMarketState:
    def to_dict(self):
        return {
            'state_probs': {
                'S0: Panic Liquidation (恐慌出清)': 0.62,
                'S1: Absorption (主力高密持续吸收)': 0.15,
            },
            'aps': 2.0,
            'is_confidence_degraded': False,
            'hidden_weakness': False,
            'hidden_strength': False,
            'regime': 'S0: Panic Liquidation (恐慌出清)',
        }


def _sample_ohlcv(rows: int = 60) -> pd.DataFrame:
    close = [100.0 + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        'Open': close,
        'High': [c + 1.0 for c in close],
        'Low': [c - 1.0 for c in close],
        'Close': close,
        'Volume': [1000 + i * 10 for i in range(rows)],
        'ATR': [2.0] * rows,
        'Volume_MA20': [1200.0] * rows,
    })


class TestStrategyDecisionAuditLog(unittest.TestCase):
    def test_records_all_categories(self):
        log = StrategyDecisionAuditLog()
        log.begin('TEST')
        log.record_score_penalty('scoring.test', -10, 80, 70, 'test penalty')
        log.record_score_cap('scoring.cap.test', 55, 70, 55, 'test cap')
        log.record_position_reduce('plan.test', '50%', '25%', 'half size', position_factor=0.5)
        log.record_watch('plan.test_watch', 'wait', direction_before='做多')

        payload = log.to_dict()
        self.assertEqual(payload['symbol'], 'TEST')
        self.assertEqual(payload['summary']['total_events'], 4)
        self.assertEqual(payload['summary']['by_category']['score_penalty'], 1)
        self.assertEqual(payload['summary']['by_category']['score_cap'], 1)
        self.assertEqual(payload['summary']['by_category']['position_reduce'], 1)
        self.assertEqual(payload['summary']['by_category']['watch'], 1)

    def test_audit_summary_fields(self):
        log = StrategyDecisionAuditLog()
        log.begin('ABC')
        log.record_watch('plan.test', 'wait')
        summary = audit_summary_fields(log.to_dict())
        self.assertEqual(summary['audit_event_count'], 1)
        self.assertEqual(summary['audit_watch_count'], 1)
        self.assertEqual(summary['audit_rule_ids'], ['plan.test'])

    def test_format_audit_markdown(self):
        log = StrategyDecisionAuditLog()
        log.begin('TEST')
        log.record_score_cap('scoring.cap.test', 55, 70, 55, 'cap test')
        log.record_watch('plan.test_watch', 'wait', direction_before='做多')
        text = format_audit_markdown(log.to_dict())
        self.assertIn('策略决策审计日志', text)
        self.assertIn('scoring.cap.test', text)
        self.assertIn('plan.test_watch', text)
        self.assertIn('得分 70→55', text)

    def test_write_audit_jsonl(self):
        import tempfile
        from pathlib import Path

        log = StrategyDecisionAuditLog()
        log.begin('JSONL')
        log.record_watch('plan.a', 'one')
        log.record_watch('plan.b', 'two')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'audit.jsonl'
            count = write_audit_jsonl(log.to_dict(), str(path), append=False)
            lines = path.read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(count, 2)
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first['symbol'], 'JSONL')
        self.assertEqual(first['rule_id'], 'plan.a')
        self.assertEqual(len(iter_audit_jsonl_records(log.to_dict())), 2)


class TestRecommendationEngineAuditIntegration(unittest.TestCase):
    def test_searchlight_contradiction_emits_score_cap_rule(self):
        data = _sample_ohlcv()
        engine = RecommendationEngine()
        engine.begin_decision_audit('ACC')

        patterns = {
            'symbol': 'ACC',
            'phase': 'Accumulation Phase D',
            'events_detected': {
                'spring': {'detected': True, 'confidence': 0.9, 'volume_ratio': 1.6},
                'sos': {'detected': True, 'confidence': 0.85, 'volume_ratio': 1.4},
            },
        }
        service = WIE3MarketStateService(WyckoffThresholds())
        service.analyze = lambda _data, index_df=None, resolve_index_df=None: WIE3AnalysisResult(
            market_state=_MockBearishMarketState(),
            df_vsa=pd.DataFrame(),
        )
        patterns = enrich_patterns_with_searchlight(
            patterns, data, service, WyckoffThresholds()
        )

        quality = engine.calculate_signal_quality(data, patterns, MarketEnvironment.UNKNOWN)
        audit = engine.get_decision_audit()

        self.assertLessEqual(quality.score, 45)
        rule_ids = audit['summary']['rule_ids']
        self.assertIn('scoring.cap.searchlight_bearish_vs_accumulation', rule_ids)

    def test_spring_pending_joc_emits_watch_rule(self):
        data = _sample_ohlcv()
        engine = RecommendationEngine()
        engine.begin_decision_audit('SPR')

        patterns = {
            'symbol': 'SPR',
            'phase': 'Accumulation Phase C',
            'events_detected': {
                'spring': {
                    'detected': True,
                    'confidence': 0.9,
                    'volume_ratio': 1.6,
                    'latest_spring': {
                        'breakdown_price': 98.0,
                        'price': 98.0,
                        'lifecycle_status': 'active',
                    },
                },
            },
        }

        plan = engine.generate_trading_plan(data, patterns, {'target_1': 110.0})
        audit = engine.get_decision_audit()

        self.assertEqual(plan.direction, '观望')
        rule_ids = audit['summary']['rule_ids']
        self.assertIn('plan.spring_pending_joc', rule_ids)

    def test_risk_advice_watch_for_plan_direction(self):
        engine = RecommendationEngine()
        engine.begin_decision_audit('RISK')
        from wyckoff.schemas import SignalQualityModel, TradingPlanModel, StopLossModel, TargetsModel, PositionSizingModel

        quality = SignalQualityModel(score=10, max_score=100, confidence='低', reasons=[])
        plan = TradingPlanModel(
            direction='观望',
            entry_zone='等待确认',
            stop_loss=StopLossModel(conservative=0.0, aggressive=0.0),
            targets=TargetsModel(target_1=0, target_2=0),
            position_sizing=PositionSizingModel(
                conservative='0%', moderate='0%', aggressive='0%'
            ),
            holding_period='1-2周',
        )
        advice = engine.generate_risk_advice(quality, plan)
        audit = engine.get_decision_audit()

        self.assertEqual(advice.conservative.action, '观望')
        self.assertIn('risk.plan_direction_watch', audit['summary']['rule_ids'])

    def test_generate_trading_plan_does_not_duplicate_scoring_audit(self):
        data = _sample_ohlcv()
        engine = RecommendationEngine()
        engine.begin_decision_audit('DEDUP')

        patterns = {
            'symbol': 'DEDUP',
            'phase': 'Accumulation Phase D',
            'events_detected': {
                'spring': {'detected': True, 'confidence': 0.9, 'volume_ratio': 1.6},
            },
        }
        engine.calculate_signal_quality(data, patterns, MarketEnvironment.UNKNOWN)
        scoring_events = engine.get_decision_audit()['summary']['total_events']

        engine.generate_trading_plan(data, patterns, {})
        total_events = engine.get_decision_audit()['summary']['total_events']

        self.assertGreater(total_events, scoring_events)
        self.assertEqual(
            engine.get_decision_audit()['summary']['by_stage'].get('scoring', 0),
            scoring_events,
        )



class TestOrchestratorAuditPayload(unittest.TestCase):
    def test_assembled_result_includes_audit_key(self):
        from wyckoff.core.orchestrator import WyckoffOrchestrator

        orch = WyckoffOrchestrator()
        orch.rec_engine.begin_decision_audit('X')
        orch.rec_engine.get_decision_audit()['summary']['total_events']
        payload = orch.rec_engine.get_decision_audit()
        self.assertIn('entries', payload)
        self.assertIn('summary', payload)

        # JSON serializable for backtest export
        json.dumps(payload, default=str)


if __name__ == '__main__':
    unittest.main()
