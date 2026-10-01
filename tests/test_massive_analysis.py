import copy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import massive_analysis as m


class MassiveTests(unittest.TestCase):
    def points(self, down=False):
        return [(date(2026, 6, 1) + timedelta(days=i), 100 + (-i if down else i), 1000) for i in range(65)]

    def test_returns_and_trend_use_sessions(self):
        result = m.metrics('SPY', self.points(), 'market')
        self.assertEqual(result['return_20_sessions_pct'], round((164 / 144 - 1) * 100, 4))
        self.assertEqual(result['trend'], '상승 추세 조건 충족')
        self.assertEqual(m.metrics('SPY', self.points(True), 'market')['trend'], '하락 추세 조건 충족')

    def test_bar_dates_use_new_york_and_reject_duplicates(self):
        timestamp = datetime(2026, 9, 30, 0, 0, tzinfo=m.NY).timestamp() * 1000
        row = {'t': timestamp, 'c': 12, 'v': 20}
        self.assertEqual(m.validate_bars([row], date(2026, 9, 30), date(2026, 9, 30))[0][0], date(2026, 9, 30))
        with self.assertRaises(m.DataError):
            m.validate_bars([row, row], date(2026, 9, 30), date(2026, 9, 30))
        with self.assertRaises(m.DataError):
            m.validate_bars([row], date(2026, 9, 29), date(2026, 9, 29))

    def test_breadth_excludes_unpaired_and_zero_volume(self):
        now = {'A': (11, 10), 'B': (8, 10), 'C': (10, 10), 'NEW': (10, 10), 'IDLE': (10, 0)}
        before = {'A': (10, 10), 'B': (10, 10), 'C': (10, 10), 'IDLE': (10, 10)}
        result = m.breadth(now, before)
        self.assertEqual(result['paired_traded_rows'], 3)
        self.assertEqual(result['excluded_current_rows'], 2)
        self.assertEqual(result['advancing_share_pct'], 33.33)
        self.assertIn('보통주만', result['scope'])

    def test_nonfinite_or_missing_data_never_become_zero(self):
        for value in (None, 'NaN', float('inf'), True):
            with self.assertRaises(m.DataError):
                m.numeric(value)
        with self.assertRaises(m.DataError):
            m.metrics('SPY', self.points()[:20], 'market')

    def test_safe_paths_and_output_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'result.json'
            m.write_output(output, {'data_date': '2026-09-30'}, 'secret-test-value')
            self.assertEqual(json.loads(output.read_text())['data_date'], '2026-09-30')
            with self.assertRaises(m.DataError):
                m.write_output(output, {'secret': 'secret-test-value'}, 'secret-test-value')
        with self.assertRaises(m.DataError):
            m.write_output(m.ROOT / 'public/test.json', {}, 'key')
        with self.assertRaises(m.DataError):
            m.Client('key').fetch('//untrusted.example/path')
        with self.assertRaises(m.DataError):
            m.watch_tickers(['NVDA?apiKey=secret'])

    def test_missing_key_and_no_redirect(self):
        with self.assertRaises(m.DataError):
            m.Client(' ')
        self.assertIsNone(m.NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_auth_error_is_not_retried_or_leaked(self):
        from io import BytesIO
        error = urllib.error.HTTPError('https://host', 401, 'unauthorized', {}, BytesIO(b'{"message":"secret-test-value"}'))
        opener = unittest.mock.Mock()
        opener.open.side_effect = error
        with patch.object(m.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(m.DataError) as raised:
                m.Client('secret-test-value', interval=0).fetch('/v1/open-close/AAPL/2026-09-30')
        self.assertEqual(opener.open.call_count, 1)
        self.assertNotIn('secret-test-value', str(raised.exception))

    def test_transient_error_retries_with_header_auth(self):
        from io import BytesIO
        error = urllib.error.HTTPError('https://host', 503, 'failure', {}, BytesIO(b'{}'))
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"status":"OK"}'
        opener = unittest.mock.Mock()
        opener.open.side_effect = [error, response]
        with patch.object(m.urllib.request, 'build_opener', return_value=opener), patch.object(m.time, 'sleep'):
            m.Client('test-key', interval=0).fetch('/v1/open-close/AAPL/2026-09-30')
        req = opener.open.call_args.args[0]
        self.assertEqual(req.get_header('Authorization'), 'Bearer test-key')
        self.assertNotIn('test-key', req.full_url)


if __name__ == '__main__':
    unittest.main()
