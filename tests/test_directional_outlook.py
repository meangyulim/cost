import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_site import ROOT, render_report, image_payload
from directional_outlook import validate_outlook, validate_view, labels


def sample_view():
    return {
        'headline': '급락 뒤 이틀 연속 반등. 안도는 왔지만 아직 확인 단계예요.',
        'mood': {'level': 'relief', 'note': '경계에서 안도로 옮겨 가는 중이에요.'},
        'drivers': [
            {'title': '나쁜 뉴스에도 버텼다.', 'text': '오전 약세를 오후에 뒤집었어요.', 'sources': ['reversal-dt']},
            {'title': '기대가 컸던 곳엔 냉정하다.', 'text': '실적이 기대에 못 미친 종목은 크게 빠졌어요.', 'sources': ['krafton-fn', 'shiftup-etoday']},
        ],
        'history': [{
            'title': '비슷했던 날', 'then': '공포성 매도가 나왔어요.', 'next': '다음 날 반등했어요.',
            'after': '한동안 고점을 되찾지 못했어요.', 'difference': '이번엔 이익 전망이 받쳐 줘요.', 'sources': ['close-asiae'],
        }],
        'paths': {'good': '외국인 매수가 이어지면 회복으로 볼 수 있어요.', 'caution': '물가 지표가 높게 나오면 불안이 돌아올 수 있어요.'},
        'estimated_at': '2026-11-11T15:51:00+09:00', 'input_cutoff': '2026-11-11T15:50:00+09:00', 'added_later': False,
    }


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((ROOT / 'data/reports/kr-close-2026-11-11.json').read_text())
        self.report['reading']['view'] = sample_view()

    def test_reading_replaces_badges_with_plain_words_on_web_and_card(self):
        html = render_report(self.report, '.')
        self.assertIn('<h2 id="reading-title">시장 읽기</h2>', html)
        self.assertIn('급락 뒤 이틀 연속 반등', html)
        self.assertIn('작성자 해석 · 지표 아님', html)
        self.assertIn('<b>안도</b>', html)
        self.assertIn('왜 이런 분위기일까', html)
        self.assertIn('같은 흐름이 반복된다는 뜻은 아니에요', html)
        self.assertIn('<b>좋은 쪽</b>', html)
        reversal = next(s for s in self.report['sources'] if s['id'] == 'reversal-dt')
        self.assertIn(f'href="{reversal["url"]}"', html.split('id="reading"')[1].split('</section>')[0])
        # No horizon badges, direction labels or distances anywhere on the page.
        for removed in ('class="chip', '상방 우세', '하방 우세', '재료 상충', '판단 보류', 'id="lines"', 'distance-row'):
            self.assertNotIn(removed, html)
        card = image_payload(self.report, '.')['reading']
        self.assertEqual(card['mood_label'], '안도')
        self.assertEqual(card['drivers'][0]['title'], '나쁜 뉴스에도 버텼다.')
        self.assertEqual(card['history'][0]['next'], '다음 날 반등했어요.')
        self.assertNotIn('sources', json.dumps(card))
        self.assertNotIn('outlook', json.dumps(image_payload(self.report, '.')['stocks']))

    def test_hidden_sources_are_never_cited(self):
        for source in self.report['sources']:
            if source['id'] == 'reversal-dt':
                source['show_public'] = False
                source['label'] = 'hidden-provider'
        html = render_report(self.report, '.')
        self.assertNotIn('hidden-provider', html)

    def test_reading_rejects_probabilities_unsourced_or_future_claims(self):
        changes = [
            lambda v: v.update(probability=0.7),
            lambda v: v['mood'].update(level='panic'),
            lambda v: v['drivers'][0].update(sources=['unknown-source']),
            lambda v: v['drivers'][0].update(sources=[]),
            lambda v: v['drivers'][0].update(text=' '),
            lambda v: v['drivers'][0].update(target_return='+5%'),
            lambda v: v['history'][0].pop('difference'),
            lambda v: v['history'][0].update(sources=[]),
            lambda v: v.update(history=v['history'] * 3),
            lambda v: v['paths'].pop('caution'),
            lambda v: v.update(input_cutoff='2099-01-01T09:00:00+09:00'),
            lambda v: v.update(estimated_at='2026-11-11T17:00:00+09:00'),
            lambda v: v.update(estimated_at='2026-11-11T06:51:00+00:00'),
        ]
        for change in changes:
            with self.subTest(change=change):
                report = copy.deepcopy(self.report)
                change(report['reading']['view'])
                with self.assertRaises((ValueError, KeyError)):
                    validate_view(report)
        late = copy.deepcopy(self.report)
        late['reading']['view'].update(estimated_at='2026-11-11T17:00:00+09:00', added_later=True)
        validate_view(late)
        self.assertIn('11.11 17:00 추가', render_report(late, '.'))

    def test_history_is_optional_but_drivers_are_not(self):
        report = copy.deepcopy(self.report)
        report['reading']['view']['history'] = []
        html = render_report(report, '.')
        self.assertNotIn('class="history"', html)
        report['reading']['view']['drivers'] = []
        with self.assertRaises(ValueError):
            validate_view(report)


class LegacyOutlookTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((ROOT / 'data/reports/kr-pre-2026-10-02.json').read_text())
        self.report['reading'] = json.loads((ROOT / 'data/reading/kr-pre-2026-10-02.json').read_text())

    def test_older_editions_read_as_sentences_without_badges(self):
        html = render_report(self.report, '.')
        self.assertIn('이전 형식 요약', html)
        self.assertIn('<b>당일</b> 오를 쪽 재료가 더 많다고 봤어요.', html)
        entry = self.report['reading']['issues'][0]
        for key in ('d1', 'd5'):
            self.assertIn(entry['outlook'][key]['invalidation'].replace('"', '&quot;').replace("'", '&#x27;'), html)
        for removed in ('class="chip', '상방 우세', '재료 상충', '방향 의견'):
            self.assertNotIn(removed, html)
        card = image_payload(self.report, '.')['reading']
        self.assertEqual(card['legacy'][0]['label'], '당일')
        self.assertIn('평가에서 제외', card['note'])

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

    def test_past_returns_never_create_readings_for_reports_without_one(self):
        report = json.loads((ROOT / 'data/reports/test-layout-2026-09-30.json').read_text())
        html = render_report(report, '.')
        self.assertNotIn('id="reading"', html)
        self.assertIsNone(image_payload(report, '.')['reading'])

    def test_labels_account_for_publication_session(self):
        self.assertEqual(labels(self.report)['d1'], '당일')
        self.report['session'] = 'close'
        self.assertEqual(labels(self.report)['d1'], '다음 거래일')
        self.report['session'] = 'intraday'
        self.assertEqual(labels(self.report)['d1'], '남은 장')
        self.assertEqual(labels(self.report)['d5'], '5거래일')
