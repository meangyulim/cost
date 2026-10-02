import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_site import ROOT, render_report, image_payload
from directional_outlook import validate_outlook, labels


class OutlookTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((ROOT / 'data/reports/kr-pre-2026-10-02.json').read_text())
        self.report['reading'] = json.loads((ROOT / 'data/reading/kr-pre-2026-10-02.json').read_text())

    def test_independent_horizons_and_price_direction_in_web_and_image(self):
        report = self.report
        report['reading']['stocks']['005930']['outlook']['d1']['direction'] = 'down'
        report['reading']['stocks']['005930']['outlook']['d5']['direction'] = 'up'
        html = render_report(report, '.')
        self.assertIn('당일 · − 하방 우세', html)
        self.assertIn('5거래일 · + 상방 우세', html)
        self.assertIn('<b class="up">+2.79%</b>', html)  # Observed change stays separate.
        payload = image_payload(report, '.')
        self.assertEqual(payload['stocks'][0]['outlook']['d1']['direction'], 'down')
        self.assertEqual(payload['stocks'][0]['outlook']['d5']['direction'], 'up')
        self.assertEqual(payload['stocks'][0]['price'], report['stocks'][0]['price'])
        self.assertTrue(payload['outlook']['added_later'])
        self.assertIn('평가에서 제외', payload['outlook']['note'])

    def test_evidence_future_inputs_and_retroactive_evaluation_are_rejected(self):
        changes = [
            lambda r: r['reading']['outlook'].update(input_cutoff='2099-01-01T09:00:00+09:00'),
            lambda r: r['reading']['outlook'].update(evaluation_eligible=True),
            lambda r: r['reading']['stocks']['005930']['outlook']['d1'].update(sources=['unknown-source']),
            lambda r: r['reading']['stocks']['005930']['outlook']['d1'].update(probability=0.8),
            lambda r: r['reading']['stocks']['005930']['outlook']['d1'].update(invalidation=''),
            lambda r: r['reading']['stocks']['005930']['outlook'].pop('d5'),
            lambda r: r['reading'].pop('outlook'),
        ]
        for change in changes:
            with self.subTest(change=change):
                report = copy.deepcopy(self.report)
                change(report)
                with self.assertRaises(ValueError):
                    validate_outlook(report)

    def test_past_returns_never_create_forecasts_for_legacy_reports(self):
        report = json.loads((ROOT / 'data/reports/test-layout-2026-09-30.json').read_text())
        html = render_report(report, '.')
        self.assertNotIn('outlook-badge', html)
        self.assertIsNone(image_payload(report, '.')['outlook'])

    def test_labels_account_for_publication_session(self):
        self.assertEqual(labels(self.report)['d1'], '당일')
        self.report['session'] = 'close'
        self.assertEqual(labels(self.report)['d1'], '다음 거래일')
        self.report['session'] = 'intraday'
        self.assertEqual(labels(self.report)['d1'], '남은 장')
        self.assertEqual(labels(self.report)['d5'], '5거래일')
