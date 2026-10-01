from datetime import date, timedelta
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from krx_analysis import Client, DataError, NoRedirect, ROOT, breadth, etf_strength, number, price_index, save_result, series_metrics


class KrxTests(unittest.TestCase):
    def test_secret_is_required_and_never_printed_on_http_error(self):
        with self.assertRaises(DataError):
            Client('')
        marker = 'TEST_CREDENTIAL_DO_NOT_LOG'
        error = urllib.error.HTTPError('https://data-dbg.krx.co.kr', 401, marker, {}, io.BytesIO(marker.encode()))
        with patch('urllib.request.OpenerDirector.open', side_effect=error):
            with self.assertRaises(DataError) as failure:
                Client(marker).fetch('idx/kospi_dd_trd', date(2026, 9, 30))
        self.assertNotIn(marker, str(failure.exception))
        self.assertIn('401', str(failure.exception))
        self.assertIsNone(NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_date_mismatch_cannot_enter_history(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'{"OutBlock_1":[{"BAS_DD":"20260929"}]}'
        with patch('urllib.request.OpenerDirector.open', return_value=Response()):
            with self.assertRaises(DataError):
                Client('fixture').fetch('idx/kospi_dd_trd', date(2026, 9, 30))

    def test_trend_returns_use_sessions_and_do_not_claim_probability(self):
        points = [(date(2026, 1, 1) + timedelta(days=i * 2), {'CLSPRC_IDX': str(100 + i), 'FLUC_RT': '1'}) for i in range(65)]
        result = series_metrics(points, 'fixture')
        self.assertEqual(result['trend'], '상승 추세 조건 충족')
        self.assertAlmostEqual(result['return_5_sessions_pct'], (164 / 159 - 1) * 100, places=3)
        self.assertAlmostEqual(result['return_20_sessions_pct'], (164 / 144 - 1) * 100, places=3)
        self.assertEqual(result['ma20'], 154.5)
        self.assertEqual(result['ma60'], 134.5)
        with self.assertRaises(DataError):
            series_metrics(points[:64], 'too short')
        points[-1][1]['CLSPRC_IDX'] = '-'
        with self.assertRaises(DataError):
            series_metrics(points, 'missing')

    def test_breadth_excludes_nontraded_and_missing_returns(self):
        def row(ret, vol='10', val='100'):
            return {'FLUC_RT': ret, 'ACC_TRDVOL': vol, 'ACC_TRDVAL': val}
        last = date(2026, 9, 30)
        history = {last - timedelta(days=i): [row('0', val='250')] for i in range(1, 6)}
        history[last] = [row('1'), row('-1'), row('0'), row('10', vol='0'), row('-')]
        result = breadth(history)
        self.assertEqual(result['valid_return_rows'], 3)
        self.assertEqual(result['advancing_share_pct'], 33.33)
        self.assertEqual(result['excluded_nontraded_rows'], 1)
        self.assertEqual(result['excluded_missing_return_rows'], 1)
        self.assertEqual(result['turnover_vs_previous_5_mean'], 2)
        history[last][0]['ACC_TRDVAL'] = '-'
        with self.assertRaises(DataError):
            breadth(history)

    def test_etf_filters_and_price_return(self):
        last = date(2026, 9, 30)
        def row(name, price):
            return {'ISU_CD': name, 'ISU_NM': name, 'TDD_CLSPRC': str(price), 'ACC_TRDVOL': '10', 'ACC_TRDVAL': '2000000000'}
        history = {last - timedelta(days=i): [row('normal', 100), row('레버리지', 100)] for i in range(1, 6)}
        history[last] = [row('normal', 105), row('레버리지', 120), row('new listing', 110)]
        result = etf_strength(history)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['return_5_sessions_pct'], 5)

    def test_nonprice_series_are_not_sector_performance(self):
        for name in ['K-샤프지수(3년)', '코스피 200 변동성지수', 'KRX PER']:
            self.assertFalse(price_index(name))
        for name in ['KRX 반도체', 'KRX 고배당 50', 'KRX 정보기술']:
            self.assertTrue(price_index(name))

    def test_nonfinite_and_direct_public_output_rejected(self):
        for value in ['NaN', 'inf', '-', None]:
            self.assertIsNone(number(value))
        for output in [ROOT / 'public/krx.json', ROOT / 'data/reports/krx.json']:
            with self.assertRaises(DataError):
                save_result({}, output)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'analysis.json'
            save_result({'forecast_probability': None}, output)
            self.assertIn('null', output.read_text())


if __name__ == '__main__':
    unittest.main()
