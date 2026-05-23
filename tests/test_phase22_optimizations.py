"""Phase 22：报告/旁路 effective_phase 统一"""
import unittest

from wyckoff.core.signal_extractor import SignalExtractor


class TestEffectivePhaseAuthority(unittest.TestCase):
    def test_prefers_effective_phase_field(self):
        phase = {
            'phase': 'Accumulation Phase C',
            'effective_phase': 'Distribution Phase C/D',
            'coordinator_phase': 'Distribution Phase C/D',
        }
        self.assertEqual(
            SignalExtractor.get_effective_phase(phase),
            'Distribution Phase C/D',
        )

    def test_falls_back_to_phase(self):
        phase = {'phase': 'Accumulation Phase C'}
        self.assertEqual(SignalExtractor.get_effective_phase(phase), 'Accumulation Phase C')


class TestScoringPayloadPhaseFields(unittest.TestCase):
    def test_payload_includes_audit_fields(self):
        phase_result = {
            'phase': 'Accumulation Phase C',
            'effective_phase': 'Accumulation Phase C',
            'identifier_phase': 'Accumulation Phase C',
            'coordinator_phase': 'Accumulation Phase C',
            'events_detected': {'spring': {'detected': True}},
        }
        payload = SignalExtractor.build_scoring_payload(phase_result)
        self.assertEqual(payload['phase'], 'Accumulation Phase C')
        self.assertEqual(payload['effective_phase'], 'Accumulation Phase C')
        self.assertEqual(payload['identifier_phase'], 'Accumulation Phase C')

    def test_scoring_payload_uses_coordinator_when_merged(self):
        phase_result = {
            'phase': 'Distribution Phase C/D',
            'effective_phase': 'Distribution Phase C/D',
            'identifier_phase': 'Accumulation Phase C',
            'coordinator_phase': 'Distribution Phase C/D',
            'phase_source': 'coordinator',
            'events_detected': {'sow': {'detected': True}},
        }
        payload = SignalExtractor.build_scoring_payload(phase_result)
        self.assertEqual(payload['phase'], 'Distribution Phase C/D')
        self.assertEqual(payload['identifier_phase'], 'Accumulation Phase C')


if __name__ == '__main__':
    unittest.main()
