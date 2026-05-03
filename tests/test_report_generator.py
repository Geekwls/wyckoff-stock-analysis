import pandas as pd
from tools.wyckoff_analyzer import WyckoffAnalyzer


def test_generate_report_with_spring_uses_recovery_day(monkeypatch, flat_data):
    analyzer = WyckoffAnalyzer('AAPL')
    analyzer.data = flat_data
    analyzer.fetch_data = lambda: flat_data

    class StubDetector:
        def identify_phase(self):
            return 'Accumulation Phase'

        def detect_trading_range(self):
            return {
                'is_consolidation': True,
                'low': 95.0,
                'high': 105.0,
                'range_pct': 0.1,
                'position': 0.5,
                'volume_trend': 'decreasing',
            }

        def detect_spring(self):
            return {
                'detected': True,
                'latest_spring': {
                    'date': pd.Timestamp('2025-01-15'),
                    'breakdown_price': 96.0,
                    'support_level': 97.0,
                    'recovery_price': 99.0,
                    'recovery_day': 2,
                },
            }

        def detect_upthrust(self):
            return {'detected': False}

        def detect_sos(self):
            return {'detected': False}

        def detect_sow(self):
            return {'detected': False}

        def detect_lps(self):
            return {'detected': False}

        def detect_lpsy(self):
            return {'detected': False}

    analyzer.pattern_detector = StubDetector()
    analyzer.law_analyzer = object()

    monkeypatch.setattr(analyzer, 'calculate_cause_effect', lambda: {
        'cause_size': 10.0,
        'targets': {'target_1': 110.0, 'target_2': 120.0, 'target_3': 130.0},
    })

    report = analyzer.generate_report()

    assert '检测到Spring' in report
    assert '收回天数: 2天' in report
