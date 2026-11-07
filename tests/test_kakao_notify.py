from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kakao_notify as k

NOW = datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc)
FAKE_ACCESS = 'access-token-should-never-appear'


def queued(report_id='us-close-2026-11-06', **changes):
    record = {
        'report_id': report_id,
        'status': 'queued',
        'queued_at_kst': '2026-11-07T09:50:00+09:00',
        'queued_at_utc': '2026-11-07T00:50:00Z',
        'report_url': f'https://meangyulim.github.io/cost/reports/{report_id}/',
        'deployment_commit': '0' * 40,
        'deployment_run_id': 1,
        'deployment_conclusion': 'success',
        'kakao_summary': '반도체 급락 뒤 다음 한국장 개장 시나리오와 관찰 종목 위험을 정리했습니다.',
        'send_tool_called': False,
        'attempted_record_created': False,
        'retry_count': 0,
    }
    record.update(changes)
    return record


class TextLimitTests(unittest.TestCase):
    URL = 'https://meangyulim.github.io/cost/reports/us-close-2026-11-06/'

    def test_short_summary_is_kept_with_url_last(self):
        text = k.build_text('짧은 요약', self.URL)
        self.assertEqual(text, '짧은 요약\n' + self.URL)

    def test_long_summary_is_cut_but_url_is_whole(self):
        text = k.build_text('가' * 500, self.URL)
        self.assertEqual(len(text), 200)
        self.assertTrue(text.endswith('\n' + self.URL))
        self.assertTrue(text.split('\n')[0].endswith('…'))

    def test_exact_fit_is_not_cut(self):
        summary = '나' * (200 - len(self.URL) - 1)
        self.assertEqual(k.build_text(summary, self.URL), summary + '\n' + self.URL)

    def test_url_that_cannot_fit_is_rejected(self):
        with self.assertRaises(ValueError):
            k.build_text('요약', 'https://example.com/' + 'a' * 200)


class RecordCheckTests(unittest.TestCase):
    def check(self, record, name=None):
        path = Path(f'/tmp/{name or record.get("report_id")}.json')
        return k.check_record(record, path, NOW)

    def test_valid_record_passes(self):
        self.assertIsNone(self.check(queued()))

    def test_report_url_must_match_exactly(self):
        for url in ('https://meangyulim.github.io/cost/reports/us-close-2026-11-06',
                    'http://meangyulim.github.io/cost/reports/us-close-2026-11-06/',
                    'https://meangyulim.github.io/cost/reports/us-pre-2026-11-06/'):
            self.assertEqual(self.check(queued(report_url=url)), ('failed', 'report_url_mismatch'))

    def test_summary_and_flags_are_required(self):
        self.assertEqual(self.check(queued(kakao_summary='  ')), ('failed', 'missing_kakao_summary'))
        record = queued()
        del record['kakao_summary']
        self.assertEqual(self.check(record), ('failed', 'missing_kakao_summary'))
        self.assertEqual(self.check(queued(send_tool_called=True))[0], 'failed')
        self.assertEqual(self.check(queued(attempted_record_created=True))[0], 'failed')
        record = queued()
        del record['send_tool_called']
        self.assertEqual(self.check(record)[0], 'failed')

    def test_file_name_must_match_report_id(self):
        self.assertEqual(self.check(queued(), name='other'), ('failed', 'invalid_report_id'))
        self.assertEqual(self.check(queued(report_id='../x'), name='x'), ('failed', 'invalid_report_id'))

    def test_queue_older_than_six_hours_expires(self):
        old = (NOW - timedelta(hours=6, minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(self.check(queued(queued_at_utc=old)), ('expired', 'queued_over_6_hours'))
        edge = (NOW - timedelta(hours=5, minutes=59)).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertIsNone(self.check(queued(queued_at_utc=edge)))

    def test_bad_queue_time_fails(self):
        self.assertEqual(self.check(queued(queued_at_utc='어제')), ('failed', 'invalid_queued_at_utc'))
        self.assertEqual(self.check(queued(queued_at_utc='2026-11-07T00:50:00')),
                         ('failed', 'invalid_queued_at_utc'))


class SendFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pushes = []
        self.addCleanup(self.tmp.cleanup)

    def write(self, record):
        path = self.dir / f'{record["report_id"]}.json'
        path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return path

    def read(self, report_id='us-close-2026-11-06'):
        return json.loads((self.dir / f'{report_id}.json').read_text(encoding='utf-8'))

    def fake_publish(self, results):
        results = list(results)

        def publish(path, message):
            self.pushes.append((json.loads(path.read_text(encoding='utf-8'))['status'], message))
            return results.pop(0) if results else True
        return publish

    def run_send(self, publish_results=(), send_result=('sent', 200, None), refresh=(FAKE_ACCESS, None),
                 store=True):
        with patch.object(k, 'pull_rebase', return_value=True), \
                patch.object(k, 'publish', side_effect=self.fake_publish(publish_results)), \
                patch.object(k, 'verify_remote', return_value=True), \
                patch.object(k, 'refresh_access_token', return_value=refresh) as refresh_mock, \
                patch.object(k, 'store_refresh_token', return_value=store) as store_mock, \
                patch.object(k, 'send_memo', return_value=send_result) as send_mock, \
                patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            code = k.cmd_send(self.dir, clock=lambda: NOW)
        self.output = out.getvalue() + err.getvalue()
        return code, refresh_mock, store_mock, send_mock

    def test_attempted_is_pushed_before_single_send(self):
        self.write(queued())
        code, _, _, send = self.run_send()
        self.assertEqual(code, 0)
        self.assertEqual(send.call_count, 1)
        text = send.call_args.args[1]
        self.assertLessEqual(len(text), 200)
        self.assertEqual([s for s, _ in self.pushes], ['attempted', 'sent'])
        record = self.read()
        self.assertEqual(record['status'], 'sent')
        self.assertTrue(record['attempted_record_created'])
        self.assertTrue(record['send_tool_called'])
        self.assertNotIn(FAKE_ACCESS, json.dumps(record) + self.output)

    def test_attempted_push_failure_does_not_send(self):
        self.write(queued())
        code, refresh, _, send = self.run_send(publish_results=[False])
        self.assertEqual(code, 1)
        send.assert_not_called()
        refresh.assert_not_called()
        self.assertEqual([s for s, _ in self.pushes], ['attempted'])

    def test_unverified_remote_attempted_does_not_send(self):
        self.write(queued())
        with patch.object(k, 'pull_rebase', return_value=True), \
                patch.object(k, 'publish', return_value=True), \
                patch.object(k, 'verify_remote', return_value=False), \
                patch.object(k, 'send_memo') as send, \
                patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(k.cmd_send(self.dir, clock=lambda: NOW), 1)
        send.assert_not_called()

    def test_api_failure_is_recorded_once_without_retry(self):
        self.write(queued())
        code, _, _, send = self.run_send(send_result=('failed', 401, -401))
        self.assertEqual(code, 1)
        self.assertEqual(send.call_count, 1)
        record = self.read()
        self.assertEqual((record['status'], record['kakao_http_status'], record['kakao_error_code']),
                         ('failed', 401, -401))
        self.assertEqual(record['retry_count'], 0)

    def test_network_error_after_send_is_unknown(self):
        self.write(queued())
        code, _, _, send = self.run_send(send_result=('unknown', None, None))
        self.assertEqual(code, 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.read()['status'], 'unknown')

    def test_only_queued_records_are_processed(self):
        self.write(queued(report_id='us-pre-2026-11-06', status='failed'))
        self.write(queued(report_id='kr-close-2026-11-06', status='sent'))
        code, _, _, send = self.run_send()
        self.assertEqual(code, 0)
        send.assert_not_called()
        self.assertEqual(self.pushes, [])

    def test_expired_and_invalid_records_are_not_sent(self):
        self.write(queued(queued_at_utc='2026-11-06T12:00:00Z'))
        self.write(queued(report_id='us-pre-2026-11-06', report_url='https://example.com/'))
        code, _, _, send = self.run_send()
        send.assert_not_called()
        self.assertEqual(code, 1)
        self.assertEqual(self.read()['status'], 'expired')
        bad = self.read('us-pre-2026-11-06')
        self.assertEqual((bad['status'], bad['failure_reason']), ('failed', 'report_url_mismatch'))

    def test_refresh_token_rotation_failure_still_sends_but_fails_job(self):
        self.write(queued())
        code, _, store, send = self.run_send(refresh=(FAKE_ACCESS, 'new-refresh'), store=False)
        self.assertEqual(code, 1)
        store.assert_called_once_with('new-refresh')
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.read()['status'], 'sent')

    def test_token_failure_marks_failed_without_send(self):
        self.write(queued())
        with patch.object(k, 'pull_rebase', return_value=True), \
                patch.object(k, 'publish', return_value=True), \
                patch.object(k, 'verify_remote', return_value=True), \
                patch.object(k, 'refresh_access_token', side_effect=k.KakaoError('http_error', 400, 'KOE322')), \
                patch.object(k, 'send_memo') as send, \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(k.cmd_send(self.dir, clock=lambda: NOW), 1)
        send.assert_not_called()
        record = self.read()
        self.assertEqual((record['status'], record['failure_reason'], record['send_tool_called']),
                         ('failed', 'token_http_error', False))


class HttpLayerTests(unittest.TestCase):
    URL = 'https://meangyulim.github.io/cost/reports/us-close-2026-11-06/'

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self, _limit):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def test_http_error_returns_code_only_and_is_not_retried(self):
        body = json.dumps({'msg': 'secret detail', 'code': -401}).encode()
        error = urllib.error.HTTPError(k.SEND_URL, 401, 'Unauthorized', {}, io.BytesIO(body))
        with patch('urllib.request.urlopen', side_effect=error) as urlopen:
            self.assertEqual(k.send_memo(FAKE_ACCESS, 'x', self.URL), ('failed', 401, -401))
        self.assertEqual(urlopen.call_count, 1)

    def test_network_error_returns_unknown_once(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError()) as urlopen:
            self.assertEqual(k.send_memo(FAKE_ACCESS, 'x', self.URL), ('unknown', None, None))
        self.assertEqual(urlopen.call_count, 1)

    def test_success_payload_and_template(self):
        with patch('urllib.request.urlopen', return_value=self.Response(b'{"result_code":0}')) as urlopen:
            self.assertEqual(k.send_memo(FAKE_ACCESS, '요약\n' + self.URL, self.URL), ('sent', 200, None))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + FAKE_ACCESS)
        form = dict(x.split('=', 1) for x in request.data.decode().split('&'))
        template = json.loads(k.urllib.parse.unquote_plus(form['template_object']))
        self.assertEqual(template, {'object_type': 'text', 'text': '요약\n' + self.URL,
                                    'link': {'web_url': self.URL, 'mobile_web_url': self.URL},
                                    'button_title': '브리핑 열기'})

    def test_nonzero_result_code_is_failed(self):
        with patch('urllib.request.urlopen', return_value=self.Response(b'{"result_code":-1}')):
            self.assertEqual(k.send_memo(FAKE_ACCESS, 'x', self.URL), ('failed', 200, -1))

    def test_token_refresh_masks_and_hides_values(self):
        body = json.dumps({'access_token': FAKE_ACCESS, 'refresh_token': 'new-refresh'}).encode()
        env = {'KAKAO_REST_API_KEY': 'rest', 'KAKAO_REFRESH_TOKEN': 'old', 'GITHUB_ACTIONS': 'true'}
        with patch.dict('os.environ', env, clear=True), \
                patch('urllib.request.urlopen', return_value=self.Response(body)) as urlopen, \
                patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(k.refresh_access_token(), (FAKE_ACCESS, 'new-refresh'))
        lines = out.getvalue().splitlines()
        self.assertEqual(lines, [f'::add-mask::{FAKE_ACCESS}', '::add-mask::new-refresh'])
        form = urlopen.call_args.args[0].data.decode()
        self.assertIn('grant_type=refresh_token', form)
        self.assertNotIn('client_secret', form)

    def test_store_refresh_token_uses_stdin(self):
        env = {'GH_SECRET_TOKEN': 'gh', 'GITHUB_REPOSITORY': 'meangyulim/cost'}
        with patch.dict('os.environ', env, clear=True), \
                patch('subprocess.run') as run, patch('sys.stdout', new_callable=io.StringIO):
            run.return_value.returncode = 0
            self.assertTrue(k.store_refresh_token('new-refresh'))
        command = run.call_args.args[0]
        self.assertEqual(command, ['gh', 'secret', 'set', 'KAKAO_REFRESH_TOKEN', '--repo', 'meangyulim/cost'])
        self.assertNotIn('new-refresh', command)
        self.assertEqual(run.call_args.kwargs['input'], 'new-refresh')
        self.assertEqual(run.call_args.kwargs['env']['GH_TOKEN'], 'gh')


if __name__ == '__main__':
    unittest.main()
